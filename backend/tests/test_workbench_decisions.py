"""Durable, task-scoped decisions do not run work until the user answers."""
import base64
import os
import signal
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from app_fixture import create_app
from test_workbench_science import wait_task


class TaskDecisionTests(unittest.TestCase):
    def test_stop_question_survives_reopen_and_duplicate_answer_does_not_repeat_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'stop decision'}).json()['id']
                original = b'>without-stop\nMK\n'
                imported = client.post(url + '/files', json={'name': 'no-stop.fasta', 'contentBase64': base64.b64encode(original).decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                body = {'conversationId': chat, 'requestId': 'ask-stop-1', 'goal': '明确 D2P 专项本地实验，缺少终止符时等我决定', 'authorizedTools': ['d2p_local'], 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'ask', 'avoid': ''}}
                response = client.post(url + '/tasks', json=body)
                self.assertEqual(response.status_code, 201, response.text)
                task = response.json()
                self.assertEqual(task['status'], 'needs_decision')
                self.assertEqual(len(task['decisions']), 1)
                question = task['decisions'][0]
                self.assertEqual(question['kind'], 'terminal_stop')
                self.assertEqual([option['value'] for option in question['options']], ['preserve', 'add'])
                self.assertEqual(client.post(url + '/tasks', json=body).json()['id'], task['id'])
                time.sleep(0.1)
                saved = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(saved['modelRequests'], 0)
                self.assertEqual(saved['tasks'][0]['toolExecutions'], [])
                self.assertEqual(saved['tasks'][0]['decisions'], [question])
                (root / imported['path']).write_text('PROJECT_SOURCE_EDITED_AFTER_FIXED_INPUT')
                # Actual process death while waiting must not lose or duplicate the question.
                runtime_pid = client.get(url).json()['runtimePid']
                os.kill(runtime_pid, signal.SIGKILL)
                time.sleep(0.05)
                same_process_reopen = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                self.assertNotEqual(same_process_reopen['runtimePid'], runtime_pid)
                self.assertEqual(same_process_reopen['scheduling'], 'paused')
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['tasks'][0]['decisions'], [question])
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                saved = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(saved['modelRequests'], 0)
                self.assertEqual(saved['tasks'][0]['decisions'], [question])
                self.assertEqual(reopened['scheduling'], 'paused')
                answer_url = url + f'/tasks/{task["id"]}/decisions/{question["id"]}'
                invalid = client.post(answer_url, json={'answer': 'guess'})
                self.assertEqual(invalid.status_code, 409, invalid.text)
                answer = client.post(answer_url, json={'answer': 'add'})
                self.assertEqual(answer.status_code, 200, answer.text)
                self.assertEqual(answer.json()['id'], task['id'])
                self.assertEqual(answer.json()['status'], 'admission_pending')
                self.assertEqual(client.post(answer_url, json={'answer': 'add'}).status_code, 200)
                # Kill exactly after the durable final answer and before explicit admission.
                runtime_pid = client.get(url).json()['runtimePid']
                os.kill(runtime_pid, signal.SIGKILL)
                time.sleep(0.05)
                client.post('/api/workbench/projects/open', json={'path': str(root)})
                preserved = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(preserved['modelRequests'], 0)
                self.assertEqual(preserved['tasks'][0]['status'], 'admission_pending')
                self.assertEqual(preserved['tasks'][0]['decisions'][0]['answer'], 'add')
                self.assertNotIn('submissionId', preserved['tasks'][0])
                self.assertEqual(client.post(answer_url, json={'answer': 'add'}).json()['status'], 'admission_pending')
                continued = client.post(url + f'/tasks/{task["id"]}/continue')
                self.assertEqual(continued.status_code, 200, continued.text)
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/continue').status_code, 200)
                finished = wait_task(client, url, chat, task['id'])
                self.assertEqual(len(finished['toolExecutions']), 1)
                result = finished['toolExecutions'][0]['result']
                self.assertEqual(result['records'][0]['protein'], 'MK*')
                self.assertEqual(result['records'][0]['original_protein'], 'MK')
                self.assertEqual(finished['decisions'][0]['answer'], 'add')
                self.assertEqual(finished['decisions'][0]['status'], 'answered')
                self.assertEqual(client.post(answer_url, json={'answer': 'add'}).json()['toolExecutions'], finished['toolExecutions'])
                self.assertEqual(client.post(answer_url, json={'answer': 'preserve'}).status_code, 409)
                self.assertEqual(client.post(url + '/tasks', json=body).json()['id'], task['id'])
                self.assertEqual((root / imported['path']).read_text(), 'PROJECT_SOURCE_EDITED_AFTER_FIXED_INPUT')
                old = client.get(url + '/input-versions/' + fixed['id']).json()
                self.assertEqual(base64.b64decode(old['inputs'][0]['contentBase64']), original)
                self.assertEqual(len(client.get(url).json()['inputVersions']), 1)

    def test_tool_grant_is_explicit_durable_and_denial_prevents_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'tool authority'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'grant', 'goal': 'ABC', 'authorizedTools': []}
                pending = client.post(url + '/tasks', json=body).json()
                question = pending['decisions'][0]
                self.assertEqual(question['kind'], 'tool_authorization')
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], 0)
                answer_url = url + f'/tasks/{pending["id"]}/decisions/{question["id"]}'
                self.assertEqual(client.post(answer_url, json={'answer': 'grant'}).status_code, 200)
                self.assertEqual(client.post(url + f'/tasks/{pending["id"]}/continue').status_code, 200)
                finished = wait_task(client, url, chat, pending['id'])
                self.assertEqual(finished['toolExecutions'][0]['result'], {'characters': 3})
                self.assertEqual(finished['authorizedTools'], ['synthetic_count'])
                before = client.get(url + f'/conversations/{chat}').json()['modelRequests']
                rejected = client.post(url + '/tasks', json={**body, 'requestId': 'deny'}).json()
                question = rejected['decisions'][0]
                answer_url = url + f'/tasks/{rejected["id"]}/decisions/{question["id"]}'
                denied = client.post(answer_url, json={'answer': 'decline'})
                self.assertEqual(denied.json()['status'], 'cancelled')
                self.assertEqual(denied.json()['toolExecutions'], [])
                self.assertEqual(client.post(answer_url, json={'answer': 'decline'}).status_code, 200)
                self.assertEqual(client.post(answer_url, json={'answer': 'grant'}).status_code, 409)
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], before)
                self.assertEqual(client.post(url + '/tasks', json={**body, 'requestId': 'unknown', 'authorizedTools': ['arbitrary_shell']}).status_code, 409)

    def test_two_decisions_are_answered_once_and_do_not_recreate_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'two decisions'}).json()['id']
                imported = client.post(url + '/files', json={'name': 'short.fa', 'contentBase64': base64.b64encode(b'>one\nMK\n').decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                body = {'conversationId': chat, 'requestId': 'two-decisions', 'goal': '明确本地 D2P 专项', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'ask', 'avoid': ''}, 'authorizedTools': []}
                task = client.post(url + '/tasks', json=body).json()
                self.assertEqual([item['kind'] for item in task['decisions']], ['terminal_stop', 'tool_authorization'])
                first, second = task['decisions']
                base = url + f'/tasks/{task["id"]}/decisions/'
                one = client.post(base + first['id'], json={'answer': 'preserve'}).json()
                self.assertEqual(one['status'], 'needs_decision')
                self.assertEqual(one['preflight'], task['preflight'])
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], 0)
                two = client.post(base + second['id'], json={'answer': 'grant'})
                self.assertEqual(two.status_code, 200, two.text)
                self.assertEqual(two.json()['status'], 'admission_pending')
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/continue').status_code, 200)
                done = wait_task(client, url, chat, task['id'])
                self.assertEqual(len(done['toolExecutions']), 1)
                self.assertEqual(done['preflight'], task['preflight'])
                self.assertEqual(len(done['decisions']), 2)
                self.assertTrue(all(item['status'] == 'answered' for item in done['decisions']))
                self.assertEqual(done['toolExecutions'][0]['result']['records'][0]['protein'], 'MK')
                self.assertEqual(client.post(url + '/tasks', json=body).json()['id'], task['id'])
                self.assertEqual(client.post(base + second['id'], json={'answer': 'grant'}).json()['toolExecutions'], done['toolExecutions'])

    def test_continuing_older_answered_task_uses_its_own_fixed_input_and_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'separate admissions'}).json()['id']
                pending = []
                for index, protein in enumerate(['MK', 'MEF']):
                    data = f'>input-{index}\n{protein}\n'.encode()
                    imported = client.post(url + '/files', json={'name': f'input-{index}.fa', 'contentBase64': base64.b64encode(data).decode()}).json()
                    fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                    body = {'conversationId': chat, 'requestId': f'pending-{index}', 'goal': '明确本地 D2P 专项', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'ask', 'avoid': ''}, 'authorizedTools': ['d2p_local']}
                    task = client.post(url + '/tasks', json=body).json()
                    answered = client.post(url + f'/tasks/{task["id"]}/decisions/{task["decisions"][0]["id"]}', json={'answer': 'add'})
                    self.assertEqual(answered.json()['status'], 'admission_pending')
                    pending.append((task, fixed))
                first, first_input = pending[0]
                second, second_input = pending[1]
                response = client.post(url + f'/tasks/{first["id"]}/continue')
                self.assertEqual(response.status_code, 200, response.text)
                done = wait_task(client, url, chat, first['id'])
                self.assertEqual(len(done['toolExecutions']), 1, done)
                execution = done['toolExecutions'][0]
                self.assertEqual(execution['result']['inputVersionId'], first_input['id'])
                self.assertEqual(execution['result']['records'][0]['protein'], 'MK*')
                self.assertTrue(all(first['id'] in artifact['path'] for artifact in execution['artifacts']))
                other = next(task for task in client.get(url + f'/conversations/{chat}').json()['tasks'] if task['id'] == second['id'])
                self.assertEqual(other['status'], 'admission_pending')
                self.assertEqual(other['toolExecutions'], [])
                self.assertEqual(other['inputVersionId'], second_input['id'])
                self.assertEqual(client.post(url + f'/tasks/{second["id"]}/continue').status_code, 200)
                second_done = wait_task(client, url, chat, second['id'])
                self.assertEqual(second_done['toolExecutions'][0]['result']['records'][0]['protein'], 'MEF*')
                self.assertEqual(len(second_done['toolExecutions']), 1)


if __name__ == '__main__':
    unittest.main()
