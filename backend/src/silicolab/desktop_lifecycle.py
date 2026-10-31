"""Independent background ownership protocol, no browser or model credentials."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import uuid
import threading

from silicolab.branding import SERVICE_ID
import fcntl

_spawned = []


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(temporary, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as output:
            json.dump(value, output)
            output.flush(); os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def service_info(directory):
    try:
        info = json.loads((Path(directory) / 'background.json').read_text())
        port = info['port']
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            return None
        with urlopen(f'http://127.0.0.1:{port}/api/desktop/status', timeout=0.5) as response:
            actual = json.load(response)
        if actual['app'] != SERVICE_ID or actual['serviceId'] != info['serviceId'] or actual['pid'] != info['pid']:
            return None
        return dict(info, origin=f'http://127.0.0.1:{port}')
    except (OSError, ValueError, KeyError):
        return None


def ensure_service(directory, *, isolated_resources=False):
    info = service_info(directory)
    if info:
        return info
    command = [sys.executable, '--background-service'] if getattr(sys, 'frozen', False) else [sys.executable, '-B', '-m', 'silicolab.desktop_service']
    if isolated_resources:
        command.append('--isolated-resources')
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'SILICOLAB_RUNTIME', 'SILICOLAB_NODE', 'SILICOLAB_FRONTEND_DIST') if key in os.environ}
    env['SILICOLAB_APP_DATA'] = str(directory)
    with (Path(directory) / 'background-launch.log').open('ab') as log:
        child = subprocess.Popen(command, cwd='/', env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
    _spawned.append(child)
    def reap():
        child.wait()
        _spawned.remove(child)
    threading.Thread(target=reap, daemon=True).start()
    for _ in range(200):
        info = service_info(directory)
        if info:
            return info
        if child.poll() is not None and child.returncode != 0:
            raise ValueError('独立后台启动失败；请检查应用日志，未创建替代项目')
        time.sleep(0.05)
    raise ValueError('独立后台尚未就绪；未宣称任务继续，请检查日志后重开')


def service_has_owner(directory):
    """Lease, not an untrusted/stale PID, proves that some background owner remains."""
    lease = (Path(directory) / 'background.lock').open('a+')
    try:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        lease.close()


def stop_service(directory):
    info = service_info(directory)
    if not info:
        if service_has_owner(directory):
            raise ValueError('后台仍持有执行权但无响应；未确认完全退出，窗口保持打开')
        return False
    request = Request(info['origin'] + '/api/desktop/quit', data=b'{}', headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + info['token']})
    try:
        with urlopen(request, timeout=10) as response:
            if not json.load(response).get('stopping'):
                raise ValueError('后台未确认完全退出')
    except (OSError, ValueError):
        raise ValueError('后台未确认完全退出；窗口保持打开，请检查连接后重试') from None
    for _ in range(200):
        if not service_has_owner(directory): return True
        time.sleep(0.05)
    raise ValueError('后台仍未释放执行权；未确认完全退出，窗口保持打开')


def gui_command(directory, operation):
    try:
        info = json.loads((Path(directory) / 'gui-session.json').read_text())
        port = info['port']
        if not isinstance(port, int) or not 1024 <= port <= 65535: return False
        with socket.create_connection(('127.0.0.1', port), timeout=2) as channel:
            channel.sendall((json.dumps({'token': info['token'], 'operation': operation}) + '\n').encode())
            return json.loads(channel.recv(4096)).get('accepted') is True
    except (OSError, ValueError, KeyError):
        return False
