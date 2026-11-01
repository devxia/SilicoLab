"""Public bootstrap must fail clearly before touching build files on old Python."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('bootstrap',ROOT/'packaging/macos/bootstrap.py');bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)


class PackagingPrerequisiteTests(unittest.TestCase):
    def test_old_host_python_rejected_before_download_or_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(bootstrap,'ROOT',Path(directory)),patch.object(bootstrap.sys,'version_info',(3,9,6)):
            with self.assertRaisesRegex(RuntimeError,'3.12'):bootstrap.bootstrap()
            self.assertEqual(list(Path(directory).iterdir()),[])


if __name__=='__main__':unittest.main()
