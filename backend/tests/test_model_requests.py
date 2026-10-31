"""Request boundaries, required conversation history, real usage and bounded retries."""
import base64
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app_fixture import create_app
from test_model_configuration import FakeModelEndpoint, MemorySecrets
from test_workbench_recovery import wait_state
from test_workbench_science import wait_task


class ModelRequestTests(unittest.TestCase):
    def setup(self, client, root, endpoints):
        configs = [client.post('/api/workbench/model-configs', json={'name': protocol, 'protocol': protocol, 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': key}).json() for protocol, endpoint, key in endpoints]
        (root / 'project').mkdir()
        project = client.post('/api/workbench/projects', json={'path': str(root / 'project')}).json()
        url = f'/api/workbench/projects/{project["id"]}'
        chat = client.post(url + '/conversations', json={'title': 'requests'}).json()['id']
        client.put(url + f'/conversations/{chat}/model', json={'configurationId': configs[0]['id']})
        task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'request-boundary', 'goal': '人工ABC字符数', 'authorizedTools': ['synthetic_count']}).json()
        return url, chat, task['id'], configs

    def test_switch_during_inflight_request_waits_until_next_request_without_pausing_tool(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-a', 'hold') as first, FakeModelEndpoint('anthropic-messages', 'artificial-b') as second:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                url, chat, task_id, configs = self.setup(client, root, [('openai-responses', first, 'artificial-a'), ('anthropic-messages', second, 'artificial-b')])
                self.assertTrue(first.entered.wait(5))
                state = client.get(url + f'/conversations/{chat}').json()
                self.assertEqual(state['tasks'][0]['modelRequests'][0]['status'], 'running')
                self.assertEqual(client.put(url + f'/conversations/{chat}/model', json={'configurationId': configs[1]['id']}).status_code, 200)
                self.assertEqual(second.requests, [])
                first.release.set()
                done = wait_task(client, url, chat, task_id)
                self.assertEqual(len(done['toolExecutions']), 1)
                self.assertEqual(done['toolExecutions'][0]['result']['characters'], 3)
                self.assertEqual([r['configurationId'] for r in done['modelRequests']], [c['id'] for c in configs])
                self.assertEqual(len(first.requests), 1)
                self.assertEqual(len(second.requests), 1)
                self.assertIn('characters', json.dumps(second.requests[0]['body']))

    def test_transient_and_stream_errors_retry_only_model_not_completed_tool(self):
        for failure in ('rate_limit', 'server_error', 'disconnect', 'socket_drop'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-retry', ['normal', failure, 'normal']) as endpoint:
                root = Path(directory)
                with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                    url, chat, task_id, _ = self.setup(client, root, [('openai-responses', endpoint, 'artificial-retry')])
                    done = wait_task(client, url, chat, task_id)
                    self.assertEqual(len(done['toolExecutions']), 1)
                    self.assertEqual(len(endpoint.requests), 3)
                    traces = done['modelRequests']
                    self.assertEqual([r['status'] for r in traces], ['completed', 'error', 'completed'])
                    self.assertEqual([r['attempt'] for r in traces], [1, 1, 2])
                    self.assertIn('retryAt', traces[1])
                    self.assertEqual(traces[1]['parameters']['maxRetries'], 0)

    def test_switch_and_retry_keep_actual_completed_scientific_artifact(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-science-a', 'hold', tool_name='d2p_local') as first, FakeModelEndpoint('anthropic-messages', 'artificial-science-b', ['rate_limit', 'duplicate_once', 'normal'], tool_name='d2p_local') as second:
            root = Path(directory)
            (root / 'project').mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                configs = [client.post('/api/workbench/model-configs', json={'name': e.protocol, 'protocol': e.protocol, 'baseUrl': e.url, 'modelId': 'artificial-model', 'apiKey': e.key}).json() for e in (first, second)]
                project = client.post('/api/workbench/projects', json={'path': str(root / 'project')}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'science switch'}).json()['id']
                client.put(url + f'/conversations/{chat}/model', json={'configurationId': configs[0]['id']})
                source = client.post(url + '/files', json={'name': 'artificial.fa', 'contentBase64': base64.b64encode(b'>artificial\nMK*\n').decode()}).json()
                fixed = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [source['id']]}).json()
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'science-switch', 'goal': '明确D2P本地专项', 'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': fixed['id'], 'parameters': {'stopPolicy': 'preserve', 'avoid': ''}, 'authorizedTools': ['d2p_local']}).json()
                self.assertTrue(first.entered.wait(5))
                client.put(url + f'/conversations/{chat}/model', json={'configurationId': configs[1]['id']})
                first.release.set()
                done = wait_task(client, url, chat, task['id'])
                self.assertEqual(len(done['toolExecutions']), 1)
                execution = done['toolExecutions'][0]
                self.assertEqual(execution['result']['records'][0]['dna'], 'ATGAAGTAA')
                self.assertEqual(execution['result']['network_attempts'], 0)
                self.assertEqual([r['configurationId'] for r in done['modelRequests']], [configs[0]['id'], configs[1]['id'], configs[1]['id'], configs[1]['id']])
                self.assertEqual([r['status'] for r in done['modelRequests']], ['completed', 'error', 'completed', 'completed'])
                fasta = next(a for a in execution['artifacts'] if a['name'] == 'synthesis.fasta')
                self.assertEqual((root / 'project' / fasta['path']).read_text(), '>artificial\nATGAAGTAA\n')
                self.assertEqual(client.get('/api/jobs').json(), [])

    def test_continuous_failures_pause_and_explicit_resume_keeps_completed_tool(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-fail', ['normal', 'server_error', 'server_error', 'server_error', 'duplicate_once', 'normal']) as endpoint:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                url, chat, task_id, _ = self.setup(client, root, [('openai-responses', endpoint, 'artificial-fail')])
                paused = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['status'] in ('paused', 'failed'))['tasks'][0]
                self.assertEqual(paused['status'], 'paused')
                self.assertEqual(len(endpoint.requests), 4)
                self.assertEqual(len(paused['toolExecutions']), 1)
                original = paused['toolExecutions'][0]
                self.assertEqual([r['attempt'] for r in paused['modelRequests']], [1, 1, 2, 3])
                self.assertIn('模型', paused['pauseReason'])
                self.assertEqual(client.post(url + f'/tasks/{task_id}/resume').status_code, 200)
                done = wait_task(client, url, chat, task_id)
                self.assertEqual(done['toolExecutions'], [original])
                self.assertEqual(len(endpoint.requests), 6)

    def test_reopen_reconciles_done_recovery_submission_not_original_failed_submission(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-recovery-id', ['normal', 'server_error', 'server_error', 'server_error', 'normal']) as endpoint:
            root = Path(directory)
            database = root / 'app.sqlite3'
            secrets = MemorySecrets()
            with TestClient(create_app(database, delay=0, credential_store=secrets)) as client:
                url, chat, task_id, _ = self.setup(client, root, [('openai-responses', endpoint, 'artificial-recovery-id')])
                wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['status'] == 'paused')
                client.post(url + f'/tasks/{task_id}/resume')
                done = wait_task(client, url, chat, task_id)
                self.assertIn('recoveryRequestId', done)
            # Fault injection: kernel recovery is committed done; app-ledger settlement was lost.
            # Modify only the artificial ledger through the public durable document API, not the kernel result.
            script = """
import { defineDoc, Harness, createRegistry } from '@earendil-works/pi-durable';
import { createModels } from '@earendil-works/pi-ai/models';
import { openNodeSqliteStorage } from '@earendil-works/pi-durable/storage/sqlite/node';
import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
const Ledger = defineDoc({kind:'silicolab.tasks',version:1,scope:'session',initial:()=>({tasks:[],modelRequests:0}),checkpointWhen:()=>true});
const h=await Harness.open(await openNodeSqliteStorage(process.argv[1]),{registry:createRegistry(),models:createModels()},BACKGROUND_CONTEXT);
await h.commit(async tx=>{const t=(await tx.doc(Ledger)).tasks.find(t=>t.id===process.argv[2]);t.status='running';},BACKGROUND_CONTEXT);
await h.close(BACKGROUND_CONTEXT);
"""
            injected = subprocess.run(['node', '--input-type=module', '-e', script, str(root / 'project' / '.silicolab' / 'session.sqlite'), task_id], cwd=Path(__file__).resolve().parents[2] / 'runtime', capture_output=True, text=True)
            self.assertEqual(injected.returncode, 0, injected.stderr)
            with TestClient(create_app(database, delay=0, credential_store=secrets)) as client:
                opened = client.post('/api/workbench/projects/open', json={'path': str(root / 'project')}).json()
                self.assertEqual(opened['tasks'][0]['status'], 'answered')
                self.assertEqual(opened['tasks'][0]['toolExecutions'], done['toolExecutions'])
                self.assertEqual(len(endpoint.requests), 5)

    def test_different_full_parameters_with_same_display_prefix_are_not_reused(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-fingerprint', ['long_original', 'server_error', 'server_error', 'server_error', 'duplicate_changed', 'normal']) as endpoint:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                url, chat, task_id, _ = self.setup(client, root, [('openai-responses', endpoint, 'artificial-fingerprint')])
                paused = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['status'] == 'paused')['tasks'][0]
                first = paused['toolExecutions'][0]
                client.post(url + f'/tasks/{task_id}/resume')
                done = wait_task(client, url, chat, task_id)
                self.assertEqual(len(done['toolExecutions']), 2)
                second = done['toolExecutions'][1]
                self.assertEqual(first['input'], second['input'])
                self.assertNotEqual(first['inputFingerprint'], second['inputFingerprint'])
                self.assertEqual(json.loads((root / 'project' / first['artifact']['path']).read_text())['input'], 'P' * 160 + 'A')
                self.assertEqual(json.loads((root / 'project' / second['artifact']['path']).read_text())['input'], 'P' * 160 + 'B')

    def test_history_limit_before_first_http_pauses_with_reason_and_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-limit', 'large_reply') as endpoint:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                url, chat, first_id, _ = self.setup(client, root, [('openai-responses', endpoint, 'artificial-limit')])
                wait_task(client, url, chat, first_id)
                later = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'over-limit', 'goal': '保持必要历史', 'authorizedTools': ['synthetic_count']}).json()
                state = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][-1]['status'] in ('paused', 'failed'))
                task = state['tasks'][-1]
                self.assertEqual(task['status'], 'paused')
                self.assertIn('历史超过', task['pauseReason'])
                self.assertEqual(task.get('modelRequests', []), [])
                self.assertEqual(len(endpoint.requests), 1)
                self.assertEqual(client.post(url + f'/tasks/{later["id"]}/resume').status_code, 200)
                recovered = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][-1]['status'] in ('paused', 'failed'))['tasks'][-1]
                self.assertEqual(recovered['status'], 'paused')
                self.assertIn('历史超过', recovered['pauseReason'])
                self.assertNotEqual(task['submissionId'], recovered['submissionId'])
                self.assertEqual(len(endpoint.requests), 1)

    def test_cancel_inflight_records_actual_receiver_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-cancel', 'hold') as endpoint:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                url, chat, task_id, configs = self.setup(client, root, [('openai-responses', endpoint, 'artificial-cancel')])
                self.assertTrue(endpoint.entered.wait(5))
                cancelled = client.post(url + f'/tasks/{task_id}/cancel')
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                self.assertEqual(cancelled.json()['status'], 'cancelled')
                traces = cancelled.json()['modelRequests']
                self.assertEqual(traces[0]['configurationId'], configs[0]['id'])
                self.assertEqual(traces[0]['status'], 'cancelled')
                self.assertEqual(len(endpoint.requests), 1)

    def test_missing_usage_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-unknown', 'no_usage') as endpoint:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                url, chat, task_id, _ = self.setup(client, root, [('openai-responses', endpoint, 'artificial-unknown')])
                done = wait_task(client, url, chat, task_id)
                self.assertTrue(all(all(v is None for v in r['usage'].values()) and r['cost'] is None for r in done['modelRequests']))

    def test_same_conversation_uses_new_receiver_and_keeps_prior_tool_history(self):
        with tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-a') as first, FakeModelEndpoint('anthropic-messages', 'artificial-b') as second:
            root = Path(directory)
            (root / 'project').mkdir()
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                configs = []
                for protocol, endpoint, key in [('openai-responses', first, 'artificial-a'), ('anthropic-messages', second, 'artificial-b')]:
                    saved = client.post('/api/workbench/model-configs', json={'name': protocol, 'protocol': protocol, 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': key}).json()
                    configs.append(saved)
                project = client.post('/api/workbench/projects', json={'path': str(root / 'project')}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'switch history'}).json()['id']
                first_done = None
                for index, config in enumerate(configs):
                    client.put(url + f'/conversations/{chat}/model', json={'configurationId': config['id']})
                    task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': f'switch-{index}', 'goal': '记住人工来源 alpha' if index == 0 else '根据先前工具结果答复', 'authorizedTools': ['synthetic_count']}).json()
                    done = wait_task(client, url, chat, task['id'])
                    traces = done['modelRequests']
                    self.assertGreaterEqual(len(traces), 1)
                    self.assertEqual(traces[0]['configurationId'], config['id'])
                    self.assertEqual(traces[0]['endpoint'], config['baseUrl'])
                    self.assertEqual(traces[0]['protocol'], config['protocol'])
                    self.assertEqual(traces[0]['usage']['input'], 4)
                    self.assertEqual(traces[0]['usage']['output'], 3)
                    self.assertIsNone(traces[0]['cost'])
                    if index == 0:
                        first_done = done
                    else:
                        body = json.dumps(second.requests[0]['body'], ensure_ascii=False)
                        self.assertIn('记住人工来源 alpha', body)
                        self.assertIn('characters', body)
                        self.assertEqual(done['toolExecutions'], [])
                self.assertEqual(len(first.requests), 2)
                original = client.get(url).json()['tasks'][0]
                self.assertEqual(original['toolExecutions'], first_done['toolExecutions'])
                self.assertEqual(client.get(url + f'/conversations/{chat}').json()['modelRequests'], 3)


if __name__ == '__main__':
    unittest.main()
