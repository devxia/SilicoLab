import errno
import json
from pathlib import Path
import socket
import tempfile
import unittest

from execution import PythonProbe


class NetworkAndInstallTests(unittest.TestCase):
    def test_live_loopback_ipv4_ipv6_udp_dns_and_unix_socket_are_denied(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-network-") as directory:
            with socket.socket() as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp, socket.socket(socket.AF_UNIX) as unix:
                tcp.bind(("127.0.0.1", 0))
                tcp.listen()
                udp.bind(("127.0.0.1", 0))
                unix_path = str(Path(directory) / "sentinel.sock")
                unix.bind(unix_path)
                unix.listen()
                # An unsandboxed control proves the listener is live, rather than a refusal by an absent service.
                with socket.create_connection(tcp.getsockname(), timeout=1):
                    accepted, _ = tcp.accept()
                    accepted.close()
                with PythonProbe() as host:
                    run = host.start(f'''
import json, socket
from pathlib import Path
checks = {{}}
def connect(family, kind, address, send=False):
    with socket.socket(family, kind) as client:
        client.settimeout(1)
        client.sendto(b'artificial', address) if send else client.connect(address)
for name, action in [
    ('tcp-ipv4', lambda: connect(socket.AF_INET, socket.SOCK_STREAM, {tcp.getsockname()!r})),
    ('udp-ipv4', lambda: connect(socket.AF_INET, socket.SOCK_DGRAM, {udp.getsockname()!r}, True)),
    ('udp-ipv6', lambda: connect(socket.AF_INET6, socket.SOCK_DGRAM, ('::1', 9), True)),
    ('dns-packet', lambda: connect(socket.AF_INET, socket.SOCK_DGRAM, ('127.0.0.1', 53), True)),
    ('unix-ipc', lambda: connect(socket.AF_UNIX, socket.SOCK_STREAM, {unix_path!r})),
]:
    try:
        action()
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
Path('network.json').write_text(json.dumps(checks))
''')
                    result = run.wait()
                    self.assertEqual(result["status"], "completed", result)
                    checks = json.loads(run.artifact("network.json"))
                    for name, value in checks.items():
                        self.assertIn(value, [errno.EPERM, errno.EACCES], (name, checks))
                    tcp.settimeout(0.05)
                    udp.settimeout(0.05)
                    with self.assertRaises(TimeoutError):
                        tcp.accept()
                    with self.assertRaises(TimeoutError):
                        udp.recvfrom(1024)

    def test_python_and_native_syscalls_cannot_start_child_processes(self):
        with PythonProbe() as host:
            run = host.start('''
import ctypes, json, os, subprocess, sys
from pathlib import Path
checks = {}
def native_fork():
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.fork()
    if result == 0:
        os._exit(73)
    if result == -1:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    os.waitpid(result, 0)
for name, action in [
    ('fork', os.fork),
    ('double-fork', lambda: os.fork() or os.fork()),
    ('subprocess', lambda: subprocess.run([sys.executable, '-I', '-S', '-c', 'pass'], check=True)),
    ('detached', lambda: subprocess.run([sys.executable, '-I', '-S', '-c', 'pass'], check=True, start_new_session=True)),
    ('posix-spawn', lambda: os.posix_spawn(sys.executable, [sys.executable, '-c', 'pass'], {})),
    ('native-fork', native_fork),
]:
    try:
        action()
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
Path('processes.json').write_text(json.dumps(checks))
''')
            result = run.wait()
            self.assertEqual(result["status"], "completed", result)
            checks = json.loads(run.artifact("processes.json"))
            for name, value in checks.items():
                self.assertIn(value, [errno.EPERM, errno.EACCES], (name, checks))

    def test_installer_bootstrap_and_runtime_package_writes_are_denied(self):
        with PythonProbe() as host:
            run = host.start('''
import json, subprocess, sys, sysconfig
from pathlib import Path
checks = {}
for name, action in [
    ('pip-import', lambda: __import__('pip')),
    ('ensurepip', lambda: __import__('ensurepip').bootstrap(default_pip=True)),
    ('pip-process', lambda: subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', 'fake-test-package'], check=True)),
    ('package-write', lambda: Path(sysconfig.get_path('purelib'), 'synthetic_package.py').write_text('pass')),
]:
    try:
        action()
        checks[name] = 'allowed'
    except (OSError, ImportError) as error:
        checks[name] = type(error).__name__
Path('install.json').write_text(json.dumps(checks))
''')
            result = run.wait()
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(json.loads(run.artifact("install.json")), {
                "pip-import": "ModuleNotFoundError", "ensurepip": "PermissionError",
                "pip-process": "PermissionError", "package-write": "PermissionError",
            })


if __name__ == "__main__":
    unittest.main()
