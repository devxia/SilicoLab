"""Workbench contract with a real Node harness and temporary project storage."""
import os
import signal
import shutil
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from silicolab.server import create_app


class WorkbenchTests(unittest.TestCase):
    def test_create_multiple_conversations_save_and_reopen_in_chosen_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'selected-project'
            project.mkdir()
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                response = client.post('/api/workbench/projects', json={'path': str(project), 'name': '人工研究'})
                self.assertEqual(response.status_code, 201, response.text)
                saved = response.json()
                self.assertEqual(saved['name'], '人工研究')
                self.assertEqual(saved['conversations'], [])
                identity = saved['id']
                first = client.post(f'/api/workbench/projects/{identity}/conversations', json={'title': '序列分析'}).json()
                second = client.post(f'/api/workbench/projects/{identity}/conversations', json={'title': '另一思路'}).json()
                self.assertNotEqual(first['id'], second['id'])
                draft = client.put(f'/api/workbench/projects/{identity}/conversations/{first["id"]}/draft', json={'text': '保留这个科研目标', 'revision': 0})
                self.assertEqual(draft.status_code, 200, draft.text)
                self.assertEqual(draft.json()['revision'], 1)
                duplicate = client.post('/api/workbench/projects/open', json={'path': str(project)}).json()
                self.assertEqual(duplicate['id'], identity)
                self.assertEqual(len(duplicate['conversations']), 2)
                self.assertEqual(duplicate['modelRequests'], 0)
            # New application + new Node process, not a reused React/host memory.
            with TestClient(create_app(database, delay=0)) as client:
                listed = client.get('/api/workbench/projects').json()
                self.assertEqual(listed[0]['id'], identity)
                reopened = client.post('/api/workbench/projects/open', json={'path': str(project)}).json()
                self.assertEqual(reopened['id'], identity)
                self.assertEqual(reopened['conversations'][0]['draft'], '保留这个科研目标')
                self.assertEqual(reopened['conversations'][1]['draft'], '')
                self.assertEqual(reopened['tasks'], [])
                self.assertEqual(reopened['modelRequests'], 0)
            self.assertTrue((project / '.silicolab' / 'session.sqlite').is_file())
            self.assertEqual(list(project.glob('*.sqlite*')), [])

    def test_second_app_and_symlink_alias_cannot_take_project_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            alias = root / 'alias'
            alias.symlink_to(project, target_is_directory=True)
            with TestClient(create_app(root / 'app1.sqlite3', delay=0)) as first:
                created = first.post('/api/workbench/projects', json={'path': str(project)}).json()
                duplicate = first.post('/api/workbench/projects/open', json={'path': str(alias)})
                self.assertEqual(duplicate.json()['id'], created['id'])
                with TestClient(create_app(root / 'app2.sqlite3', delay=0)) as second:
                    denied = second.post('/api/workbench/projects/open', json={'path': str(alias)})
                    self.assertEqual(denied.status_code, 409, denied.text)
                self.assertEqual(first.get(f'/api/workbench/projects/{created["id"]}').status_code, 200)
            with TestClient(create_app(root / 'app2.sqlite3', delay=0)) as second:
                recovered = second.post('/api/workbench/projects/open', json={'path': str(alias)})
                self.assertEqual(recovered.json()['id'], created['id'])

    def test_stale_draft_does_not_overwrite_and_unknown_project_does_not_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                created = client.post('/api/workbench/projects', json={'path': str(project)}).json()
                identity = created['id']
                chat = client.post(f'/api/workbench/projects/{identity}/conversations', json={'title': '决定'}).json()
                url = f'/api/workbench/projects/{identity}/conversations/{chat["id"]}/draft'
                self.assertEqual(client.put(url, json={'text': 'first', 'revision': 0}).status_code, 200)
                self.assertEqual(client.put(url, json={'text': 'overwrite', 'revision': 0}).status_code, 409)
                state = client.get(f'/api/workbench/projects/{identity}').json()
                self.assertEqual(state['path'], str(project.resolve()))
                self.assertEqual(state['conversations'][0]['draft'], 'first')
                other = root / 'not-a-project'
                other.mkdir()
                self.assertEqual(client.post('/api/workbench/projects/open', json={'path': str(other)}).status_code, 409)
                self.assertFalse((other / '.silicolab').exists())
                self.assertEqual(client.post('/api/workbench/projects', json={'path': str(other)}, headers={'Origin': 'https://evil.invalid'}).status_code, 403)

    def test_replaced_project_directory_rejects_mutating_the_other_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_a, project_b = root / 'A', root / 'B'
            project_a.mkdir()
            project_b.mkdir()
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                a = client.post('/api/workbench/projects', json={'path': str(project_a)}).json()
                b = client.post('/api/workbench/projects', json={'path': str(project_b)}).json()
            shutil.rmtree(project_a / '.silicolab')
            shutil.copytree(project_b / '.silicolab', project_a / '.silicolab')
            with TestClient(create_app(database, delay=0)) as client:
                response = client.post(f'/api/workbench/projects/{a["id"]}/conversations', json={'title': 'must not be written'})
                self.assertEqual(response.status_code, 409, response.text)
                opened = client.post('/api/workbench/projects/open', json={'path': str(project_a)}).json()
                self.assertEqual(opened['id'], b['id'])
                self.assertEqual(opened['conversations'], [])

    def test_corrupt_app_index_preserves_file_and_allows_explicit_project_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                created = client.post('/api/workbench/projects', json={'path': str(project)}).json()
            for corruption in ['{bad-json', '{}', '[{"id": 5}]']:
                index = root / 'projects.json'
                index.write_text(corruption)
                with TestClient(create_app(database, delay=0)) as client:
                    self.assertEqual(client.get('/api/health').status_code, 200)
                    self.assertEqual(client.get('/api/workbench/projects').status_code, 409)
                    self.assertEqual(index.read_text(), corruption)
                    reopened = client.post('/api/workbench/projects/open', json={'path': str(project)})
                    self.assertEqual(reopened.status_code, 200, reopened.text)
                    self.assertEqual(reopened.json()['id'], created['id'])
                    self.assertEqual(client.get('/api/workbench/projects').status_code, 200)
                self.assertTrue(any(path.read_text() == corruption for path in root.glob('projects.corrupt-*.json')))

    def test_dead_node_host_can_be_reopened_without_running_any_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                created = client.post('/api/workbench/projects', json={'path': str(project)}).json()
                os.kill(created['runtimePid'], signal.SIGKILL)
                import time
                time.sleep(0.05)
                reopened = client.post('/api/workbench/projects/open', json={'path': str(project)})
                self.assertEqual(reopened.status_code, 200, reopened.text)
                saved = reopened.json()
                self.assertEqual(saved['id'], created['id'])
                self.assertNotEqual(saved['runtimePid'], created['runtimePid'])
                self.assertEqual(saved['modelRequests'], 0)
                self.assertEqual(saved['scheduling'], 'paused')


if __name__ == '__main__':
    unittest.main()
