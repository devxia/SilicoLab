"""Selected import and immutable task inputs through the application contract."""
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app_fixture import create_app


class WorkbenchInputTests(unittest.TestCase):
    def test_selected_import_and_fixed_task_bytes_survive_edit_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            original = root / 'original.fasta'
            original.write_text('>first\nMK*\n')
            untouched = root / 'not-selected.txt'
            untouched.write_text('DO_NOT_IMPORT')
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(project)}).json()['id']
                chat = client.post(f'/api/workbench/projects/{identity}/conversations', json={'title': '来源核对'}).json()
                url = f'/api/workbench/projects/{identity}'
                imported_response = client.post(url + '/files', json={'name': original.name, 'contentBase64': base64.b64encode(original.read_bytes()).decode()})
                self.assertEqual(imported_response.status_code, 201, imported_response.text)
                imported = imported_response.json()
                second = client.post(url + '/files', json={'name': original.name, 'contentBase64': base64.b64encode(b'>second\nMEF*\n').decode()}).json()
                self.assertNotEqual(second['path'], imported['path'])
                first_version_response = client.post(url + '/input-versions', json={'conversationId': chat['id'], 'fileIds': [imported['id']]})
                self.assertEqual(first_version_response.status_code, 201, first_version_response.text)
                first_version = first_version_response.json()
                self.assertNotEqual(first_version['id'], chat['id'])
                fixed = first_version['inputs'][0]
                self.assertEqual(fixed['sha256'], hashlib.sha256(original.read_bytes()).hexdigest())
                (project / imported['path']).write_bytes(b'>updated\nMKK*\n')
                original.write_text('CHANGED_EXTERNAL_ORIGINAL')
                old = client.get(url + f'/input-versions/{first_version["id"]}').json()
                self.assertEqual(base64.b64decode(old['inputs'][0]['contentBase64']), b'>first\nMK*\n')
                new = client.post(url + '/input-versions', json={'conversationId': chat['id'], 'fileIds': [imported['id']]}).json()
                self.assertEqual(base64.b64decode(new['inputs'][0]['contentBase64']), b'>updated\nMKK*\n')
                self.assertEqual(new['inputs'][0]['version'], 2)
                self.assertEqual(fixed['version'], 1)
                self.assertNotEqual(new['inputs'][0]['sha256'], fixed['sha256'])
                listing = client.get(url).json()
                self.assertEqual(len(listing['files']), 2)
                self.assertEqual(len(listing['inputVersions']), 2)
                self.assertFalse(any('not-selected' in str(p) for p in project.rglob('*')))
                self.assertEqual((project / second['path']).read_bytes(), b'>second\nMEF*\n')
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(project)}).json()
                old = client.get(f'/api/workbench/projects/{reopened["id"]}/input-versions/{first_version["id"]}').json()
                self.assertEqual(base64.b64decode(old['inputs'][0]['contentBase64']), b'>first\nMK*\n')
                self.assertEqual(untouched.read_text(), 'DO_NOT_IMPORT')

    def test_import_rejects_invalid_names_and_snapshot_detects_tampering_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            sentinel = root / 'outside.txt'
            sentinel.write_text('DO_NOT_READ')
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(project)}).json()['id']
                url = f'/api/workbench/projects/{identity}'
                chat = client.post(url + '/conversations', json={'title': 'test'}).json()
                for name in ['../outside.txt', '.', 'a/b', 'a\\b']:
                    self.assertEqual(client.post(url + '/files', json={'name': name, 'contentBase64': 'TUs='}).status_code, 409)
                self.assertEqual(client.post(url + '/files', json={'name': 'bad', 'contentBase64': '%%%invalid'}).status_code, 409)
                imported = client.post(url + '/files', json={'name': 'protein.fa', 'contentBase64': 'TUs='}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat['id'], 'fileIds': [imported['id']]}).json()
                (project / fixed['inputs'][0]['path']).write_text('tampered')
                read = client.get(url + '/input-versions/' + fixed['id'])
                self.assertEqual(read.status_code, 409, read.text)
                (project / imported['path']).unlink()
                (project / imported['path']).symlink_to(sentinel)
                failed = client.post(url + '/input-versions', json={'conversationId': chat['id'], 'fileIds': [imported['id']]})
                self.assertEqual(failed.status_code, 409, failed.text)
                self.assertNotIn('DO_NOT_READ', failed.text)
                self.assertEqual(len(client.get(url).json()['inputVersions']), 1)
                self.assertEqual(sentinel.read_text(), 'DO_NOT_READ')

    def test_multi_file_freeze_is_not_committed_when_any_source_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(project)}).json()['id']
                url = f'/api/workbench/projects/{identity}'
                chat = client.post(url + '/conversations', json={'title': 'multiple files'}).json()
                sources = [client.post(url + '/files', json={'name': f'{index}.fa', 'contentBase64': 'TUs='}).json() for index in range(2)]
                (project / sources[1]['path']).unlink()
                failed = client.post(url + '/input-versions', json={'conversationId': chat['id'], 'fileIds': [item['id'] for item in sources]})
                self.assertEqual(failed.status_code, 409, failed.text)
                self.assertEqual(client.get(url).json()['inputVersions'], [])
                self.assertEqual(list((project / '.silicolab/inputs').glob('*')), [])
                self.assertEqual((project / sources[0]['path']).read_bytes(), b'MK')
                duplicate = client.post(url + '/input-versions', json={'conversationId': chat['id'], 'fileIds': [sources[0]['id']] * 2})
                self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_utf8_preview_truncates_without_misclassifying_multibyte_text(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'project'
            project.mkdir()
            with TestClient(create_app(Path(directory) / 'app.sqlite3', delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(project)}).json()['id']
                url = f'/api/workbench/projects/{identity}'
                content = ('a' * 7999 + '中').encode()
                imported = client.post(url + '/files', json={'name': 'utf8.txt', 'contentBase64': base64.b64encode(content).decode()}).json()
                preview = client.get(url + '/files/' + imported['id']).json()
                self.assertEqual(preview['text'], 'a' * 7999)
                self.assertTrue(preview['truncated'])
                self.assertEqual(preview['currentSize'], len(content))


if __name__ == '__main__':
    unittest.main()
