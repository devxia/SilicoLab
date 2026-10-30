"""Generate a genuine previously-published scientific project for UI upgrade checks.

Requires Git history containing the #7 delivery and an already-populated npm
cache. Only temporary source, a loopback server and artificial files are used.
"""
import base64
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

import httpx

BASE = 'a36eebd776e546a367a128ae6ff6b39f87d00ff8'


def create_legacy_project(project: Path):
    project.mkdir()
    archive = subprocess.check_output(['git', 'archive', BASE, 'backend/src', 'runtime/src', 'runtime/package.json', 'runtime/package-lock.json'])
    with tempfile.TemporaryDirectory(prefix='silicolab-previous-release-') as directory:
        root = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            for member in source.getmembers():
                destination = root / member.name
                if member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.extractfile(member).read())
        user, global_config = root / 'empty-user.npmrc', root / 'empty-global.npmrc'
        user.touch()
        global_config.touch()
        env = {key: value for key, value in os.environ.items() if key in ['PATH', 'HOME', 'TMPDIR', 'LANG']}
        subprocess.run(['npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund',
                        '--userconfig=' + str(user), '--globalconfig=' + str(global_config)],
                       cwd=root / 'runtime', env=env, check=True, capture_output=True, text=True, timeout=60)
        env.update(PYTHONPATH=str(root / 'backend/src'), SILICOLAB_DB=str(root / 'app.sqlite3'))
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen([sys.executable, '-B', '-m', 'uvicorn', 'silicolab.server:create_app', '--factory',
                                    '--host', '127.0.0.1', '--port', str(port), '--log-level', 'warning'],
                                   cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10, trust_env=False) as client:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        if client.get('/api/health').is_success:
                            break
                    except httpx.TransportError:
                        pass
                    if process.poll() is not None:
                        raise AssertionError('Previous release server failed to start')
                    time.sleep(0.05)
                else:
                    raise AssertionError('Previous release server did not become ready')
                saved = client.post('/api/workbench/projects', json={'path': str(project), 'name': '旧格式科学结果'}).json()
                url = '/api/workbench/projects/' + saved['id']
                chat = client.post(url + '/conversations', json={'title': '从已发布版本重开'}).json()['id']
                content = b'>legacy-good\nK*\n>legacy-failed\nM*\n'
                imported = client.post(url + '/files', json={'name': 'legacy.fasta', 'contentBase64': base64.b64encode(content).decode()}).json()
                version = client.post(url + '/input-versions', json={'conversationId': chat, 'fileIds': [imported['id']]}).json()
                response = client.post(url + '/tasks', json={'conversationId': chat, 'requestId': 'legacy', 'goal': '明确 D2P 专项本地实验',
                                                           'workflow': 'd2p_local', 'specialtyAcknowledged': True, 'inputVersionId': version['id'],
                                                           'authorizedTools': ['d2p_local'], 'parameters': {'stopPolicy': 'preserve', 'avoid': 'ATG'}})
                assert response.is_success, response.text
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    state = client.get(url + '/conversations/' + chat).json()
                    if state['tasks'][0]['status'] == 'answered':
                        execution = state['tasks'][0]['toolExecutions'][0]
                        assert 'attempt' not in execution['result']
                        assert 'terminal_stop_present' not in execution['result']['records'][1]
                        return saved['id'], chat, state
                    time.sleep(0.03)
                raise AssertionError('Previous release did not complete the artificial task')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
