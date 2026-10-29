"""Deletion tests use temporary databases and synthetic jobs only."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from silicolab.server import ACTIVE, Store, create_app


def job(identifier, status='completed'):
    return {'id': identifier, 'name': 'synthetic ' + identifier, 'species': 'D2P(default)', 'avoid': '',
            'engine': 'remote', 'created_at': '2026-10-29T00:00:00Z', 'status': status, 'message': None,
            'records': [{'id': 'r-' + identifier, 'name': 'protein', 'sequence': 'MK', 'dna': 'ATGAAG',
                         'status': 'completed', 'checks': {}, 'response': {'success': '1', 'seq': 'ATGAAG'},
                         'attempts': [{'response': {'success': '1'}}], 'error': None}]}


class JobDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'db.sqlite3'
        self.app = create_app(self.path, delay=0)
        self.store = self.app.state.store
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def assert_exists(self, identifier, exists):
        with closing(sqlite3.connect(self.path)) as db:
            for table in ['jobs', 'job_index']:
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table} WHERE id=?', (identifier,)).fetchone()[0], int(exists))

    def test_single_delete_removes_raw_and_index_and_survives_reopen(self):
        self.store.save(job('a'))
        self.store.save(job('keep'))
        revision = self.store.revision
        response = self.client.delete('/api/jobs/a')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deleted_ids'], ['a'])
        self.assertEqual(self.store.revision, revision + 1)
        self.assert_exists('a', False)
        self.assertEqual(self.client.get('/api/jobs/a').status_code, 404)
        self.assertEqual(self.client.get('/api/jobs/a/export').status_code, 404)
        reopened = Store(self.path)
        self.assertEqual([row['id'] for row in reopened.summaries()], ['keep'])
        self.assertEqual(reopened.get('keep')['records'][0]['attempts'], job('keep')['records'][0]['attempts'])

    def test_batch_deletes_selected_only_and_deduplicates(self):
        for identifier in ['a', 'b', 'c']:
            self.store.save(job(identifier))
        response = self.client.post('/api/jobs/bulk-delete', json={'ids': ['a', 'b', 'a']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'deleted_ids': ['a', 'b'], 'deleted_count': 2})
        self.assert_exists('a', False)
        self.assert_exists('b', False)
        self.assert_exists('c', True)

    def test_protected_statuses_rejected_and_entire_batch_unchanged(self):
        self.store.save(job('safe'))
        for status in ACTIVE:
            identifier = 'active-' + status
            self.store.save(job(identifier, status))
            revision = self.store.revision
            response = self.client.post('/api/jobs/bulk-delete', json={'ids': ['safe', identifier]})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(self.client.delete('/api/jobs/' + identifier).status_code, 409)
            self.assertEqual(self.store.revision, revision)
            self.assert_exists('safe', True)
            self.assert_exists(identifier, True)

    def test_all_inactive_states_are_deletable(self):
        for status in ['completed', 'partial', 'failed', 'warning', 'stopped', 'interrupted', 'paused']:
            self.store.save(job(status, status))
            self.assertEqual(self.client.delete('/api/jobs/' + status).status_code, 200)

    def test_missing_id_rejects_entire_batch_without_partial_deletion(self):
        self.store.save(job('a'))
        self.assertEqual(self.client.delete('/api/jobs/absent').status_code, 404)
        self.assertEqual(self.client.post('/api/jobs/bulk-delete', json={'ids': ['a', 'absent']}).status_code, 404)
        self.assert_exists('a', True)

    def test_transaction_rollback_if_second_table_delete_fails(self):
        self.store.save(job('a'))
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER reject_index_delete BEFORE DELETE ON job_index BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        revision = self.store.revision
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.delete_jobs(['a'])
        self.assertEqual(self.store.revision, revision)
        self.assert_exists('a', True)

    def test_delete_uses_index_status_not_full_history(self):
        self.store.save(job('a'))
        with patch.object(Store, 'jobs', side_effect=AssertionError('No full history')), patch.object(Store, 'get', side_effect=AssertionError('No full task decode')):
            self.assertEqual(self.client.delete('/api/jobs/a').status_code, 200)

    def test_deletion_does_not_remove_exports_or_presets(self):
        exported = Path(self.temp.name) / 'export.fasta'
        exported.write_text('>protein\nATGAAG\n')
        self.store.save(job('a'))
        self.store.save_preset({'id': 'p', 'name': 'preset', 'engine': 'remote', 'species': 'D2P(default)', 'avoid': ''})
        self.client.delete('/api/jobs/a')
        self.assertEqual(exported.read_text(), '>protein\nATGAAG\n')
        self.assertEqual(len(self.client.get('/api/presets').json()), 1)

    def test_invalid_batch_is_rejected_without_deletion(self):
        self.store.save(job('a'))
        for ids in [[], [''], ['a'] * 1001, [7], 'a']:
            response = self.client.post('/api/jobs/bulk-delete', json={'ids': ids})
            self.assertEqual(response.status_code, 422)
            self.assert_exists('a', True)

    def test_backend_rechecks_status_after_user_selected_finished_job(self):
        self.store.save(job('a', 'failed'))
        self.store.mutate('a', lambda current: current.update(status='queued'))
        self.assertEqual(self.client.delete('/api/jobs/a').status_code, 409)
        self.assert_exists('a', True)

    def test_delete_and_retry_like_mutation_are_serialized(self):
        self.store.save(job('a', 'failed'))
        entered, release = threading.Event(), threading.Event()
        def update(current):
            entered.set()
            release.wait(2)
            current['status'] = 'queued'
        thread = threading.Thread(target=lambda: self.store.mutate('a', update))
        thread.start()
        self.assertTrue(entered.wait(1))
        result = []
        def delete():
            try:
                self.store.delete_jobs(['a'])
            except HTTPException as exc:
                result.append(exc.status_code)
        deleter = threading.Thread(target=delete)
        deleter.start()
        release.set()
        thread.join(2)
        deleter.join(2)
        self.assertEqual(result, [409])
        self.assert_exists('a', True)

    def test_external_origin_cannot_delete(self):
        self.store.save(job('a'))
        self.assertEqual(self.client.delete('/api/jobs/a', headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assert_exists('a', True)


if __name__ == '__main__':
    unittest.main()
