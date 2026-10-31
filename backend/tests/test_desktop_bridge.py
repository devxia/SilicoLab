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
            self.assertEqual(sorted(exposed), ['bootstrap', 'choose_project_directory', 'copy_text', 'desktop_status', 'open_export_directory', 'quit_application', 'reconnect_background', 'save_draft', 'save_export', 'save_selection'])
            self.assertTrue(all(callable(getattr(bridge, name)) for name in exposed))

    def test_native_selection_is_origin_independent_and_unconfirmed_quit_does_not_close(self):
        import tempfile
        import uuid
        from pathlib import Path
        from unittest.mock import patch
        from silicolab.desktop import DesktopBridge
        class Window:
            destroyed = False
            def get_current_url(self): return 'http://127.0.0.1:45678'
            def create_confirmation_dialog(self, *_): return True
            def destroy(self): self.destroyed = True
        with tempfile.TemporaryDirectory() as directory:
            bridge = DesktopBridge(Path(directory)); bridge._origin = 'http://127.0.0.1:45678'; bridge._window = Window()
            selection = {'projectId': str(uuid.uuid4()), 'conversationId': '47'}
            self.assertTrue(bridge.save_selection(selection))
            self.assertEqual(bridge.bootstrap()['selection'], selection)
            reattached = DesktopBridge(Path(directory)); reattached._origin = 'http://127.0.0.1:45679'; reattached._window = Window()
            reattached._window.get_current_url = lambda: 'http://127.0.0.1:45679'
            self.assertEqual(reattached.bootstrap()['selection'], selection)
            self.assertEqual((Path(directory) / 'workbench-selection.json').stat().st_mode & 0o777, 0o600)
            with patch('silicolab.desktop.stop_service', side_effect=ValueError('后台无响应，未确认完全退出')):
                with self.assertRaises(ValueError): bridge.quit_application()
            self.assertFalse(bridge._window.destroyed)
            with self.assertRaises(ValueError): bridge.save_selection({'projectId': selection['projectId'], 'conversationId': '47', 'apiKey': 'artificial-key'})

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
