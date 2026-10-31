"""Real temporary directory failures, relocation identity and non-destructive unlink."""
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import threading

from silicolab.workbench import ProjectHost

from fastapi.testclient import TestClient
from app_fixture import create_app
from test_model_configuration import FakeModelEndpoint, MemorySecrets
from test_workbench_recovery import wait_state
from test_workbench_science import wait_task


class ProjectAvailabilityTests(unittest.TestCase):
    def test_move_while_request_inflight_stops_only_that_host_and_requires_verified_relocation(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-offline', 'hold') as endpoint:
            root = Path(directory)
            a, b = root / 'A', root / 'B'
            a.mkdir(); b.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                projects = [client.post('/api/workbench/projects', json={'path': str(p)}).json() for p in (a, b)]
                url = '/api/workbench/projects/' + projects[0]['id']
                other = '/api/workbench/projects/' + projects[1]['id']
                chat = client.post(url + '/conversations', json={'title': 'move running'}).json()['id']
                cfg = client.post('/api/workbench/model-configs', json={'name': 'artificial', 'protocol': endpoint.protocol, 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': endpoint.key}).json()
                client.put(url + f'/conversations/{chat}/model', json={'configurationId': cfg['id']})
                imported = client.post(url + '/files', json={'name': 'artificial.fa', 'contentBase64': base64.b64encode(b'>a\nMK*\n').decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'move', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                self.assertTrue(endpoint.entered.wait(5))
                moved = root / 'moved-A'
                a.rename(moved)
                state = wait_state(client, url, lambda s: s.get('availability', {}).get('status') == 'offline')
                self.assertFalse(state['availability']['progressSaved'])
                self.assertIn('目录', state['availability']['reason'])
                with self.assertRaises(ProcessLookupError):
                    os.kill(projects[0]['runtimePid'], 0)
                self.assertEqual(client.post(url + '/conversations', json={'title': 'must not create'}).status_code, 409)
                self.assertFalse(a.exists())
                c2 = client.post(other + '/conversations', json={'title': 'unaffected'}).json()['id']
                t2 = client.post(other + '/tasks', json={'conversationId': c2, 'requestId': 'ok', 'goal': 'XYZ', 'authorizedTools': ['synthetic_count']}).json()
                self.assertEqual(wait_task(client, other, c2, t2['id'])['toolExecutions'][0]['result']['characters'], 3)
                empty = root / 'empty'
                empty.mkdir()
                self.assertEqual(client.post(url + '/relocate', json={'path': str(empty)}).status_code, 409)
                self.assertFalse((empty / '.silicolab').exists())
                located = client.post(url + '/relocate', json={'path': str(moved)})
                self.assertEqual(located.status_code, 200, located.text)
                restored = located.json()
                self.assertEqual(restored['id'], projects[0]['id'])
                self.assertEqual(restored['tasks'][0]['status'], 'paused')
                self.assertEqual(restored['inputVersions'][0]['id'], fixed['id'])
                self.assertEqual(len(endpoint.requests), 1)
                endpoint.release.set()
                client.put(url + f'/conversations/{chat}/model', json={'configurationId': None})
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/resume').status_code, 200)
                self.assertEqual(wait_task(client, url, chat, task['id'])['status'], 'answered')
                self.assertEqual(len(endpoint.requests), 1)

    def test_readonly_and_disconnect_do_not_claim_saved_or_create_substitute_then_remove_keeps_bytes(self):
        for failure in ('readonly', 'disconnect'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / 'project'
                project.mkdir()
                database = root / 'app.sqlite3'
                with TestClient(create_app(database, delay=0)) as client:
                    opened = client.post('/api/workbench/projects', json={'path': str(project)}).json()
                    url = '/api/workbench/projects/' + opened['id']
                    chat = client.post(url + '/conversations', json={'title': 'preserved'}).json()['id']
                    client.put(url + f'/conversations/{chat}/draft', json={'text': 'saved-before-failure', 'revision': 0})
                    if failure == 'readonly':
                        (project / '.silicolab').chmod(0o500)
                    else:
                        project.rename(root / 'disconnected')
                    try:
                        state = wait_state(client, url, lambda s: s.get('availability', {}).get('status') == 'offline')
                        self.assertFalse(state['availability']['progressSaved'])
                        self.assertEqual(client.put(url + f'/conversations/{chat}/draft', json={'text': 'must not save', 'revision': 1}).status_code, 409)
                    finally:
                        if failure == 'readonly': (project / '.silicolab').chmod(0o700)
                        else: (root / 'disconnected').rename(project)
                    relocated = client.post(url + '/relocate', json={'path': str(project)})
                    self.assertEqual(relocated.status_code, 200, relocated.text)
                    self.assertEqual(relocated.json()['conversations'][0]['draft'], 'saved-before-failure')
                    snapshot = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file() and p.suffix not in ('.sqlite',) and not p.name.endswith(('-wal', '-shm'))}
                    removed = client.delete(url)
                    self.assertEqual(removed.status_code, 200, removed.text)
                    self.assertEqual(client.get('/api/workbench/projects').json(), [])
                    self.assertTrue((project / '.silicolab/session.sqlite').is_file())
                    for path, content in snapshot.items(): self.assertEqual((project / path).read_bytes(), content)
                    reopened = client.post('/api/workbench/projects/open', json={'path': str(project)}).json()
                    self.assertEqual(reopened['id'], opened['id'])
                    self.assertEqual(reopened['conversations'][0]['id'], chat)

    def test_relocation_rejects_other_project_and_corrupt_fixed_input_without_rebinding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / 'A', root / 'B'
            a.mkdir(); b.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                original = client.post('/api/workbench/projects', json={'path': str(a)}).json()
                another = client.post('/api/workbench/projects', json={'path': str(b)}).json()
                url = '/api/workbench/projects/' + original['id']
                chat = client.post(url + '/conversations', json={'title': 'fixed'}).json()['id']
                imported = client.post(url + '/files', json={'name': 'source.txt', 'contentBase64': base64.b64encode(b'artificial original').decode()}).json()
                version = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                moved = root / 'moved'
                a.rename(moved)
                wait_state(client, url, lambda s: s.get('availability', {}).get('status') == 'offline')
                self.assertEqual(client.post(url + '/relocate', json={'path': str(b)}).status_code, 409)
                self.assertEqual(client.get('/api/workbench/projects/' + another['id']).json()['conversations'], [])
                saved_path = moved / version['inputs'][0]['path']
                saved_path.write_text('tampered artificial input')
                rejected = client.post(url + '/relocate', json={'path': str(moved)})
                self.assertEqual(rejected.status_code, 409, rejected.text)
                ordinary = client.post('/api/workbench/projects/open', json={'path': str(moved)})
                self.assertEqual(ordinary.status_code, 409, ordinary.text)
                create_existing = client.post('/api/workbench/projects', json={'path': str(moved)})
                self.assertEqual(create_existing.status_code, 409, create_existing.text)
                self.assertEqual(next(p for p in client.get('/api/workbench/projects').json() if p['id'] == original['id'])['path'], str(a.resolve()))
                saved_path.write_bytes(b'artificial original')
                accepted = client.post('/api/workbench/projects/open', json={'path': str(moved)})
                self.assertEqual(accepted.status_code, 200, accepted.text)
                self.assertEqual(accepted.json()['inputVersions'][0]['id'], version['id'])

    def test_create_unlinked_existing_project_cannot_bypass_integrity_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / 'project'; project.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                original = client.post('/api/workbench/projects', json={'path': str(project)}).json()
                url = '/api/workbench/projects/' + original['id']
                chat = client.post(url + '/conversations', json={'title': 'unlinked integrity'}).json()['id']
                imported = client.post(url + '/files', json={'name': 'source.txt', 'contentBase64': base64.b64encode(b'original artificial bytes').decode()}).json()
                version = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                self.assertEqual(client.delete(url).status_code, 200)
                fixed = project / version['inputs'][0]['path']
                fixed.write_bytes(b'tampered artificial bytes')
                rejected = client.post('/api/workbench/projects', json={'path': str(project)})
                self.assertEqual(rejected.status_code, 409, rejected.text)
                self.assertEqual(client.get('/api/workbench/projects').json(), [])
                fixed.write_bytes(b'original artificial bytes')
                accepted = client.post('/api/workbench/projects', json={'path': str(project)})
                self.assertEqual(accepted.status_code, 201, accepted.text)
                self.assertEqual(accepted.json()['id'], original['id'])

    def test_index_publication_failure_keeps_old_memory_and_disk_association(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'; project.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                original = client.post('/api/workbench/projects', json={'path': str(project)}).json()
                url = '/api/workbench/projects/' + original['id']
                index = (root / 'projects.json').read_bytes()
                moved = root / 'moved'; project.rename(moved)
                wait_state(client, url, lambda s: s.get('availability', {}).get('status') == 'offline')
                replace = Path.replace
                def fail_index(path, target):
                    if Path(target) == root / 'projects.json': raise PermissionError('artificial index write failure')
                    return replace(path, target)
                with patch.object(Path, 'replace', fail_index):
                    rejected = client.post(url + '/relocate', json={'path': str(moved)})
                    self.assertEqual(rejected.status_code, 409, rejected.text)
                self.assertEqual((root / 'projects.json').read_bytes(), index)
                self.assertEqual(client.get('/api/workbench/projects').json()[0]['path'], original['path'])
                self.assertEqual(client.get(url).json()['availability']['status'], 'offline')
                self.assertEqual(client.post(url + '/relocate', json={'path': str(moved)}).status_code, 200)

    def test_stale_offline_observer_cannot_poison_successful_relocation(self):
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=2) as pool:
            root = Path(directory); project = root / 'project'; project.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                original = client.post('/api/workbench/projects', json={'path': str(project)}).json()
                url = '/api/workbench/projects/' + original['id']
                entered, release = threading.Event(), threading.Event()
                observe = ProjectHost.offline_snapshot
                def delayed(host):
                    snapshot = observe(host); entered.set(); release.wait(5); return snapshot
                moved = root / 'moved'; project.rename(moved)
                with patch.object(ProjectHost, 'offline_snapshot', delayed):
                    status = pool.submit(client.get, url)
                    self.assertTrue(entered.wait(5))
                    relocated = pool.submit(client.post, url + '/relocate', json={'path': str(moved)})
                    try: relocated.result(timeout=2)
                    except FutureTimeout: pass
                    finally: release.set()
                    self.assertEqual(status.result(timeout=10).status_code, 200)
                    self.assertEqual(relocated.result(timeout=10).status_code, 200)
                self.assertEqual(client.get(url).json()['availability']['status'], 'online')
                self.assertEqual(client.post(url + '/conversations', json={'title': 'new host remains writable'}).status_code, 201)

    def test_remove_and_new_admission_have_one_project_lifecycle_order(self):
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=2) as pool:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                opened = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = '/api/workbench/projects/' + opened['id']
                chat = client.post(url + '/conversations', json={'title': 'atomic remove'}).json()['id']
                entered, release = threading.Event(), threading.Event()
                operation = ProjectHost.call
                def delayed(host, op, **values):
                    result = operation(host, op, **values)
                    if op == 'status' and not entered.is_set():
                        entered.set(); release.wait(5)
                    return result
                with patch.object(ProjectHost, 'call', delayed):
                    removal = pool.submit(client.delete, url)
                    self.assertTrue(entered.wait(5))
                    admission = pool.submit(client.post, url + '/tasks', json={'conversationId': chat, 'requestId': 'raced', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']})
                    try: admission.result(timeout=0.25)
                    except FutureTimeout: pass
                    finally: release.set()
                    deleted, started = removal.result(timeout=10), admission.result(timeout=10)
                self.assertFalse(deleted.status_code == 200 and started.status_code == 201, 'must not acknowledge a new task then remove it implicitly')
                self.assertTrue((root / '.silicolab/session.sqlite').is_file())

    def test_relocation_content_verification_does_not_block_other_project(self):
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=2) as pool:
            root = Path(directory)
            a, b = root / 'A', root / 'B'; a.mkdir(); b.mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                projects = [client.post('/api/workbench/projects', json={'path': str(p)}).json() for p in (a, b)]
                first = '/api/workbench/projects/' + projects[0]['id']; second = '/api/workbench/projects/' + projects[1]['id']
                moved = root / 'moved'; a.rename(moved)
                wait_state(client, first, lambda s: s.get('availability', {}).get('status') == 'offline')
                entered, release = threading.Event(), threading.Event()
                operation = ProjectHost.call
                def delayed(host, op, **values):
                    if op == 'project.verify': entered.set(); release.wait(5)
                    return operation(host, op, **values)
                with patch.object(ProjectHost, 'call', delayed):
                    relocation = pool.submit(client.post, first + '/relocate', json={'path': str(moved)})
                    self.assertTrue(entered.wait(5))
                    other = pool.submit(client.post, second + '/conversations', json={'title': 'independent admission'})
                    try: self.assertEqual(other.result(timeout=1).status_code, 201)
                    finally: release.set()
                    self.assertEqual(relocation.result(timeout=10).status_code, 200)

    def test_remove_refuses_active_work_until_explicit_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                opened = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = '/api/workbench/projects/' + opened['id']
                chat = client.post(url + '/conversations', json={'title': 'active'}).json()['id']
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                self.assertEqual(client.delete(url).status_code, 409)
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/pause').status_code, 200)
                self.assertEqual(client.delete(url).status_code, 200)
                self.assertTrue((root / '.silicolab/session.sqlite').is_file())


if __name__ == '__main__':
    unittest.main()
