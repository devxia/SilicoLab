"""Resource and entry-point invariants for the organized source/package layout."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from silicolab import paths
from silicolab.features.codon import local
from silicolab.features.codon.engines import engine_metadata


class LayoutTests(unittest.TestCase):
    def test_source_frontend_and_database_are_outside_python_package(self):
        root = Path(__file__).resolve().parents[2]
        with patch.dict(os.environ, {}, clear=True), patch.object(paths, "project_directory", return_value=root):
            self.assertEqual(paths.browser_database(), root / "data/silicolab.sqlite3")
            self.assertEqual(paths.frontend_directory(), root / "frontend/dist")

    def test_explicit_database_and_frontend_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"SILICOLAB_DB": str(root / "test.sqlite3"),
                                         "SILICOLAB_FRONTEND_DIST": str(root / "ui")}):
                self.assertEqual(paths.browser_database(), root / "test.sqlite3")
                self.assertEqual(paths.frontend_directory(), (root / "ui").resolve())

    def test_frozen_frontend_uses_bundle_resources(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            with patch.object(paths.sys, "frozen", True, create=True), \
                    patch.object(paths.sys, "_MEIPASS", directory, create=True):
                self.assertEqual(paths.frontend_directory(), Path(directory) / "frontend/dist")

    def test_standalone_installed_package_uses_writable_application_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            with patch.object(paths, "project_directory", return_value=root / "site-packages"), \
                    patch.object(paths, "application_directory", return_value=root / "app-data"):
                self.assertEqual(paths.browser_database(), root / "app-data/silicolab.sqlite3")

    def test_local_engine_and_mapping_are_product_resources(self):
        self.assertEqual(local.MODEL.parent.name, "resources")
        self.assertNotIn("research", Path(local.__file__).parts)
        self.assertNotIn("research", local.MODEL.parts)
        self.assertEqual(json.loads(local.MODEL.read_text())["mapping"], local.load_mapping())
        info = engine_metadata("local")
        self.assertEqual(len(info["model_sha256"]), 64)
        self.assertEqual(len(info["code_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
