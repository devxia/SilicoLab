"""External-effect identity, independent lifetime and explicit reconciliation using a fake service."""
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app_fixture import create_app
from test_workbench_science import wait_task


class SimulatedExternalTests(unittest.TestCase):
    def test_waiting_job_releases_slot_result_returns_via_queue_and_cancels_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'external waits'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'external-one', 'goal': '提交人工模拟外部作业', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 2500, 'queryable': True, 'responseMode': 'normal'}}
                response = client.post(url + '/tasks', json=body)
                self.assertEqual(response.status_code, 201, response.text)
                task = response.json()
                self.assertEqual(task['status'], 'waiting_external')
                self.assertTrue(task['externalJob']['jobId'])
                active = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'local', 'goal': 'ABCDE', 'authorizedTools': ['synthetic_count']}).json()
                self.assertEqual(active['status'], 'running')
                wait_task(client, url, chat, active['id'])
                count = client.get(url + f'/conversations/{chat}').json()['modelRequests']
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/pause').json()['status'], 'paused')
                service = client.get('/api/workbench/simulated-executor').json()
                self.assertEqual(service['createdJobs'], 1)
                self.assertEqual(service['jobs'][0]['state'], 'running')
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                external = next(item for item in project['tasks'] if item['id'] == task['id'])
                self.assertEqual(external['status'], 'paused')
                time.sleep(0.4)
                receipt = client.post(url + f'/tasks/{task["id"]}/external/reconcile')
                self.assertEqual(receipt.status_code, 200, receipt.text)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    saved = client.get(url + f'/conversations/{chat}').json()
                    current = next(item for item in saved['tasks'] if item['id'] == task['id'])
                    if current['status'] == 'answered':
                        break
                    time.sleep(0.05)
                    client.post(url + f'/tasks/{task["id"]}/external/reconcile')
                else:
                    self.fail(str(current))
                self.assertEqual(current['externalJob']['jobId'], task['externalJob']['jobId'])
                result = current['toolExecutions'][0]['result']
                self.assertEqual(result['characters'], 3)
                self.assertEqual(result['jobId'], task['externalJob']['jobId'])
                self.assertEqual(saved['modelRequests'], count)
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][0]['submit_attempts'], 1)
                download = client.get(url + f'/tasks/{task["id"]}/artifacts/{current["toolExecutions"][0]["id"]}/simulated-result.json')
                self.assertEqual(download.status_code, 200, download.text)
                self.assertEqual(json.loads(download.content)['payload'], 'ABC')
                pending = client.post(url + '/tasks', json={**body, 'requestId': 'external-cancel', 'simulation': {**body['simulation'], 'durationMs': 60000}}).json()
                stopped = client.post(url + f'/tasks/{pending["id"]}/cancel')
                self.assertEqual(stopped.json()['status'], 'cancelled')
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][1]['state'], 'running')
                cancelled = client.post(url + f'/tasks/{pending["id"]}/external/cancel')
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                self.assertEqual(cancelled.json()['externalJob']['state'], 'cancelled')
                self.assertEqual(client.post(url + f'/tasks/{pending["id"]}/external/cancel').json()['externalJob']['state'], 'cancelled')

    def test_kill_after_service_acceptance_before_receipt_reconciles_without_resubmit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'lost receipt'}).json()['id']
                errors = []
                def submit():
                    try:
                        client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'accepted-before-id', 'goal': '模拟接受但回执未保存', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 10000, 'queryable': True, 'responseMode': 'hold_after_accept'}})
                    except Exception as error:
                        errors.append(str(error))
                thread = threading.Thread(target=submit)
                thread.start()
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    service = client.get('/api/workbench/simulated-executor').json()
                    if service['createdJobs'] == 1:
                        break
                    time.sleep(0.02)
                else:
                    self.fail(str(service))
                os.kill(project['runtimePid'], signal.SIGKILL)
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
                reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                pending = reopened['tasks'][0]
                self.assertEqual(pending['status'], 'result_unknown')
                self.assertEqual(pending['externalJob']['state'], 'unknown')
                self.assertIn('对账', pending['externalJob']['error'])
                self.assertNotIn('jobId', pending['externalJob'])
                self.assertEqual(pending['externalJob']['requestKey'], service['jobs'][0]['request_key'])
                receipt = client.post(url + f'/tasks/{pending["id"]}/external/reconcile')
                self.assertEqual(receipt.status_code, 200, receipt.text)
                self.assertEqual(receipt.json()['externalJob']['jobId'], service['jobs'][0]['id'])
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][0]['submit_attempts'], 1)

    def test_unsupported_query_preserves_unknown_and_requires_explicit_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'unknown needs decision'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'unknown', 'goal': '模拟无查询能力回执丢失', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 10000, 'queryable': False, 'responseMode': 'lost'}}
                response = client.post(url + '/tasks', json=body)
                self.assertEqual(response.status_code, 201, response.text)
                task = response.json()
                self.assertEqual(task['status'], 'result_unknown')
                checked = client.post(url + f'/tasks/{task["id"]}/external/reconcile').json()
                self.assertEqual(checked['status'], 'needs_decision')
                question = checked['decisions'][0]
                self.assertEqual(question['kind'], 'external_retry')
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/external/reconcile').json()['decisions'], checked['decisions'])
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][0]['submit_attempts'], 1)
                answer_url = url + f'/tasks/{task["id"]}/decisions/{question["id"]}'
                answered = client.post(answer_url, json={'answer': 'retry_same_identity'})
                self.assertEqual(answered.status_code, 200, answered.text)
                retried = client.post(url + f'/tasks/{task["id"]}/continue')
                self.assertEqual(retried.status_code, 200, retried.text)
                self.assertEqual(retried.json()['status'], 'waiting_external')
                self.assertEqual(client.post(answer_url, json={'answer': 'retry_same_identity'}).status_code, 200)
                self.assertEqual(client.post(url + f'/tasks/{task["id"]}/continue').status_code, 200)
                final = client.get('/api/workbench/simulated-executor').json()
                self.assertEqual(final['createdJobs'], 1)
                self.assertEqual(final['jobs'][0]['submit_attempts'], 2)
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], 0)

    def test_external_result_rejoins_fifo_and_keep_unknown_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'reconcile queue'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'ready-external', 'goal': '模拟结果返回项目队列', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 0, 'queryable': True, 'responseMode': 'normal'}}
                external = client.post(url + '/tasks', json=body).json()
                active = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active-local', 'goal': 'ABCDE', 'authorizedTools': ['synthetic_count']}).json()
                queued = client.post(url + f'/tasks/{external["id"]}/external/reconcile')
                self.assertEqual(queued.status_code, 200, queued.text)
                self.assertEqual(queued.json()['status'], 'queued')
                self.assertEqual(queued.json()['toolExecutions'], [])
                self.assertEqual(client.post(url + f'/tasks/{external["id"]}/external/reconcile').json()['status'], 'queued')
                done_local = wait_task(client, url, chat, active['id'])
                done_external = wait_task(client, url, chat, external['id'])
                self.assertEqual(len(done_external['toolExecutions']), 1)
                self.assertGreaterEqual(done_external['finishedAt'], done_local['finishedAt'])
                unknown = client.post(url + '/tasks', json={**body, 'requestId': 'keep', 'simulation': {**body['simulation'], 'queryable': False, 'responseMode': 'lost'}}).json()
                checked = client.post(url + f'/tasks/{unknown["id"]}/external/reconcile').json()
                question = checked['decisions'][0]
                answer_url = url + f'/tasks/{unknown["id"]}/decisions/{question["id"]}'
                response = client.post(answer_url, json={'answer': 'keep_unknown'})
                self.assertEqual(response.json()['status'], 'result_unknown')
                self.assertEqual(client.post(answer_url, json={'answer': 'keep_unknown'}).status_code, 200)
                self.assertEqual(client.post(url + f'/tasks/{unknown["id"]}/external/reconcile').json()['status'], 'result_unknown')
                self.assertEqual(client.post(url + f'/tasks/{unknown["id"]}/continue').json()['status'], 'result_unknown')
                jobs = client.get('/api/workbench/simulated-executor').json()
                self.assertEqual(jobs['createdJobs'], 2)
                self.assertEqual(jobs['jobs'][1]['submit_attempts'], 1)

    def test_independent_cancel_before_queue_admission_does_not_submit_a_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'cancel unsent'}).json()['id']
                active = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                pending = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'not-sent', 'goal': '排队中的人工模拟请求', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 5000, 'queryable': True, 'responseMode': 'normal'}}).json()
                self.assertEqual(pending['status'], 'queued')
                self.assertEqual(pending['externalJob']['state'], 'not_submitted')
                cancelled = client.post(url + f'/tasks/{pending["id"]}/external/cancel')
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                self.assertEqual(cancelled.json()['status'], 'cancelled')
                self.assertEqual(cancelled.json()['externalJob']['state'], 'cancelled')
                wait_task(client, url, chat, active['id'])
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['createdJobs'], 0)
                self.assertEqual(client.post(url + f'/tasks/{pending["id"]}/continue').json()['status'], 'cancelled')

    def test_completed_job_cancellation_check_does_not_reopen_or_duplicate_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'late cancellation'}).json()['id']
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'instant', 'goal': '人工模拟瞬时完成', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 0, 'queryable': True, 'responseMode': 'normal'}}).json()
                client.post(url + f'/tasks/{task["id"]}/external/reconcile')
                completed = wait_task(client, url, chat, task['id'])
                self.assertEqual(completed['externalJob']['state'], 'succeeded')
                response = client.post(url + f'/tasks/{task["id"]}/external/cancel')
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], 'answered')
                self.assertEqual(response.json()['externalJob']['state'], 'succeeded')
                checked = client.post(url + f'/tasks/{task["id"]}/external/reconcile').json()
                self.assertEqual(checked['toolExecutions'], completed['toolExecutions'])
                self.assertEqual(checked['status'], 'answered')
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][0]['submit_attempts'], 1)

    def test_known_unsent_pause_or_restart_resumes_first_submission_without_unknown_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'known unsent'}).json()['id']
                active = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active-for-pause', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                body = {'conversationId': chat, 'requestId': 'unsent-pause', 'goal': '人工模拟队列任务', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 5000, 'queryable': True, 'responseMode': 'normal'}}
                pending = client.post(url + '/tasks', json=body).json()
                self.assertEqual(pending['status'], 'queued')
                self.assertEqual(client.post(url + f'/tasks/{pending["id"]}/pause').json()['status'], 'paused')
                resumed = client.post(url + f'/tasks/{pending["id"]}/resume')
                self.assertEqual(resumed.status_code, 200, resumed.text)
                self.assertEqual(resumed.json()['status'], 'queued')
                self.assertEqual(resumed.json()['decisions'], [])
                wait_task(client, url, chat, active['id'])
                first = resumed.json()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    first = next(item for item in client.get(url).json()['tasks'] if item['id'] == pending['id'])
                    if first['status'] == 'waiting_external':
                        break
                    time.sleep(0.03)
                self.assertEqual(first['status'], 'waiting_external', first)
                client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'active-at-close', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']})
                waiting = client.post(url + '/tasks', json={**body, 'requestId': 'unsent-restart'}).json()
                self.assertEqual(waiting['status'], 'queued')
            with TestClient(create_app(database, delay=0)) as client:
                reopened = client.post('/api/workbench/projects/open', json={'path': str(root)}).json()
                second = next(item for item in reopened['tasks'] if item['id'] == waiting['id'])
                self.assertEqual(second['status'], 'paused')
                self.assertEqual(second['externalJob']['state'], 'not_submitted')
                resumed = client.post(url + f'/tasks/{waiting["id"]}/resume')
                self.assertEqual(resumed.status_code, 200, resumed.text)
                self.assertEqual(resumed.json()['status'], 'waiting_external')
                self.assertEqual(resumed.json()['decisions'], [])
                jobs = client.get('/api/workbench/simulated-executor').json()
                self.assertEqual(jobs['createdJobs'], 2)
                self.assertTrue(all(item['submit_attempts'] == 1 for item in jobs['jobs']))
    def test_cancel_failure_persists_unknown_state_and_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'cancel unknown'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'cancel-failure', 'goal': '模拟外部作业', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 60000, 'queryable': True, 'responseMode': 'normal'}}
                task = client.post(url + '/tasks', json=body).json()
                # Fault injection at the external fake-service adapter; HTTP still traverses the real client.
                with patch('silicolab.simulated_executor.SimulatedExecutor.cancel', side_effect=OSError('artificial cancel service outage')):
                    cancelled = client.post(url + f'/tasks/{task["id"]}/external/cancel')
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                self.assertEqual(cancelled.json()['status'], 'result_unknown')
                self.assertEqual(cancelled.json()['externalJob']['state'], 'unknown')
                self.assertTrue(cancelled.json()['externalJob']['error'])
                reopened = client.get(url).json()
                self.assertEqual(reopened['tasks'][0]['externalJob']['state'], 'unknown')

    def test_local_cancelled_waiting_job_is_not_resurrected_by_later_reconcile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'cancelled external'}).json()['id']
                body = {'conversationId': chat, 'requestId': 'cancelled-wait', 'goal': '模拟等待作业', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 100, 'queryable': True, 'responseMode': 'normal'}}
                task = client.post(url + '/tasks', json=body).json()
                cancelled = client.post(url + f'/tasks/{task["id"]}/cancel')
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                self.assertEqual(cancelled.json()['status'], 'cancelled')
                time.sleep(0.2)
                reconciled = client.post(url + f'/tasks/{task["id"]}/external/reconcile')
                self.assertEqual(reconciled.status_code, 200, reconciled.text)
                saved = reconciled.json()
                self.assertEqual(saved['status'], 'cancelled')
                self.assertEqual(saved['toolExecutions'], [])
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][0]['state'], 'running')

    def test_lookup_outage_and_unsupported_lookup_persist_unknown_without_losing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'lookup unavailable'}).json()['id']
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'lookup-failure', 'goal': '人工模拟作业', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 60000, 'queryable': True, 'responseMode': 'normal'}}).json()
                original = task['externalJob']
                with patch('silicolab.simulated_executor.SimulatedExecutor.find', side_effect=OSError('artificial lookup outage')):
                    checked = client.post(url + f'/tasks/{task["id"]}/external/reconcile')
                self.assertEqual(checked.status_code, 200, checked.text)
                saved = checked.json()
                self.assertEqual(saved['status'], 'result_unknown')
                self.assertEqual(saved['externalJob']['state'], 'unknown')
                self.assertTrue(saved['externalJob']['error'])
                for key in ['jobId', 'requestKey', 'serviceId', 'payloadHash']:
                    self.assertEqual(saved['externalJob'][key], original[key])
                unavailable = {'known': False, 'reason': 'query_unsupported', 'serviceId': original['serviceId']}
                with patch('silicolab.simulated_executor.SimulatedExecutor.find', return_value=unavailable):
                    pending = client.post(url + f'/tasks/{task["id"]}/external/reconcile').json()
                self.assertEqual(pending['externalJob']['state'], 'unknown')
                self.assertEqual(pending['status'], 'needs_decision')
                with patch('silicolab.simulated_executor.SimulatedExecutor.cancel', return_value=unavailable):
                    cancelled = client.post(url + f'/tasks/{task["id"]}/external/cancel').json()
                self.assertEqual(cancelled['status'], 'result_unknown')
                self.assertEqual(cancelled['externalJob']['state'], 'unknown')
                self.assertEqual(cancelled['externalJob']['jobId'], original['jobId'])
                self.assertEqual(client.get('/api/workbench/simulated-executor').json()['jobs'][0]['submit_attempts'], 1)

    def test_external_cancel_uncertainty_preserves_local_terminal_state(self):
        for fault in ['exception', 'unknown']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with TestClient(create_app(root / 'app.sqlite3', delay=0)) as client:
                    project = client.post('/api/workbench/projects', json={'path': str(root)}).json()
                    url = f'/api/workbench/projects/{project["id"]}'
                    chat = client.post(url + '/conversations', json={'title': 'independent state axes'}).json()['id']
                    body = {'conversationId': chat, 'requestId': 'local-terminated', 'goal': '人工模拟任务', 'authorizedTools': ['simulated_external'], 'workflow': 'simulated_external', 'simulation': {'payload': 'ABC', 'durationMs': 100, 'queryable': True, 'responseMode': 'normal'}}
                    task = client.post(url + '/tasks', json=body).json()
                    self.assertEqual(client.post(url + f'/tasks/{task["id"]}/cancel').json()['status'], 'cancelled')
                    unavailable = {'known': False, 'reason': 'simulated_cancellation_unknown', 'serviceId': task['externalJob']['serviceId']}
                    adapter = patch('silicolab.simulated_executor.SimulatedExecutor.cancel', **({'side_effect': OSError('artificial cancellation outage')} if fault == 'exception' else {'return_value': unavailable}))
                    with adapter:
                        response = client.post(url + f'/tasks/{task["id"]}/external/cancel')
                    self.assertEqual(response.status_code, 200, response.text)
                    uncertain = response.json()
                    self.assertEqual(uncertain['status'], 'cancelled')
                    self.assertEqual(uncertain['externalJob']['state'], 'unknown')
                    self.assertTrue(uncertain['externalJob']['error'])
                    time.sleep(0.2)
                    reconciled = client.post(url + f'/tasks/{task["id"]}/external/reconcile').json()
                    self.assertEqual(reconciled['status'], 'cancelled')
                    self.assertEqual(reconciled['toolExecutions'], [])
                    self.assertEqual(client.post(url + f'/tasks/{task["id"]}/continue').json()['status'], 'cancelled')
                    self.assertEqual(client.get('/api/workbench/simulated-executor').json()['createdJobs'], 1)
                    self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], 0)


if __name__ == '__main__':
    unittest.main()
