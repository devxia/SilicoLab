"""Real Cocoa close/reopen; independent background/task identity and no duplicate owner.

Run with .desktop-venv; artificial text, empty skill roots, no actual provider/science.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID
from silicolab.desktop_lifecycle import ensure_service, gui_command, service_info, stop_service

OUT = Path('outputs/native/window-lifecycle')
OUT.mkdir(parents=True, exist_ok=True)


def wait(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        time.sleep(0.03)
    raise AssertionError('Native lifecycle condition timed out')


def windows(pid):
    return [dict(w) for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) if w.get('kCGWindowOwnerPID') == pid and w.get('kCGWindowLayer') == 0]


with tempfile.TemporaryDirectory(prefix='silicolab-native-window-') as directory:
    root = Path(directory)
    env = {**os.environ, 'SILICOLAB_APP_DATA': directory, 'SILICOLAB_NATIVE_EVIDENCE': str(root / 'native-ui-evidence.json')}
    processes = []
    log = (root / 'gui.log').open('ab')
    command = [str(Path('.desktop-venv/bin/python').absolute()), '-B', str(Path('tests/e2e/fixtures/native_window_driver.py').absolute())]
    def launch(prepare=False):
        process = subprocess.Popen(command, cwd='/tmp', env=dict(env, SILICOLAB_NATIVE_PREPARE_SELECTION='1' if prepare else '0'), stdout=log, stderr=log)
        processes.append(process)
        wait(lambda: (root / 'gui-session.json').exists() and process.poll() is None)
        wait(lambda: windows(process.pid))
        return process
    try:
        background = ensure_service(root, isolated_resources=True)
        origin = background['origin']
        def api(path, payload=None, method='GET'):
            request = Request(origin + '/api/workbench' + path, data=json.dumps(payload).encode() if payload is not None else None, method=method, headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=10) as response: return json.load(response)
        project_path = root / 'project'; project_path.mkdir()
        project = api('/projects', {'path': str(project_path), 'name': 'native close evidence'}, 'POST')
        url = '/projects/' + project['id']
        api(url + '/conversations', {'title': 'decoy first conversation'}, 'POST')
        chat = api(url + '/conversations', {'title': 'same background task'}, 'POST')['id']
        env['SILICOLAB_NATIVE_TARGET_CHAT'] = chat
        first = launch(prepare=True)
        task = api(url + '/tasks', {'conversationId': chat, 'requestId': 'native-close', 'goal': 'ARTIFICIAL_NATIVE_BACKGROUND_TEXT', 'authorizedTools': ['synthetic_count']}, 'POST')
        first_ui = wait(lambda: json.loads((root / 'native-ui-evidence.json').read_text()) if (root / 'native-ui-evidence.json').exists() else None)
        assert first_ui['expected']['projectId'] == project['id']
        assert first_ui['expected']['conversationId'] == chat
        if (root / 'workbench-selection.json').exists():
            assert json.loads((root / 'workbench-selection.json').read_text()) == first_ui['expected']
        wait(lambda: api(url + f'/conversations/{chat}')['modelRequests'] >= 1)
        original_node = api(url)['runtimePid']
        closed_at = time.time()
        assert gui_command(root, 'close'), 'native window must acknowledge close'
        first.wait(timeout=15)
        assert windows(first.pid) == [], 'real Cocoa window survived'
        assert service_info(root)['serviceId'] == background['serviceId']
        done = wait(lambda: next((t for t in api(url)['tasks'] if t['id'] == task['id'] and t['status'] == 'answered'), None))
        from datetime import datetime
        assert datetime.fromisoformat(done['finishedAt'].replace('Z', '+00:00')).timestamp() > closed_at, 'task must actually finish after native close'
        assert len(done['toolExecutions']) == 1
        assert done['toolExecutions'][0]['result']['characters'] == len('ARTIFICIAL_NATIVE_BACKGROUND_TEXT')
        assert len(done['modelRequests']) == 2
        assert api(url)['runtimePid'] == original_node
        (root / 'native-ui-evidence.json').unlink(missing_ok=True)
        second = launch()
        second_ui = wait(lambda: json.loads((root / 'native-ui-evidence.json').read_text()) if (root / 'native-ui-evidence.json').exists() else None)
        assert second_ui['expected'] == first_ui['expected']
        assert 'same background task' in second_ui['heading']
        assert task['id'][:8] in second_ui['transcript']
        assert service_info(root)['serviceId'] == background['serviceId']
        assert json.loads((root / 'gui-session.json').read_text())['backgroundPid'] == background['pid']
        assert api(url)['tasks'][0]['id'] == task['id']
        assert api(url)['runtimePid'] == original_node
        # A duplicate normal application invocation focuses/attaches, never takes a second lease.
        duplicate = subprocess.Popen(command, cwd='/tmp', env=env, stdout=log, stderr=log)
        processes.append(duplicate)
        assert duplicate.wait(timeout=15) == 0
        assert json.loads((root / 'gui-session.json').read_text())['pid'] == second.pid
        assert service_info(root)['pid'] == background['pid']
        assert api(url)['tasks'][0]['toolExecutions'] == done['toolExecutions']
        assert len(api(url)['tasks'][0]['modelRequests']) == 2
        import signal
        os.kill(background['pid'], signal.SIGSTOP)
        try:
            refused_quit = subprocess.run([str(Path('.desktop-venv/bin/python').absolute()), '-B', '-m', 'silicolab.desktop', '--quit'], cwd='/tmp', env=env, stdout=log, stderr=log, timeout=15)
            assert refused_quit.returncode == 1, 'unresponsive leased background must not be reported exited'
            assert second.poll() is None and windows(second.pid), 'unconfirmed quit must preserve the real Cocoa window'
        finally:
            os.kill(background['pid'], signal.SIGCONT)
        wait(lambda: service_info(root))
        os.kill(background['pid'], signal.SIGKILL)
        wait(lambda: service_info(root) is None)
        lost_ui = wait(lambda: (state if '后台连接已丢失' in state.get('backend', '') else None) if (root / 'native-ui-evidence.json').exists() and (state := json.loads((root / 'native-ui-evidence.json').read_text())) else None)
        assert '未确认' in lost_ui['backend']
        assert gui_command(root, 'close')
        second.wait(timeout=15)
        (root / 'native-ui-evidence.json').unlink(missing_ok=True)
        third = launch()
        replacement = wait(lambda: service_info(root))
        assert replacement['serviceId'] != background['serviceId']
        reattached = wait(lambda: json.loads((root / 'native-ui-evidence.json').read_text()) if (root / 'native-ui-evidence.json').exists() else None)
        assert reattached['expected'] == first_ui['expected']
        assert 'same background task' in reattached['heading']
        assert json.loads((root / 'workbench-selection.json').read_text()) == first_ui['expected']
        with urlopen(replacement['origin'] + '/api/workbench' + url, timeout=10) as response:
            preserved = json.load(response)
        assert preserved['tasks'][0]['id'] == task['id']
        assert preserved['tasks'][0]['toolExecutions'] == done['toolExecutions']
        assert len(preserved['tasks'][0]['modelRequests']) == 2
        report = {'status': 'passed', 'native_windows_closed_not_dom_hidden': True, 'independent_service_pid': background['pid'], 'first_gui_pid': first.pid, 'reopened_gui_pid': second.pid,
                  'unresponsive_quit_preserves_native_window': True, 'background_loss_visible_in_native_ui': True, 'explicit_reopen_retains_history_after_service_loss': True, 'same_project_node_pid': original_node, 'same_service_identity': True, 'same_task_identity': True, 'native_wkwebview_attached_same_project_conversation': True, 'model_requests': 2, 'tool_executions': 1, 'duplicate_open_no_second_writer': True, 'artificial_data_only': True, 'task_finished_after_native_close': True, 'closed_at': closed_at}
        (OUT / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        if any(p.poll() not in (None, 0) for p in processes) or not (root / 'native-ui-evidence.json').exists():
            log.flush()
            for name in ('gui.log', 'background-launch.log', 'desktop.log'):
                if (root / name).exists(): print(name, (root / name).read_text(errors='replace')[-6000:])
        try: stop_service(root)
        except Exception: pass
        gui_command(root, 'close')
        for process in processes:
            if process.poll() is None:
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        log.close()
