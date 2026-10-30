import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from execution import PythonProbe


class FailureBoundaryTests(unittest.TestCase):
    def test_shell_exec_is_denied_and_python_reexec_keeps_file_and_network_restrictions(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-reexec-") as directory:
            sentinel = Path(directory) / "outside.txt"
            sentinel.write_text("FAKE_REEXEC_CREDENTIAL_ONLY", encoding="utf-8")
            payload = f'''
import json, socket
from pathlib import Path
checks={{}}
for name, action in [('file', lambda:Path({str(sentinel)!r}).read_text()), ('network', lambda:socket.create_connection(('127.0.0.1',9), timeout=0.2))]:
    try:
        action()
        checks[name]='allowed'
    except OSError as error:
        checks[name]=error.errno
Path('reexec.json').write_text(json.dumps(checks))
'''
            with PythonProbe() as host:
                shell = host.start("import os;os.execv('/bin/sh',['sh','-c','echo unexpected'])")
                result = shell.wait()
                self.assertEqual(result["status"], "failed", result)
                self.assertIn("PermissionError", result["stderr"])
                run = host.start(f"import os,sys;os.execv(sys.executable,[sys.executable,'-I','-S','-B','-c',{payload!r}])")
                self.assertEqual(run.wait()["status"], "completed", run.status())
                self.assertTrue(all(value in [errno.EPERM, errno.EACCES] for value in json.loads(run.artifact("reexec.json")).values()))

    def test_sandbox_start_failure_never_falls_back_to_running_the_script(self):
        with PythonProbe() as host:
            with patch("execution.subprocess.Popen", side_effect=OSError("artificial sandbox startup failure")):
                with self.assertRaisesRegex(OSError, "sandbox startup failure"):
                    host.start("raise RuntimeError('must not run')")
            run = host.start("from pathlib import Path;Path('ok.txt').write_text('retry uses sandbox')")
            self.assertEqual(run.wait()["status"], "completed", run.status())
            self.assertEqual(run.artifact("ok.txt"), b"retry uses sandbox")

    def test_dependency_materialization_rejects_a_symlink_into_host_files(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-package-sentinel-") as directory:
            root = Path(directory)
            module = root / 'openpyxl'
            module.mkdir()
            private = root / 'credential.txt'
            private.write_text('FAKE_PACKAGE_SYMLINK_CREDENTIAL_ONLY')
            (module / '__init__.py').symlink_to(private)
            class SyntheticDistribution:
                version = '3.1.5'
                def locate_file(self, _name):
                    return module
            with patch('execution.distribution', return_value=SyntheticDistribution()):
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    PythonProbe()

    def test_artifact_reader_rejects_script_created_symlink_and_fifo(self):
        with PythonProbe() as host:
            run = host.start('''
import os
from pathlib import Path
Path('real.txt').write_text('real output')
os.symlink('real.txt', 'link.txt')
os.mkfifo('pipe')
''')
            self.assertEqual(run.wait()["status"], "completed", run.status())
            self.assertEqual(run.artifact("real.txt"), b"real output")
            for name in ["link.txt", "pipe", "../analysis.py", "/dev/null"]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    run.artifact(name)


if __name__ == "__main__":
    unittest.main()
