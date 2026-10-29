import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from silicolab.features.codon import client as codon
from silicolab.server import Store, create_app


def result(payload):
    dna = ''.join({'M': 'ATG', 'K': 'AAG', 'E': 'GAG', 'F': 'TTT', '*': 'TAA'}[aa] for aa in payload['sequence'])
    return {'success': '1', 'seq': dna, 'log_id': 'test-log', 'data': []}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'jobs.sqlite3'
        self.calls = []

        def optimizer(payload):
            self.calls.append(payload)
            return result(payload)
        self.optimizer = optimizer
        self.app = create_app(self.db, optimizer, delay=0)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def create(self, sequences=('MK',), **extra):
        response = self.client.post('/api/jobs', json={
            'name': 'test job', 'species': 'Escherichia_coli', 'avoid': '',
            'records': [{'name': f'protein-{i}', 'sequence': sequence} for i, sequence in enumerate(sequences)],
            **extra,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def wait(self, job_id, statuses=None):
        statuses = statuses or {'completed', 'partial', 'failed', 'stopped', 'paused'}
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            job = self.client.get('/api/jobs/' + job_id).json()
            if job['status'] in statuses:
                return job
            time.sleep(0.01)
        self.fail('Timed out waiting for job: ' + str(job))

    def test_real_queue_checks_results_and_persists_snapshots(self):
        job_id = self.create((' mk ', 'MEF*'), avoid='GAATTC')
        job = self.wait(job_id)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]['jumpName'], 'pep')
        self.assertNotIn('userVal', self.calls[0])
        first, second = job['records']
        self.assertEqual(first['sequence'], 'MK')
        self.assertEqual(first['dna'], 'ATGAAG')
        self.assertTrue(first['checks']['translation'])
        self.assertEqual(second['checks']['bp'], 12)
        self.assertTrue(second['checks']['stop'])
        self.assertEqual(len(first['attempts']), 1)
        summary = self.client.get('/api/jobs').json()[0]
        self.assertEqual(summary['completed'], 2)
        self.assertEqual(summary['done'], 2)
        self.assertNotIn('records', summary)
        reopened = Store(self.db).get(job_id)
        self.assertEqual(reopened['records'][0]['dna'], 'ATGAAG')

    def test_invalid_batch_is_rejected_before_network(self):
        for sequence in ('MX', 'M*K', '*', ''):
            response = self.client.post('/api/jobs', json={
                'name': 'invalid', 'records': [{'name': 'bad', 'sequence': sequence}],
            })
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.client.get('/api/jobs').json(), [])

    def test_failed_record_does_not_prevent_later_success_and_retry_keeps_completed(self):
        attempts = {}
        def optimizer(payload):
            name = payload['fileName']
            attempts[name] = attempts.get(name, 0) + 1
            if name == 'protein-0' and attempts[name] == 1:
                return {'success': '0', 'msg': 'constraint warning'}
            return result(payload)
        self.app.state.worker.optimizer = optimizer
        job_id = self.create(('MK', 'MK'))
        job = self.wait(job_id)
        self.assertEqual(job['status'], 'partial')
        self.assertEqual([record['status'] for record in job['records']], ['warning', 'completed'])
        self.assertEqual(self.client.post(f'/api/jobs/{job_id}/retry').status_code, 200)
        retried = self.wait(job_id)
        self.assertEqual(retried['status'], 'completed')
        self.assertEqual(attempts, {'protein-0': 2, 'protein-1': 1})
        self.assertEqual(len(retried['records'][0]['attempts']), 2)
        self.assertEqual(retried['records'][0]['attempts'][0]['response']['success'], '0')
        self.assertEqual(self.client.post(f'/api/jobs/{job_id}/retry').status_code, 409)

    def test_translation_mismatch_is_warning_and_not_exported_as_valid_dna(self):
        self.app.state.worker.optimizer = lambda payload: {'success': '1', 'seq': 'ATGTAA'}
        job_id = self.create()
        job = self.wait(job_id)
        record = job['records'][0]
        self.assertEqual(record['status'], 'warning')
        self.assertIsNone(record['dna'])
        self.assertIn('不一致', record['error'])
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/export').status_code, 409)

    def test_stop_finishes_inflight_but_does_not_submit_remaining(self):
        entered, release = threading.Event(), threading.Event()
        def slow_optimizer(payload):
            self.calls.append(payload)
            entered.set()
            release.wait(3)
            return result(payload)
        self.app.state.worker.optimizer = slow_optimizer
        job_id = self.create(('MK', 'MK', 'MK'))
        self.assertTrue(entered.wait(2))
        response = self.client.post(f'/api/jobs/{job_id}/stop')
        self.assertEqual(response.json()['status'], 'stopping')
        self.assertEqual(self.client.post(f'/api/jobs/{job_id}/retry').status_code, 409)
        release.set()
        job = self.wait(job_id)
        self.assertEqual(job['status'], 'stopped')
        self.assertEqual([record['status'] for record in job['records']], ['completed', 'stopped', 'stopped'])
        self.assertEqual(len(self.calls), 1)

    def test_global_queue_is_serial_and_queued_job_can_be_stopped(self):
        entered, release = threading.Event(), threading.Event()
        def slow_optimizer(payload):
            self.calls.append(payload)
            entered.set()
            release.wait(3)
            return result(payload)
        self.app.state.worker.optimizer = slow_optimizer
        first = self.create()
        self.assertTrue(entered.wait(2))
        second = self.create()
        self.assertEqual(self.client.get('/api/jobs/' + second).json()['status'], 'queued')
        self.assertEqual(len(self.calls), 1)
        self.client.post(f'/api/jobs/{second}/stop')
        release.set()
        self.wait(first)
        self.assertEqual(self.wait(second)['records'][0]['status'], 'stopped')
        self.assertEqual(len(self.calls), 1)

    def test_rate_limit_pauses_remaining_records(self):
        def limited(payload):
            try:
                raise HTTPError('https://example.test', 429, 'limit', {}, None)
            except HTTPError as error:
                raise codon.OptimizationError('接口返回 HTTP 429') from error
        self.app.state.worker.optimizer = limited
        job_id = self.create(('MK', 'MK'))
        job = self.wait(job_id)
        self.assertEqual(job['status'], 'paused')
        self.assertEqual([record['status'] for record in job['records']], ['failed', 'pending'])
        self.assertIn('暂停', job['message'])

    def test_export_fasta_single_record_and_zip_with_input_and_attempts(self):
        job_id = self.create(('MK', 'MEF*'))
        job = self.wait(job_id)
        exported = self.client.get(f'/api/jobs/{job_id}/export')
        self.assertEqual(exported.status_code, 200)
        self.assertIn('attachment', exported.headers['content-disposition'])
        self.assertEqual(exported.text, '>protein-0\nATGAAG\n>protein-1\nATGGAGTTTTAA\n')
        single = self.client.get(f'/api/jobs/{job_id}/export', params={'record_id': job['records'][1]['id']})
        self.assertNotIn('protein-0', single.text)
        bundle = self.client.get(f'/api/jobs/{job_id}/export?format=zip')
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            record = json.loads(archive.read('record.json'))
            self.assertEqual(record['records'][0]['attempts'][0]['status'], 'completed')
            self.assertIn('optimized.fasta', archive.namelist())
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/export?format=pdf').status_code, 400)
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}/export?record_id=missing').status_code, 404)

    def test_presets_roundtrip_and_validation(self):
        response = self.client.post('/api/presets', json={'name': 'Golden Gate', 'species': 'Escherichia_coli', 'avoid': 'ggtctc,CGTCTC'})
        self.assertEqual(response.status_code, 201)
        preset = response.json()
        self.assertEqual(preset['avoid'], 'GGTCTC,CGTCTC')
        self.assertEqual(self.client.get('/api/presets').json()[0]['id'], preset['id'])
        self.assertEqual(self.client.post('/api/presets', json={'name': ' ', 'avoid': ''}).status_code, 422)
        self.assertEqual(self.client.post('/api/presets', json={'name': 'bad', 'avoid': 'EcoRI'}).status_code, 422)
        self.assertEqual(self.client.delete('/api/presets/' + preset['id']).status_code, 200)
        self.assertEqual(self.client.get('/api/presets').json(), [])

    def test_restart_marks_unfinished_records_interrupted_without_resubmitting(self):
        job_id = self.create()
        self.wait(job_id)
        store = self.app.state.store
        def interrupted(job):
            job['status'] = 'running'
            job['records'].append({'id': 'unfinished', 'name': 'next', 'sequence': 'MK', 'status': 'running'})
        store.mutate(job_id, interrupted)
        recovered = Store(self.db).get(job_id)
        self.assertEqual(recovered['status'], 'interrupted')
        self.assertEqual(recovered['records'][0]['status'], 'completed')
        self.assertEqual(recovered['records'][1]['status'], 'interrupted')
        self.assertEqual(len(self.calls), 1)

    def test_external_origin_and_host_are_rejected(self):
        self.assertEqual(self.client.post('/api/jobs', headers={'Origin': 'https://evil.example'}, json={}).status_code, 403)
        self.assertEqual(self.client.get('/api/health', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/health', headers={'Origin': 'http://127.0.0.1:5173'}).status_code, 200)

    def test_species_uses_cached_fallback_on_outage(self):
        with patch('silicolab.server.codon.list_species', side_effect=codon.OptimizationError('offline')):
            data = self.client.get('/api/species').json()
        self.assertFalse(data['online'])
        self.assertIn('D2P(default)', data['items'])
        with patch('silicolab.server.codon.list_species', return_value=['Escherichia_coli']):
            refreshed = self.client.get('/api/species?refresh=true').json()
        self.assertTrue(refreshed['online'])
        self.assertEqual(refreshed['items'], ['D2P(default)', 'Escherichia_coli'])

    def test_missing_task_is_404(self):
        self.assertEqual(self.client.get('/api/jobs/missing').status_code, 404)
        self.assertEqual(self.client.post('/api/jobs/missing/retry').status_code, 404)


if __name__ == '__main__':
    unittest.main()
