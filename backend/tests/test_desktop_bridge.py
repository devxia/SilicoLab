import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('webview'), 'Run native bridge checks in .desktop-venv')
class DesktopBridgeSurfaceTests(unittest.TestCase):
    def test_js_bridge_exposes_only_five_intended_methods_and_no_internal_objects(self):
        import tempfile
        from pathlib import Path
        from silicolab.desktop import DesktopBridge
        with tempfile.TemporaryDirectory() as directory:
            bridge = DesktopBridge(Path(directory))
            exposed = [name for name in dir(bridge) if not name.startswith('_')]
            self.assertEqual(sorted(exposed), ['bootstrap', 'copy_text', 'open_export_directory', 'save_draft', 'save_export'])
            self.assertTrue(all(callable(getattr(bridge, name)) for name in exposed))


if __name__ == '__main__':
    unittest.main()
