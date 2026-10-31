"""Project admission FIFO, real cross-project overlap, waiting/paused slot release."""
import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from app_fixture import create_app
from test_workbench_science import wait_task


class ProjectSchedulingTests(unittest.TestCase):
    def test_same_project_queues_fifo_with_one_real_active_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'FIFO'}).json()['id']
                first = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'one', 'goal': 'AAA', 'authorizedTools': ['synthetic_count']}).json()
                response = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'two', 'goal': 'BBBB', 'authorizedTools': ['synthetic_count']})
                self.assertEqual(response.status_code, 201, response.text)
                second = response.json()
                self.assertEqual(second['status'], 'queued')
                third = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'three', 'goal': 'CCCCC', 'authorizedTools': ['synthetic_count']}).json()
                self.assertEqual(third['status'], 'queued')
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    tasks = client.get(url + f'/conversations/{chat}').json()['tasks']
                    self.assertLessEqual(sum(task['status'] in ['running', 'pausing'] for task in tasks), 1, tasks)
                    if all(task['status'] == 'answered' for task in tasks):
                        break
                    time.sleep(0.02)
                else:
                    self.fail(str(tasks))
                self.assertEqual([task['id'] for task in tasks], [first['id'], second['id'], third['id']])
                self.assertEqual([task['toolExecutions'][0]['result']['characters'] for task in tasks], [3, 4, 5])
                times = [task['startedAt'] for task in tasks]
                self.assertEqual(times, sorted(times))
                self.assertTrue(all(task['finishedAt'] <= tasks[index + 1]['startedAt'] for index, task in enumerate(tasks[:-1])))
                self.assertEqual(len({task['toolExecutions'][0]['artifact']['path'] for task in tasks}), 3)

    def test_two_projects_overlap_without_crossing_inputs_or_task_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                contexts = []
                for index in range(2):
                    path = root / str(index)
                    path.mkdir()
                    project = client.post('/api/workbench/projects', json={'path': str(path)}).json()
                    url = f'/api/workbench/projects/{project["id"]}'
                    chat = client.post(url + '/conversations', json={'title': str(index)}).json()['id']
                    contexts.append((path, url, chat))
                with ThreadPoolExecutor(max_workers=2) as pool:
                    responses = list(pool.map(lambda item: client.post(item[1] + '/tasks', json={'conversationId': item[2], 'requestId': 'same-client-id', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}), contexts))
                self.assertTrue(all(response.status_code == 201 for response in responses))
                deadline = time.monotonic() + 8
                overlap = False
                while time.monotonic() < deadline:
                    states = [client.get(url + f'/conversations/{chat}').json() for _, url, chat in contexts]
                    if all(state['tasks'][0]['status'] == 'running' and state['tasks'][0]['toolExecutions'] for state in states):
                        overlap = True
                        break
                    time.sleep(0.01)
                self.assertTrue(overlap, states)
                done = [wait_task(client, url, chat, response.json()['id']) for (_, url, chat), response in zip(contexts, responses)]
                self.assertNotEqual(done[0]['id'], done[1]['id'])
                for (path, _, _), task in zip(contexts, done):
                    artifact = task['toolExecutions'][0]['artifact']
                    self.assertTrue((path / artifact['path']).is_file())
                    self.assertEqual(task['toolExecutions'][0]['result'], {'characters': 3})

    def test_wait_pause_and_restart_do_not_block_or_auto_resume_others(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'slot release'}).json()['id']
                waiting = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'waiting', 'goal': 'one', 'authorizedTools': []}).json()
                first = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                second = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'queued', 'goal': 'ABCDE', 'authorizedTools': ['synthetic_count']}).json()
                answer = client.post(url + f'/tasks/{waiting["id"]}/decisions/{waiting["decisions"][0]["id"]}', json={'answer': 'grant'})
                self.assertEqual(answer.status_code, 200, answer.text)
                continued = client.post(url + f'/tasks/{waiting["id"]}/continue')
                self.assertEqual(continued.json()['status'], 'queued')
                paused = client.post(url + f'/tasks/{first["id"]}/pause')
                self.assertEqual(paused.status_code, 200, paused.text)
                self.assertEqual(paused.json()['status'], 'paused')
                next_done = wait_task(client, url, chat, second['id'])
                final_done = wait_task(client, url, chat, waiting['id'])
                self.assertLessEqual(next_done['finishedAt'], final_done['startedAt'])
                saved = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(saved['tasks'][1]['status'], 'paused')
                self.assertEqual(client.post(url + f'/tasks/{first["id"]}/resume').status_code, 200)
                third = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'after-resume', 'goal': 'queued at exit', 'authorizedTools': ['synthetic_count']}).json()
                self.assertEqual(third['status'], 'queued')
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                selected = {task['id']: task for task in reopened['tasks']}
                self.assertEqual(selected[third['id']]['status'], 'paused')
                before = reopened['modelRequests']
                time.sleep(0.1)
                self.assertEqual(client.get(url).json()['modelRequests'], before)
                self.assertEqual(client.post(url + f'/tasks/{third["id"]}/resume').status_code, 200)
                done = wait_task(client, url, chat, third['id'])
                self.assertEqual(done['toolExecutions'][0]['result'], {'characters': 14})
                others = client.get(url + f'/conversations/{chat}').json()['tasks']
                self.assertNotEqual(next(task for task in others if task['id'] == first['id'])['status'], 'running')

    def test_failed_queued_precondition_does_not_block_following_valid_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'queue validation'}).json()['id']
                imported = client.post(url + '/files', json={'name': 'one.fa', 'contentBase64': base64.b64encode(b'>one\nMK*\n').decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                first = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'first', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                invalid = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'changed-input', 'goal': 'D2P 本地专项', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'preserve', 'avoid': ''}, 'authorizedTools': ['d2p_local']}).json()
                self.assertEqual(invalid['status'], 'queued')
                (root / fixed['inputs'][0]['path']).write_text('tampered')
                valid = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'following', 'goal': 'ABCD', 'authorizedTools': ['synthetic_count']}).json()
                done = wait_task(client, url, chat, valid['id'])
                self.assertEqual(done['toolExecutions'][0]['result'], {'characters': 4})
                tasks = client.get(url + f'/conversations/{chat}').json()['tasks']
                self.assertEqual(next(task for task in tasks if task['id'] == invalid['id'])['status'], 'paused')
                self.assertEqual(next(task for task in tasks if task['id'] == invalid['id'])['toolExecutions'], [])
                self.assertEqual(next(task for task in tasks if task['id'] == first['id'])['status'], 'answered')

    def test_project_host_capacity_is_explicit_and_does_not_create_unowned_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                for index in range(4):
                    path = root / str(index)
                    path.mkdir()
                    response = client.post('/api/workbench/projects', json={'path': str(path)})
                    self.assertEqual(response.status_code, 201, response.text)
                extra = root / 'fifth'
                extra.mkdir()
                response = client.post('/api/workbench/projects', json={'path': str(extra)})
                self.assertEqual(response.status_code, 409, response.text)
                self.assertIn('4', response.json()['detail'])
                self.assertFalse((extra / '.silicolab').exists())

    def test_resumed_artifact_is_rechecked_at_queue_admission_and_bad_item_does_not_stall_next(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'admission recheck'}).json()['id']
                first = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'paused-A', 'goal': 'AAA', 'authorizedTools': ['synthetic_count']}).json()
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    state = client.get(url + f'/conversations/{chat}').json()
                    if state['tasks'][0]['toolExecutions'] and state['tasks'][0]['toolExecutions'][0]['status'] == 'completed':
                        break
                    time.sleep(0.01)
                completed = state['tasks'][0]['toolExecutions'][0]
                self.assertEqual(client.post(url + f'/tasks/{first["id"]}/pause').json()['status'], 'paused')
                second = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active-B', 'goal': 'BBBB', 'authorizedTools': ['synthetic_count']}).json()
                resumed = client.post(url + f'/tasks/{first["id"]}/resume')
                self.assertEqual(resumed.status_code, 200, resumed.text)
                self.assertEqual(resumed.json()['status'], 'queued')
                (root / completed['artifact']['path']).write_text('tampered after enqueue')
                third = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'following-C', 'goal': 'CCCCC', 'authorizedTools': ['synthetic_count']}).json()
                done = wait_task(client, url, chat, third['id'])
                self.assertEqual(done['toolExecutions'][0]['result'], {'characters': 5})
                saved = client.get(url + f'/conversations/{chat}').json()['tasks']
                rejected = next(task for task in saved if task['id'] == first['id'])
                self.assertEqual(rejected['status'], 'paused', rejected)
                self.assertIn('产物', rejected['pauseReason'])
                self.assertEqual(rejected['toolExecutions'], [completed])
                self.assertEqual(next(task for task in saved if task['id'] == second['id'])['status'], 'answered')

    def test_history_over_cache_capacity_can_overlap_admission_and_pause_actual_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'history/cache stress'}).json()['id']
                first = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'old-paused', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    state = client.get(url + f'/conversations/{chat}').json()
                    if state['tasks'][0]['toolExecutions'] and state['tasks'][0]['toolExecutions'][0]['status'] == 'completed':
                        break
                    time.sleep(0.01)
                self.assertEqual(client.post(url + f'/tasks/{first["id"]}/pause').json()['status'], 'paused')
                warmup = [client.post(url + '/tasks', json={'conversationId': chat, 'requestId': f'history-{index}', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json() for index in range(9)]
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    state = client.get(url + f'/conversations/{chat}').json()
                    if next(task for task in state['tasks'] if task['id'] == warmup[-1]['id'])['status'] == 'answered':
                        break
                    time.sleep(0.03)
                else:
                    self.fail(str(state))
                active = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'new-active', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                self.assertEqual(client.post(url + f'/tasks/{first["id"]}/resume').json()['status'], 'queued')
                def read_history(_):
                    response = client.get(url + f'/conversations/{chat}')
                    self.assertEqual(response.status_code, 200, response.text)
                    return response.json()
                with ThreadPoolExecutor(max_workers=3) as pool:
                    for _ in range(30):
                        states = list(pool.map(read_history, range(3)))
                        selected = next(task for task in states[-1]['tasks'] if task['id'] == first['id'])
                        if selected['status'] == 'running':
                            break
                    else:
                        self.fail(str(states[-1]))
                    paused = client.post(url + f'/tasks/{first["id"]}/pause')
                    self.assertEqual(paused.status_code, 200, paused.text)
                    self.assertEqual(paused.json()['status'], 'paused')
                    completed = paused.json()['toolExecutions']
                    states = list(pool.map(read_history, range(3)))
                before = states[-1]['modelRequests']
                time.sleep(0.8)
                final = client.get(url + f'/conversations/{chat}').json()
                selected = next(task for task in final['tasks'] if task['id'] == first['id'])
                self.assertEqual(selected['status'], 'paused')
                self.assertEqual(selected['toolExecutions'], completed)
                self.assertEqual(final['modelRequests'], before)
                self.assertEqual(next(task for task in final['tasks'] if task['id'] == active['id'])['status'], 'answered')
                self.assertTrue(all(len(task['toolExecutions']) == 1 for task in final['tasks']))


if __name__ == '__main__':
    unittest.main()
