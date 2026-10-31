"""Application-only model configuration; test credentials are explicitly injected."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from silicolab.server import create_app
from test_workbench_science import wait_task
from test_workbench_recovery import wait_state


class MemorySecrets:
    def __init__(self):
        self.values = {}
    def get(self, identity):
        return self.values.get(identity)
    def set(self, identity, value):
        self.values[identity] = value
    def delete(self, identity):
        self.values.pop(identity, None)


class FakeModelEndpoint:
    def __init__(self, protocol, key, mode='normal', tool_name='synthetic_count'):
        self.tool_name = tool_name
        self.protocol, self.key, self.mode = protocol, key, mode
        self.requests = []
        self.release = threading.Event()
        self.entered = threading.Event()
        endpoint = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                endpoint.requests.append({'path': self.path, 'headers': dict(self.headers), 'body': data})
                current_mode = mode[min(len(endpoint.requests) - 1, len(mode) - 1)] if isinstance(mode, list) else mode
                if current_mode == 'hold':
                    endpoint.entered.set()
                    endpoint.release.wait(6)
                if current_mode in ('rate_limit', 'server_error'):
                    self.send_response(429 if current_mode == 'rate_limit' else 503)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"temporary service error"}}')
                    return
                if current_mode == 'invalid_key':
                    self.send_response(401)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': {'type': 'authentication_error', 'message': key}}).encode())
                    return
                if current_mode == 'incompatible':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    self.wfile.write(b'data: {"type":"unrecognized_protocol"}\n\n')
                    return
                returned_tool_result = any(item.get('type') == 'function_call_output' for item in data.get('input', []) if isinstance(item, dict)) or any(block.get('type') == 'tool_result' for item in data.get('messages', []) for block in item.get('content', []) if isinstance(block, dict))
                if current_mode == 'duplicate_once':
                    returned_tool_result = False
                arguments = {'text': 'ABC'} if tool_name == 'synthetic_count' else {}
                if current_mode in ('long_original', 'duplicate_changed'):
                    arguments = {'text': 'P' * 160 + ('A' if current_mode == 'long_original' else 'B')}
                    if current_mode == 'duplicate_changed':
                        returned_tool_result = False
                reply = 'L' * 1000001 if current_mode == 'large_reply' else '人工模型已核对工具结果'
                if current_mode == 'large_reply':
                    returned_tool_result = True
                if current_mode == 'echo_property_name':
                    arguments[key] = {'nested-' + key: 'echo'}
                if protocol == 'openai-responses':
                    response = {'id': 'resp_artificial', 'object': 'response', 'status': 'completed', 'output': [], 'usage': {'input_tokens': 4, 'output_tokens': 3, 'total_tokens': 7}}
                    if data.get('tools') and not returned_tool_result:
                        item = {'id': 'fc_artificial', 'type': 'function_call', 'call_id': 'call_artificial', 'name': tool_name, 'arguments': json.dumps(arguments), 'status': 'completed'}
                    else:
                        item = {'id': 'msg_artificial', 'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': reply, 'annotations': []}]}
                    response['output'] = [item]
                    events = [{'type': 'response.created', 'response': response}, {'type': 'response.output_item.added', 'output_index': 0, 'item': item}, {'type': 'response.output_item.done', 'output_index': 0, 'item': item}, {'type': 'response.completed', 'response': response}]
                else:
                    tool = bool(data.get('tools')) and not returned_tool_result
                    block = {'type': 'tool_use', 'id': 'toolu_artificial', 'name': tool_name, 'input': arguments} if tool else {'type': 'text', 'text': reply}
                    events = [{'type': 'message_start', 'message': {'id': 'msg_artificial', 'type': 'message', 'role': 'assistant', 'model': 'artificial-model', 'content': [], 'usage': {'input_tokens': 4, 'output_tokens': 0}, 'stop_reason': None, 'stop_sequence': None}}, {'type': 'content_block_start', 'index': 0, 'content_block': block}, {'type': 'content_block_stop', 'index': 0}, {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use' if tool else 'end_turn', 'stop_sequence': None}, 'usage': {'output_tokens': 3}}, {'type': 'message_stop'}]
                    if tool:
                        events.insert(2, {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(arguments)}})
                if current_mode == 'no_usage':
                    for event in events:
                        if 'usage' in event:
                            del event['usage']
                        for field in ('response', 'message'):
                            if field in event:
                                event[field].pop('usage', None)
                if current_mode in ('disconnect', 'socket_drop'):
                    events = events[:1]
                raw = ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n' for event in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(raw) + 1024 if current_mode == 'socket_drop' else len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                if current_mode == 'socket_drop':
                    import socket
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}' + ('/v1' if protocol == 'openai-responses' else '')
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ModelConfigurationTests(unittest.TestCase):
    def test_both_explicit_protocols_drive_real_kernel_tool_loop_with_only_selected_secret(self):
        for protocol in ('openai-responses', 'anthropic-messages'):
            sentinel = 'artificial-key-' + protocol
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as directory, FakeModelEndpoint(protocol, sentinel) as endpoint:
                root = Path(directory)
                project_path = root / 'project'
                project_path.mkdir()
                with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                    config = client.post('/api/workbench/model-configs', json={'name': '人工协议验证', 'protocol': protocol, 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': sentinel}).json()
                    project = client.post('/api/workbench/projects', json={'path': str(project_path)}).json()
                    url = f'/api/workbench/projects/{project["id"]}'
                    chat = client.post(url + '/conversations', json={'title': 'secret isolation'}).json()['id']
                    selection = client.put(url + f'/conversations/{chat}/model', json={'configurationId': config['id']})
                    self.assertEqual(selection.status_code, 200, selection.text)
                    started = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'configured-model', 'goal': '核对人工文本ABC字符数', 'authorizedTools': ['synthetic_count']})
                    self.assertEqual(started.status_code, 201, started.text)
                    done = wait_task(client, url, chat, started.json()['id'])
                    self.assertEqual(done['toolExecutions'][0]['result']['characters'], 3)
                    self.assertEqual(len(endpoint.requests), 2)
                    for request in endpoint.requests:
                        headers = {k.lower(): v for k, v in request['headers'].items()}
                        if protocol == 'openai-responses':
                            self.assertEqual(request['path'], '/v1/responses')
                            self.assertEqual(headers['authorization'], 'Bearer ' + sentinel)
                        else:
                            self.assertEqual(request['path'].split('?')[0], '/v1/messages')
                            self.assertEqual(headers['x-api-key'], sentinel)
                        self.assertNotIn(sentinel, json.dumps(request['body']))
                    state = client.get(url + f'/conversations/{chat}')
                    self.assertNotIn(sentinel, state.text)
                    self.assertIn('人工模型已核对工具结果', state.text)
                    self.assertNotIn(sentinel, client.get('/api/workbench/model-configs').text)
                for path in project_path.rglob('*'):
                    if path.is_file():
                        self.assertNotIn(sentinel.encode(), path.read_bytes(), str(path))

    def test_echoed_secret_property_names_never_reach_checkpoint_or_next_prompt(self):
        for protocol in ('openai-responses', 'anthropic-messages'):
            sentinel = 'artificial-secret-property-name-sentinel'
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as directory, FakeModelEndpoint(protocol, sentinel, 'echo_property_name') as endpoint:
                root = Path(directory)
                (root / 'project').mkdir()
                with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                    config = client.post('/api/workbench/model-configs', json={'name': '人工属性回显', 'protocol': protocol, 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': sentinel}).json()
                    project = client.post('/api/workbench/projects', json={'path': str(root / 'project')}).json()
                    url = f'/api/workbench/projects/{project["id"]}'
                    chat = client.post(url + '/conversations', json={'title': 'echo property'}).json()['id']
                    client.put(url + f'/conversations/{chat}/model', json={'configurationId': config['id']})
                    task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'echo', 'goal': '人工文本ABC', 'authorizedTools': ['synthetic_count']}).json()
                    wait_task(client, url, chat, task['id'])
                    state = client.get(url + f'/conversations/{chat}').text
                    self.assertNotIn(sentinel, state)
                    self.assertEqual(len(endpoint.requests), 2)
                    for request in endpoint.requests:
                        self.assertNotIn(sentinel, json.dumps(request['body']))
                for path in (root / 'project').rglob('*'):
                    if path.is_file():
                        self.assertNotIn(sentinel.encode(), path.read_bytes(), str(path))

    def test_removed_selected_model_is_explicitly_unavailable_never_faux_fallback(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                config = client.post('/api/workbench/model-configs', json={'name': '人工移除模型', 'protocol': 'openai-responses', 'baseUrl': 'http://127.0.0.1:9/v1', 'modelId': 'artificial-model', 'apiKey': 'artificial-key'}).json()
                (root / 'project').mkdir()
                project = client.post('/api/workbench/projects', json={'path': str(root / 'project')}).json()
                url = f'/api/workbench/projects/{project["id"]}'
                chat = client.post(url + '/conversations', json={'title': 'missing selected model'}).json()['id']
                client.put(url + f'/conversations/{chat}/model', json={'configurationId': config['id']})
                client.delete('/api/workbench/model-configs/' + config['id'])
                task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'missing', 'goal': 'ABC', 'authorizedTools': ['synthetic_count']}).json()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state = client.get(url + f'/conversations/{chat}').json()
                    if state['tasks'][0]['status'] == 'paused':
                        break
                    time.sleep(0.01)
                self.assertEqual(state['tasks'][0]['status'], 'paused')
                self.assertIn('未切换接收方', state['tasks'][0]['pauseReason'])
                self.assertEqual(state['tasks'][0]['toolExecutions'], [])
                self.assertEqual(state['modelRequests'], 0)

    def test_protocol_errors_never_persist_echoed_credentials_or_fallback(self):
        for protocol in ('openai-responses', 'anthropic-messages'):
            for mode in ('invalid_key', 'incompatible'):
                sentinel = 'artificial-key-error-echo-sentinel'
                with self.subTest(protocol=protocol, mode=mode), tempfile.TemporaryDirectory() as directory, FakeModelEndpoint(protocol, sentinel, mode) as endpoint:
                    root = Path(directory)
                    project_path = root / 'project'
                    project_path.mkdir()
                    with TestClient(create_app(root / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                        config = client.post('/api/workbench/model-configs', json={'name': '人工错误路径', 'protocol': protocol, 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': sentinel}).json()
                        project = client.post('/api/workbench/projects', json={'path': str(project_path)}).json()
                        url = f'/api/workbench/projects/{project["id"]}'
                        chat = client.post(url + '/conversations', json={'title': 'errors'}).json()['id']
                        client.put(url + f'/conversations/{chat}/model', json={'configurationId': config['id']})
                        task = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'error-path', 'goal': '人工错误路径', 'authorizedTools': ['synthetic_count']}).json()
                        done = wait_state(client, url + f'/conversations/{chat}', lambda s: s['tasks'][0]['status'] == 'paused')['tasks'][0]
                        self.assertEqual(done['toolExecutions'], [])
                        state = client.get(url + f'/conversations/{chat}').text
                        self.assertNotIn(sentinel, state)
                        self.assertIn('未自动切换接收方', state)
                        self.assertIn('凭据无效' if mode == 'invalid_key' else '协议不兼容', state)
                        self.assertEqual(len(endpoint.requests), 1)
                    for path in project_path.rglob('*'):
                        if path.is_file():
                            self.assertNotIn(sentinel.encode(), path.read_bytes(), str(path))

    def test_explicit_connection_check_marks_only_successful_selected_protocol(self):
        for mode in ('normal', 'invalid_key', 'incompatible'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, FakeModelEndpoint('openai-responses', 'artificial-verify-key', mode) as endpoint:
                with TestClient(create_app(Path(directory) / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                    config = client.post('/api/workbench/model-configs', json={'name': '人工连接检查', 'protocol': 'openai-responses', 'baseUrl': endpoint.url, 'modelId': 'artificial-model', 'apiKey': 'artificial-verify-key'}).json()
                    self.assertEqual(endpoint.requests, [])
                    checked = client.post('/api/workbench/model-configs/' + config['id'] + '/verify')
                    self.assertEqual(checked.status_code, 200 if mode == 'normal' else 409, checked.text)
                    persisted = client.get('/api/workbench/model-configs').json()[0]
                    self.assertEqual(persisted['verification'], 'verified_transport' if mode == 'normal' else 'unverified')
                    self.assertEqual(len(endpoint.requests), 1)
                    self.assertNotIn('artificial-verify-key', checked.text)

    def test_native_keychain_stores_only_silicolab_artificial_key_and_removes_it(self):
        import sys
        import uuid
        if sys.platform != 'darwin':
            self.skipTest('macOS Keychain')
        from silicolab.model_configuration import KeychainSecrets
        store = KeychainSecrets()
        identity = 'artificial-test-' + uuid.uuid4().hex
        try:
            self.assertIsNone(store.get(identity))
            store.set(identity, 'artificial-keychain-sentinel')
            self.assertEqual(store.get(identity), 'artificial-keychain-sentinel')
            store.set(identity, 'artificial-keychain-updated')
            self.assertEqual(store.get(identity), 'artificial-keychain-updated')
        finally:
            store.delete(identity)
        self.assertIsNone(store.get(identity))

    def test_configuration_is_app_owned_protocol_explicit_and_secret_never_returned_or_persisted(self):
        sentinel = 'artificial-model-key-sentinel-not-a-real-credential'
        secrets = MemorySecrets()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'app.sqlite3'
            with TestClient(create_app(database, delay=0, credential_store=secrets)) as client:
                response = client.post('/api/workbench/model-configs', json={'name': '人工 Responses', 'protocol': 'openai-responses', 'baseUrl': 'http://127.0.0.1:9/v1', 'modelId': 'artificial-model', 'apiKey': sentinel})
                self.assertEqual(response.status_code, 201, response.text)
                saved = response.json()
                self.assertNotIn(sentinel, response.text)
                self.assertEqual(saved['protocol'], 'openai-responses')
                self.assertEqual(saved['verification'], 'unverified')
                self.assertTrue(saved['hasKey'])
                self.assertEqual(secrets.get(saved['id']), sentinel)
                self.assertNotIn(sentinel, client.get('/api/workbench/model-configs').text)
                self.assertNotIn(sentinel, (root / 'model-configs.json').read_text())
            with TestClient(create_app(database, delay=0, credential_store=secrets)) as client:
                items = client.get('/api/workbench/model-configs').json()
                self.assertEqual(items[0]['id'], saved['id'])
                self.assertTrue(items[0]['hasKey'])
                removed = client.delete('/api/workbench/model-configs/' + saved['id'])
                self.assertEqual(removed.status_code, 200, removed.text)
                self.assertIsNone(secrets.get(saved['id']))
                self.assertEqual(client.get('/api/workbench/model-configs').json(), [])

    def test_protocol_is_not_inferred_from_url_and_credentials_cannot_be_embedded_in_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory) / 'app.sqlite3', delay=0, credential_store=MemorySecrets())) as client:
                for values in (
                    {'name': 'missing protocol', 'baseUrl': 'http://127.0.0.1:9/v1', 'modelId': 'artificial-model', 'apiKey': 'artificial'},
                    {'name': 'bad protocol', 'protocol': 'guess-from-url', 'baseUrl': 'http://127.0.0.1:9/v1', 'modelId': 'artificial-model', 'apiKey': 'artificial'},
                    {'name': 'credential url', 'protocol': 'anthropic-messages', 'baseUrl': 'https://artificial-user:artificial-password@example.invalid', 'modelId': 'artificial-model', 'apiKey': 'artificial'},
                    {'name': 'credential query', 'protocol': 'anthropic-messages', 'baseUrl': 'https://example.invalid?key=secret', 'modelId': 'artificial-model', 'apiKey': 'artificial'},
                ):
                    response = client.post('/api/workbench/model-configs', json=values)
                    self.assertIn(response.status_code, (409, 422), response.text)
                self.assertEqual(client.get('/api/workbench/model-configs').json(), [])


if __name__ == '__main__':
    unittest.main()
