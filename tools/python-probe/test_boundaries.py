import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from execution import PythonProbe


class FileBoundaryTests(unittest.TestCase):
    def test_original_input_snapshot_outside_file_and_synthetic_credential_stay_protected(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-sentinels-") as directory:
            root = Path(directory)
            source = root / "values.csv"
            outside = root / "private-data.txt"
            credential = root / "sentinel-credential.txt"
            source.write_text("value\n1\n", encoding="utf-8")
            outside.write_text("artificial-private-content", encoding="utf-8")
            credential.write_text("FAKE_TEST_CREDENTIAL_ONLY", encoding="utf-8")
            with patch.dict(os.environ, {"SILICOLAB_FAKE_KEY": "FAKE_TEST_CREDENTIAL_ONLY", "PYTHONPATH": str(root)}):
                with PythonProbe() as host:
                    run = host.start(f'''
import json, os
from pathlib import Path
checks = {{}}
for name, path, mode in [
    ('outside-read', {str(outside)!r}, 'r'),
    ('credential-read', {str(credential)!r}, 'r'),
    ('original-write', {str(source)!r}, 'w'),
    ('input-write', str(INPUTS / 'values.csv'), 'w'),
    ('outside-write', {str(outside)!r}, 'w'),
]:
    try:
        with open(path, mode) as file:
            file.read() if mode == 'r' else file.write('MUTATED')
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
checks['env-key'] = os.environ.get('SILICOLAB_FAKE_KEY')
checks['pythonpath'] = os.environ.get('PYTHONPATH')
Path('denials.json').write_text(json.dumps(checks))
''', inputs=[source])
                    result = run.wait()
                    self.assertEqual(result["status"], "completed", result)
                    checks = json.loads(run.artifact("denials.json"))
                    for name in ["outside-read", "credential-read", "original-write", "input-write", "outside-write"]:
                        self.assertIn(checks[name], [errno.EPERM, errno.EACCES], (name, checks))
                    self.assertIsNone(checks["env-key"])
                    self.assertIsNone(checks["pythonpath"])
                    self.assertTrue(result["inputs_unchanged"])
                    self.assertEqual(outside.read_text(), "artificial-private-content")
                    self.assertEqual(credential.read_text(), "FAKE_TEST_CREDENTIAL_ONLY")

    def test_symlink_hardlink_relative_and_directory_fd_do_not_escape_output(self):
        with tempfile.TemporaryDirectory(prefix="silicolab-aliases-") as directory:
            target = Path(directory) / "outside.txt"
            target.write_text("unchanged", encoding="utf-8")
            with PythonProbe() as host:
                run = host.start(f'''
import json, os
from pathlib import Path
checks = {{}}
for name, action in [
    ('symlink-create', lambda: os.symlink({str(target)!r}, 'alias')),
    ('symlink-read', lambda: Path('alias').read_text()),
    ('symlink-write', lambda: Path('alias').write_text('MUTATED')),
    ('hardlink', lambda: os.link({str(target)!r}, 'hardalias')),
    ('parent-write', lambda: Path('../escaped.txt').write_text('MUTATED')),
    ('relative-read', lambda: Path(os.path.relpath({str(target)!r})).read_text()),
    ('dirfd-read', lambda: os.open('outside.txt', os.O_RDONLY, dir_fd=os.open({str(target.parent)!r}, os.O_RDONLY))),
]:
    try:
        action()
        checks[name] = 'allowed'
    except OSError as error:
        checks[name] = error.errno
Path('aliases.json').write_text(json.dumps(checks))
''')
                result = run.wait()
                self.assertEqual(result["status"], "completed", result)
                checks = json.loads(run.artifact("aliases.json"))
                self.assertEqual(checks.pop('symlink-create'), 'allowed', checks)
                for name, value in checks.items():
                    self.assertIn(value, [errno.EPERM, errno.EACCES], (name, checks))
                self.assertEqual(target.read_text(), "unchanged")
                with self.assertRaises(ValueError):
                    run.artifact(str(target))
                with self.assertRaises(ValueError):
                    run.artifact('alias')


if __name__ == "__main__":
    unittest.main()
