"""Performance regression seams: no large history decoding in hot paths; lazy XLSX load."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from silicolab.server import Store, create_app, summary


def synthetic_job(index, status='completed'):
    return {'id': f'job-{index}', 'name': f'job {index}', 'species': 'D2P(default)', 'avoid': '',
            'status': status, 'created_at': f'2026-01-01T00:00:{index:02d}', 'message': None,
            'records': [{'id': f'record-{index}', 'name': 'synthetic', 'sequence': 'M' * 1000,
                         'status': 'completed', 'dna': 'ATG' * 1000,
                         'response': {'success': '1', 'seq': 'ATG' * 1000, 'data': ['x' * 1000] * 100},
                         'attempts': [], 'checks': None, 'error': None}]}


class PerformanceRegressionTests(unittest.TestCase):
    def test_idle_history_and_health_never_load_full_job_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / 'db.sqlite3', delay=0)
            for index in range(8):
                app.state.store.save(synthetic_job(index))
            with TestClient(app) as client, patch.object(Store, 'jobs', side_effect=AssertionError('Full history decode is forbidden')):
                self.assertEqual(client.get('/api/health').json()['active'], 0)
                rows = client.get('/api/jobs').json()
                self.assertEqual(len(rows), 8)
                self.assertNotIn('records', rows[0])

    def test_create_app_does_not_import_excel_library_until_requested(self):
        command = [sys.executable, '-c', 'from silicolab import server; import sys,tempfile; from pathlib import Path; '
                   't=tempfile.TemporaryDirectory(); app=server.create_app(Path(t.name)/"db.sqlite3"); '
                   'assert "openpyxl" not in sys.modules, "XLSX eagerly loaded"']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_summary_index_tracks_updates_and_restart_without_decoding_complete_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite3'
            store = Store(path)
            job = synthetic_job(1)
            store.save(job)
            expected = summary(store.get(job['id']))
            self.assertEqual(store.summaries(), [expected])
            with patch('silicolab.server.json.loads', side_effect=AssertionError('Startup must use SQL metadata only')):
                reopened = Store(path)
            self.assertEqual(reopened.summaries(), [expected])

    def test_compact_job_view_omits_raw_codon_data_but_export_keeps_it(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / 'db.sqlite3')
            app.state.store.save(synthetic_job(1))
            with TestClient(app) as client:
                full = client.get('/api/jobs/job-1').json()
                compact = client.get('/api/jobs/job-1?compact=true').json()
                self.assertEqual(compact['records'][0]['dna'], full['records'][0]['dna'])
                self.assertNotIn('data', compact['records'][0]['response'])
                self.assertIn('data', full['records'][0]['response'])
                self.assertLess(len(json.dumps(compact)), len(json.dumps(full)) / 5)


if __name__ == '__main__':
    unittest.main()
