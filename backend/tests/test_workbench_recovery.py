"""Actual pause/kill/reopen and selected task recovery through public operations."""
import base64
import hashlib
import os
from pathlib import Path
import signal
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from silicolab.server import create_app
from test_workbench_science import wait_task


def wait_state(client, url, predicate):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        state = client.get(url).json()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise AssertionError(state)


class TaskRecoveryTests(unittest.TestCase):
    def test_pause_stops_model_then_resume_same_task_without_reexecuting_completed_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'pause before final answer'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'resume-complete', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}
                task = client.post(url + '/tasks', json=body).json()
                state = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['toolExecutions'] and s['tasks'][0]['toolExecutions'][0]['status'] == 'completed' and s['tasks'][0]['status'] == 'running')
                completed = state['tasks'][0]['toolExecutions'][0]
                artifact = root / completed['artifact']['path']
                before = hashlib.sha256(artifact.read_bytes()).hexdigest()
                paused = client.post(url + f'/tasks/{task["id"]}/pause')
                self.assertEqual(paused.status_code, 200, paused.text)
                self.assertEqual(paused.json()['status'], 'paused')
                count = client.get(url + f'/conversations/{chat}').json()['modelRequests']
                time.sleep(0.15)
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], count)
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/pause').json()['status'], 'paused')
                resumed = client.post(url + f'/tasks/{task["id"]}/resume')
                self.assertEqual(resumed.status_code, 200, resumed.text)
                self.assertEqual(resumed.json()['id'], task['id'])
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/resume').status_code, 200)
                done = wait_task(client, url, chat, task['id'])
                self.assertEqual(done['toolExecutions'], [completed])
                self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), before)
                self.assertEqual(client.post(url + '/tasks', json=body).json()['id'], task['id'])

    def test_pause_stops_actual_python_reopens_passively_then_redoes_only_unfinished_step(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'pause python'}).json()['id']
                source = b'>long\nM' + b'K' * 1500 + b'*\n'
                imported = client.post(url + '/files', json={'name': 'long.fa', 'contentBase64': base64.b64encode(source).decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                body = {'conversationId': chat, 'requestId': 'pause-science', 'goal': 'D2P 专项本地实验', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'preserve', 'avoid': 'AAG'}, 'authorizedTools': ['d2p_local']}
                task = client.post(url + '/tasks', json=body).json()
                state = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['toolExecutions'] and s['tasks'][0]['toolExecutions'][0].get('pythonPid'))
                pid = state['tasks'][0]['toolExecutions'][0]['pythonPid']
                response = client.post(url + f'/tasks/{task["id"]}/pause')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], 'paused')
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                prior = response.json()['toolExecutions']
                self.assertEqual(prior[0]['status'], 'paused')
                calls = client.get(url + f'/conversations/{chat}').json()['modelRequests']
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                self.assertEqual(project['tasks'][0]['status'], 'paused')
                self.assertEqual(project['modelRequests'], calls)
                self.assertEqual(project['tasks'][0]['toolExecutions'], prior)
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/resume').status_code, 200)
                done = wait_task(client, url, chat, task['id'])
                self.assertEqual(len(done['toolExecutions']), 2)
                self.assertEqual(done['toolExecutions'][0], prior[0])
                self.assertEqual(done['toolExecutions'][1]['status'], 'completed')
                self.assertEqual(done['inputVersionId'], fixed['id'])
                self.assertEqual(done['toolExecutions'][1]['result']['records'][0]['protein'], 'M' + 'K' * 1500 + '*')

    def test_killed_host_reaps_science_process_and_requires_selected_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'kill python owner'}).json()['id']
                source = b'>long\nM' + b'K' * 1500 + b'*\n'
                imported = client.post(url + '/files', json={'name': 'long.fa', 'contentBase64': base64.b64encode(source).decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'kill-science', 'goal': 'D2P 专项本地实验', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'preserve', 'avoid': 'AAG'}, 'authorizedTools': ['d2p_local']}).json()
                state = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['toolExecutions'] and s['tasks'][0]['toolExecutions'][0].get('pythonPid'))
                pid = state['tasks'][0]['toolExecutions'][0]['pythonPid']
                runtime = client.get(url).json()['runtimePid']
                os.kill(runtime, signal.SIGKILL)
                # The still-live application supervisor owns/reaps Python when its pipe loses the Node owner.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.02)
                else:
                    self.fail('scientific child survived its Node host')
                reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                self.assertEqual(reopened['tasks'][0]['status'], 'paused')
                calls = reopened['modelRequests']
                time.sleep(0.1)
                self.assertEqual(client.get(url).json()['modelRequests'], calls)
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/resume').status_code, 200)
                done = wait_task(client, url, chat, task['id'])
                self.assertEqual(done['id'], task['id'])
                self.assertEqual(done['toolExecutions'][-1]['status'], 'completed')
                self.assertEqual(client.get('/api/jobs').json(), [])

    def test_changed_completed_artifact_blocks_resume_without_reexecuting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'verify before resume'}).json()['id']
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'tamper', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                state = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['toolExecutions'] and s['tasks'][0]['toolExecutions'][0]['status'] == 'completed' and s['tasks'][0]['status'] == 'running')
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/pause').status_code, 200)
                artifact = state['tasks'][0]['toolExecutions'][0]['artifact']
                (root / artifact['path']).write_text('tampered')
                before = client.get(url + f'/conversations/{chat}').json()
                denied = client.post(url + f'/tasks/{task["id"]}/resume')
                self.assertEqual(denied.status_code, 409, denied.text)
                after = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(after['modelRequests'], before['modelRequests'])
                self.assertEqual(after['tasks'][0]['status'], 'paused')
                self.assertEqual(after['tasks'][0]['toolExecutions'], before['tasks'][0]['toolExecutions'])

    def test_normal_app_close_reaps_python_and_reopen_only_lists_recoverable_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'normal close'}).json()['id']
                data = b'>long\nM' + b'K' * 1500 + b'*\n'
                imported = client.post(url + '/files', json={'name': 'long.fa', 'contentBase64': base64.b64encode(data).decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'normal-close', 'goal': 'D2P 专项本地实验', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'preserve', 'avoid': 'AAG'}, 'authorizedTools': ['d2p_local']}).json()
                state = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['toolExecutions'] and s['tasks'][0]['toolExecutions'][0].get('pythonPid'))
                pid = state['tasks'][0]['toolExecutions'][0]['pythonPid']
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                self.assertEqual(reopened['tasks'][0]['status'], 'paused')
                calls = reopened['modelRequests']
                time.sleep(0.1)
                self.assertEqual(client.get(url).json()['modelRequests'], calls)
                resumed = client.post(url + f'/tasks/{task["id"]}/resume')
                self.assertEqual(resumed.status_code, 200, resumed.text)
                done = wait_task(client, url, chat, task['id'])
                self.assertEqual(done['toolExecutions'][-1]['status'], 'completed')

    def test_repeated_crashes_hit_restart_limit_and_resume_stays_paused_with_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'bounded crash recovery'}).json()['id']
                data = b'>long\nM' + b'K' * 8000 + b'*\n'
                imported = client.post(url + '/files', json={'name': 'long.fa', 'contentBase64': base64.b64encode(data).decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'restart-limit', 'goal': 'D2P 专项本地实验', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'preserve', 'avoid': 'AAG'}, 'authorizedTools': ['d2p_local']}).json()
                for attempt in range(3):
                    state = wait_state(client, url + f'/conversations/{chat}', lambda s: len(s['tasks'][0]['toolExecutions']) == attempt + 1 and s['tasks'][0]['toolExecutions'][-1].get('pythonPid'))
                    runtime = client.get(url).json()['runtimePid']
                    os.kill(runtime, signal.SIGKILL)
                    time.sleep(0.05)
                    reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                    self.assertEqual(reopened['tasks'][0]['status'], 'paused')
                    if attempt < 2:
                        response = client.post(url + f'/tasks/{task["id"]}/resume')
                        self.assertEqual(response.status_code, 200, response.text)
                before = client.get(url + f'/conversations/{chat}').json()
                denied = client.post(url + f'/tasks/{task["id"]}/resume')
                self.assertEqual(denied.status_code, 409, denied.text)
                after = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(after['tasks'][0]['status'], 'paused')
                self.assertIn('restart_limit', after['tasks'][0]['pauseReason'])
                self.assertEqual(after['modelRequests'], before['modelRequests'])
                self.assertEqual(after['tasks'][0]['toolExecutions'], before['tasks'][0]['toolExecutions'])
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/resume').status_code, 409)


if __name__ == '__main__':
    unittest.main()
