import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('webview'), 'Run native bridge checks in .desktop-venv')
class DesktopBridgeSurfaceTests(unittest.TestCase):
    def test_js_bridge_exposes_only_intended_methods_and_no_internal_objects(self):
        import tempfile
        from pathlib import Path
        from silicolab.desktop import DesktopBridge
        with tempfile.TemporaryDirectory() as directory:
            bridge = DesktopBridge(Path(directory))
            exposed = [name for name in dir(bridge) if not name.startswith('_')]
            self.assertEqual(sorted(exposed), ['bootstrap', 'choose_project_directory', 'copy_text', 'open_export_directory', 'save_draft', 'save_export'])
            self.assertTrue(all(callable(getattr(bridge, name)) for name in exposed))

    def test_local_hash_routes_remain_trusted_for_directory_selection(self):
        import tempfile
        from pathlib import Path
        from silicolab.desktop import DesktopBridge
        class LocalWindow:
            url = 'http://127.0.0.1:8765/#manual'
            def get_current_url(self):
                return self.url
            def create_file_dialog(self, *_args, **_kwargs):
                return [str(Path(directory).resolve())]
        with tempfile.TemporaryDirectory() as directory:
            bridge = DesktopBridge(Path(directory))
            bridge._origin = 'http://127.0.0.1:8765'
            bridge._window = LocalWindow()
            self.assertEqual(bridge.choose_project_directory(), str(Path(directory).resolve()))
            bridge._window.url = 'https://external.invalid/#manual'
            with self.assertRaises(ValueError):
                bridge.choose_project_directory()


if __name__ == '__main__':
    unittest.main()
