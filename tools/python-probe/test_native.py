import errno
import json
from pathlib import Path
import socket
import struct
import tempfile
import unittest

from execution import PythonProbe


class NativeBoundaryTests(unittest.TestCase):
    def test_libc_open_and_connect_still_obey_kernel_policy(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-native-") as directory:
            sentinel = Path(directory) / "credential.txt"
            sentinel.write_text("FAKE_NATIVE_CREDENTIAL_ONLY", encoding="utf-8")
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                address = struct.pack("BB", 16, socket.AF_INET) + struct.pack("!H", listener.getsockname()[1]) + socket.inet_aton("127.0.0.1") + b"\0" * 8
                with PythonProbe() as host:
                    run = host.start(f'''
import ctypes, json, os, socket
from pathlib import Path
libc = ctypes.CDLL(None, use_errno=True)
libc.open.argtypes = [ctypes.c_char_p, ctypes.c_int]
libc.connect.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
results = {{}}
fd = libc.open(os.fsencode({str(sentinel)!r}), os.O_RDONLY)
results['native-open'] = ctypes.get_errno() if fd < 0 else 'allowed'
if fd >= 0:
    os.close(fd)
with socket.socket() as client:
    sockaddr = ctypes.create_string_buffer({address!r})
    result = libc.connect(client.fileno(), sockaddr, 16)
    results['native-connect'] = ctypes.get_errno() if result < 0 else 'allowed'
Path('native.json').write_text(json.dumps(results))
''')
                    result = run.wait()
                    self.assertEqual(result["status"], "completed", result)
                    for name, error in json.loads(run.artifact("native.json")).items():
                        self.assertIn(error, [errno.EPERM, errno.EACCES], name)
                    listener.settimeout(0.05)
                    with self.assertRaises(TimeoutError):
                        listener.accept()
                    self.assertEqual(sentinel.read_text(), "FAKE_NATIVE_CREDENTIAL_ONLY")

    def test_runtime_packages_system_and_task_control_files_are_not_writable(self):
        with PythonProbe() as host:
            run = host.start('''
import json, os, sys
from pathlib import Path
checks = {}
for name, action in [
    ('system-null-write', lambda: Path('/dev/null').open('w')),
    ('stdout-path-write', lambda: Path('../stdout.txt').open('w')),
    ('profile-write', lambda: Path('../profile.sb').write_text('(allow default)')),
    ('runtime-write', lambda: Path(sys.executable).open('ab')),
]:
    try:
        result = action()
        if hasattr(result, 'close'):
            result.close()
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
Path('writes.json').write_text(json.dumps(checks))
''')
            self.assertEqual(run.wait()["status"], "completed", run.status())
            for name, error in json.loads(run.artifact("writes.json")).items():
                self.assertIn(error, [errno.EPERM, errno.EACCES], name)


if __name__ == "__main__":
    unittest.main()
