"""Independent real background process, stable service identity, explicit quit."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from urllib.request import Request, urlopen

from silicolab.desktop_lifecycle import ensure_service, service_info, stop_service


class DesktopServiceTests(unittest.TestCase):
    def test_lost_background_reaps_project_host_and_reconnect_lists_recovery_without_new_task(self):
        import signal
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = ensure_service(root, isolated_resources=True)
            def api(origin, path, body=None):
                request = Request(origin + '/api/workbench' + path, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
                with urlopen(request, timeout=10) as response: return json.load(response)
            project_path = root / 'project'; project_path.mkdir()
            try:
                project = api(info['origin'], '/projects', {'path': str(project_path)})
                url = '/projects/' + project['id']
                chat = api(info['origin'], url + '/conversations', {'title': 'crash recovery'})['id']
                task = api(info['origin'], url + '/tasks', {'conversationId': chat, 'requestId': 'background-crash', 'goal': 'ARTIFICIAL_LONG_TEXT_' * 100, 'authorizedTools': ['synthetic_count']})
                node = project['runtimePid']
                os.kill(info['pid'], signal.SIGKILL)
                for _ in range(150):
                    try: os.kill(node, 0)
                    except ProcessLookupError: break
                    time.sleep(0.03)
                else: self.fail('project Node survived lost background stdin owner')
                self.assertIsNone(service_info(root))
                recovered = ensure_service(root, isolated_resources=True)
                self.assertNotEqual(recovered['serviceId'], info['serviceId'])
                opened = api(recovered['origin'], '/projects/open', {'path': str(project_path)})
                self.assertEqual(opened['id'], project['id'])
                self.assertEqual(opened['tasks'][0]['id'], task['id'])
                self.assertEqual(opened['tasks'][0]['status'], 'paused')
                count = opened['modelRequests']
                time.sleep(0.2)
                self.assertEqual(api(recovered['origin'], url)['modelRequests'], count)
            finally:
                stop_service(root)

    def test_unresponsive_background_cannot_be_mistaken_for_successful_quit(self):
        import signal
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = ensure_service(root, isolated_resources=True)
            try:
                os.kill(info['pid'], signal.SIGSTOP)
                with self.assertRaisesRegex(ValueError, '未确认|无响应'):
                    stop_service(root)
                os.kill(info['pid'], 0)
            finally:
                os.kill(info['pid'], signal.SIGCONT)
                stop_service(root)

    def test_repeated_attach_is_same_background_and_rejects_unauthorized_quit(self):
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = ensure_service(root, isolated_resources=True)
            try:
                self.assertNotEqual(info['pid'], os.getpid())
                self.assertEqual(ensure_service(root, isolated_resources=True)['serviceId'], info['serviceId'])
                with urlopen(info['origin'] + '/api/health') as response:
                    self.assertEqual(json.load(response)['pid'], info['pid'])
                with urlopen(info['origin'] + '/api/desktop/status') as response:
                    self.assertIs(json.load(response).get('isolatedResources'),True)
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(info['origin'] + '/api/desktop/quit', data=b'{}', headers={'Authorization': 'Bearer artificial-wrong'}))
                self.assertEqual(denied.exception.code, 403)
                self.assertEqual(service_info(root)['serviceId'], info['serviceId'])
                self.assertEqual((root / 'background.json').stat().st_mode & 0o777, 0o600)
            finally:
                stop_service(root)
                for _ in range(100):
                    if service_info(root) is None: break
                    time.sleep(0.05)
                self.assertIsNone(service_info(root))


if __name__ == '__main__':
    unittest.main()
