import errno
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from execution import PythonProbe


def wait_for_artifact(run, name):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            return run.artifact(name)
        except FileNotFoundError:
            if run.status()["status"] != "running":
                raise AssertionError(run.status())
            time.sleep(0.02)
    raise AssertionError("task did not reach its observable checkpoint")


class StopAndIsolationTests(unittest.TestCase):
    def test_stop_kills_a_script_that_ignores_termination_and_no_child_can_survive(self):
        with PythonProbe() as host:
            run = host.start('''
import errno, json, os, signal, subprocess, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
checks = {}
for name, action in [
    ('fork', os.fork),
    ('detached', lambda: subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import time;time.sleep(60)'], start_new_session=True)),
]:
    try:
        action()
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
# Publish only after the complete JSON has been written and closed.
Path('ready.pending').write_text(json.dumps(checks))
Path('ready.pending').replace('ready.json')
while True:
    with Path('heartbeat.txt').open('a') as output:
        output.write('tick\\n')
    time.sleep(0.02)
''')
            ready = json.loads(wait_for_artifact(run, "ready.json"))
            self.assertTrue(all(value in [errno.EPERM, errno.EACCES] for value in ready.values()), ready)
            wait_for_artifact(run, "heartbeat.txt")
            self.assertEqual(run.stop()["status"], "stopped")
            with self.assertRaises(ProcessLookupError):
                os.kill(run.pid, 0)
            saved = run.artifact("heartbeat.txt")
            time.sleep(0.1)
            self.assertEqual(run.artifact("heartbeat.txt"), saved)
            self.assertEqual(run.stop()["status"], "stopped")

    def test_host_close_and_timeout_reclaim_running_interpreters(self):
        host = PythonProbe()
        run = host.start("from pathlib import Path; import time; Path('ready').write_text('yes'); time.sleep(60)")
        try:
            wait_for_artifact(run, "ready")
            host.close()
            with self.assertRaises(ProcessLookupError):
                os.kill(run.pid, 0)
            host.close()
        finally:
            host.close()
        with PythonProbe() as host:
            run = host.start("import time; time.sleep(60)")
            import subprocess
            with self.assertRaises(subprocess.TimeoutExpired):
                run.wait(timeout=0.1)
            self.assertEqual(run.status()["status"], "stopped")
            with self.assertRaises(ProcessLookupError):
                os.kill(run.pid, 0)

    def test_task_cannot_read_another_task_or_write_its_script_and_preinstalled_library(self):
        with PythonProbe() as host:
            first = host.start("from pathlib import Path; Path('private.txt').write_text('synthetic-task-1')")
            self.assertEqual(first.wait()["status"], "completed")
            prior_task = first.status()["task_id"]
            run = host.start('''
import errno, json, openpyxl
from pathlib import Path
checks = {}
for name, action in [
    ('task-read', lambda: Path('../../PRIOR_TASK/outputs/private.txt').read_text()),
    ('script-write', lambda: Path('../analysis.py').write_text('pass')),
    ('library-write', lambda: Path(openpyxl.__file__).write_text('pass')),
]:
    try:
        action()
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
Path('isolation.json').write_text(json.dumps(checks))
'''.replace('PRIOR_TASK', prior_task))
            self.assertEqual(run.wait()["status"], "completed", run.status())
            self.assertTrue(all(value in [errno.EPERM, errno.EACCES] for value in json.loads(run.artifact("isolation.json")).values()))
            self.assertEqual(first.artifact("private.txt"), b"synthetic-task-1")

    def test_inheritable_host_descriptor_does_not_expose_synthetic_credential(self):
        with tempfile.TemporaryFile() as credential:
            credential.write(b"FAKE_DESCRIPTOR_CREDENTIAL_ONLY")
            credential.flush()
            credential.seek(0)
            os.set_inheritable(credential.fileno(), True)
            with PythonProbe() as host:
                run = host.start(f'''
import os
from pathlib import Path
try:
    result = os.pread({credential.fileno()}, 100, 0).decode()
except OSError:
    result = 'descriptor closed'
Path('descriptor.txt').write_text(result)
''')
                self.assertEqual(run.wait()["status"], "completed", run.status())
                self.assertNotIn(b"FAKE_DESCRIPTOR_CREDENTIAL_ONLY", run.artifact("descriptor.txt"))


if __name__ == "__main__":
    unittest.main()
