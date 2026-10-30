"""Real durable loop with faux provider and harmless local tool, via workbench."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from silicolab.server import create_app


class AgentLoopTests(unittest.TestCase):
    def test_real_tool_task_history_and_reconnect_do_not_duplicate_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(project)}).json()['id']
                url = f'/api/workbench/projects/{identity}'
                chat = client.post(url + '/conversations', json={'title': 'tool loop'}).json()
                body = {'conversationId': chat['id'], 'requestId': 'stable-request-1', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}
                response = client.post(url + '/tasks', json=body)
                self.assertEqual(response.status_code, 201, response.text)
                task = response.json()
                self.assertEqual(client.post(url + '/tasks', json=body).json()['id'], task['id'])
                conflicting = client.post(url + '/tasks', json={**body, 'goal': 'different target'})
                self.assertEqual(conflicting.status_code, 409, conflicting.text)
                states = []
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    state = client.get(url + f'/conversations/{chat["id"]}').json()
                    states.append(state)
                    if any(item['status'] == 'answered' for item in state['tasks']):
                        break
                    time.sleep(0.03)
                else:
                    self.fail(str(states[-1]))
                self.assertTrue(any(item['tasks'][0]['toolExecutions'] for item in states))
                self.assertTrue(any(item.get('partial') for item in states))
                finished = states[-1]['tasks'][0]
                self.assertEqual(finished['id'], task['id'])
                self.assertTrue(finished['submissionId'])
                self.assertEqual(len(finished['toolExecutions']), 1)
                execution = finished['toolExecutions'][0]
                self.assertEqual(execution['tool'], 'synthetic_count')
                self.assertEqual(execution['status'], 'completed')
                self.assertEqual(execution['progress'], 100)
                self.assertEqual(execution['result'], {'characters': 3})
                content = (project / execution['artifact']['path']).read_bytes()
                self.assertEqual(json.loads(content)['result'], {'characters': 3})
                self.assertEqual(client.post(url + '/tasks', json=body).json()['id'], task['id'])
                replay = client.get(url + f'/conversations/{chat["id"]}').json()
                self.assertEqual(len(replay['tasks']), 1)
                self.assertEqual(replay['tasks'][0]['toolExecutions'], finished['toolExecutions'])
                self.assertTrue(any(entry['kind'] == 'pi.tool-result' for entry in replay['entries']))
                self.assertGreaterEqual(replay['modelRequests'], 2)
                self.assertEqual(client.get('/api/jobs').json(), [])
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(project)}).json()
                saved = client.get(url + f'/conversations/{chat["id"]}').json()
                self.assertEqual(saved['tasks'][0]['toolExecutions'], finished['toolExecutions'])
                self.assertEqual(saved['scheduling'], 'paused')
                self.assertEqual(saved['modelRequests'], replay['modelRequests'])
                self.assertEqual(reopened['id'], identity)

    def test_missing_authority_returns_needed_decision_without_running_model_or_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(root)}).json()['id']
                url = f'/api/workbench/projects/{identity}'
                chat = client.post(url + '/conversations', json={'title': 'no implicit authority'}).json()
                response = client.post(url + '/tasks', json={'conversationId': chat['id'], 'requestId': 'no-auth', 'goal': '请优化密码子并上传', 'authorizedTools': []})
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()['status'], 'needs_decision')
                state = client.get(url + f'/conversations/{chat["id"]}').json()
                self.assertEqual(state['modelRequests'], 0)
                self.assertEqual(state['tasks'][0]['toolExecutions'], [])
                self.assertEqual(state['entries'], [])

    def test_tool_artifact_failure_is_terminal_and_persisted_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            project.mkdir()
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                identity = client.post('/api/workbench/projects', json={'path': str(project)}).json()['id']
                url = f'/api/workbench/projects/{identity}'
                chat = client.post(url + '/conversations', json={'title': 'artifact failure'}).json()
                (project / '.silicolab/outputs').write_text('artificial output obstacle')
                response = client.post(url + '/tasks', json={'conversationId': chat['id'], 'requestId': 'write-failed', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']})
                self.assertEqual(response.status_code, 201, response.text)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    state = client.get(url + f'/conversations/{chat["id"]}').json()
                    if state['tasks'][0]['status'] == 'answered':
                        break
                    time.sleep(0.03)
                else:
                    self.fail(str(state))
                failed = state['tasks'][0]['toolExecutions'][0]
                self.assertEqual(failed['status'], 'failed', failed)
                self.assertTrue(failed['error'])
                self.assertLess(failed['progress'], 100)
                self.assertNotIn('artifact', failed)
                self.assertNotIn('result', failed)
                self.assertTrue(any(entry.get('model', [{}])[0].get('isError') for entry in state['entries'] if entry['kind'] == 'pi.tool-result'))
                self.assertEqual((project / '.silicolab/outputs').read_text(), 'artificial output obstacle')
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(project)}).json()
                state = client.get(url + f'/conversations/{chat["id"]}').json()
                self.assertEqual(state['tasks'][0]['toolExecutions'][0], failed)
                self.assertEqual(reopened['scheduling'], 'paused')


if __name__ == '__main__':
    unittest.main()
