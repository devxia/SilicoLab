import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from silicolab.branding import APP_NAME, APP_VERSION, DATABASE_FILENAME, MACOS_BUNDLE_ID, SERVICE_ID
from silicolab.paths import application_directory, read_preferences, write_preferences


class DesktopPathTests(unittest.TestCase):
    def test_application_data_override_is_created_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'app-data'
            with patch.dict(os.environ, {'SILICOLAB_APP_DATA': str(root)}):
                self.assertEqual(application_directory(), root)
            self.assertTrue(root.is_dir())
            write_preferences(root, {'port': 12001})
            self.assertEqual(read_preferences(root), {'port': 12001})
            self.assertEqual((root / 'desktop.json').stat().st_mode & 0o777, 0o600)

    def test_missing_or_invalid_preferences_return_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(read_preferences(root), {})
            (root / 'desktop.json').write_text('bad')
            self.assertEqual(read_preferences(root), {})
            (root / 'desktop.json').write_text('[]')
            self.assertEqual(read_preferences(root), {})

    def test_default_path_is_silicolab_and_does_not_import_external_history(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.dict(os.environ, {}, clear=True), patch('silicolab.paths.Path.home', return_value=home):
                root = application_directory()
            self.assertEqual(root, home / 'Library/Application Support/SilicoLab')
            self.assertEqual(list(root.iterdir()), [])
            from silicolab import paths as desktop_paths
            self.assertFalse(hasattr(desktop_paths, 'migrate_database'))

    def test_product_identity_and_version_are_consistent(self):
        self.assertEqual(APP_NAME, 'SilicoLab')
        self.assertEqual(APP_VERSION, '0.2.0')
        self.assertEqual(SERVICE_ID, 'silicolab')
        self.assertEqual(MACOS_BUNDLE_ID, 'com.silicolab.desktop')
        self.assertEqual(DATABASE_FILENAME, 'silicolab.sqlite3')
        root = Path(__file__).resolve().parents[2] / "frontend"
        package = json.loads((root / 'package.json').read_text())
        lock = json.loads((root / 'package-lock.json').read_text())
        for item in [package, lock, lock['packages']['']]:
            self.assertEqual(item['name'], SERVICE_ID)
            self.assertEqual(item['version'], APP_VERSION)


if __name__ == '__main__':
    unittest.main()
