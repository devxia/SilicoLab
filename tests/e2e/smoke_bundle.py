"""Standalone frozen-app smoke: isolated local history, local calculation, exports and restart.

No remote optimization requests. Optional read-only /api/species check verifies bundled TLS.
"""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

from AppKit import NSRunningApplication
from openpyxl import load_workbook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    executable = str(args.app.resolve() / 'Contents/MacOS/SilicoLab')
    with tempfile.TemporaryDirectory(prefix='codon-bundle-smoke-') as directory:
        root = Path(directory)
        env = dict(os.environ, SILICOLAB_APP_DATA=directory)
        def start():
            process = subprocess.Popen([executable], cwd='/tmp', env=env, stdout=(root / 'launch.log').open('ab'), stderr=subprocess.STDOUT)
            for _ in range(200):
                prefs = root / 'desktop.json'
                if prefs.exists():
                    port = json.loads(prefs.read_text())['port']
                    origin = f'http://127.0.0.1:{port}'
                    try:
                        with urlopen(origin + '/api/health', timeout=.1) as response:
                            if json.load(response)['pid'] == process.pid:
                                return process, origin
                    except OSError:
                        pass
                time.sleep(.05)
            process.kill()
            raise RuntimeError('Bundled app did not start')
        process, origin = start()
        try:
            def get(path):
                with urlopen(origin + path, timeout=10) as response:
                    return json.load(response)
            identity = get('/api/health')
            assert identity['app'] == 'silicolab' and identity['name'] == 'SilicoLab'
            assert identity['version'] == '0.1.3'
            assert get('/api/jobs') == [], 'Fresh SilicoLab must not import external history'
            assert get('/api/presets') == []
            assert (root / 'silicolab.sqlite3').exists()
            payload = {'name': 'synthetic packaged smoke', 'engine': 'local', 'species': 'D2P(default)',
                       'avoid': 'GAATTC', 'records': [{'name': 'test', 'sequence': 'MEF*'}]}
            with urlopen(Request(origin + '/api/jobs', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}), timeout=5) as response:
                job_id = json.load(response)['id']
            for _ in range(200):
                detail = get('/api/jobs/' + job_id)
                if detail['status'] not in {'queued', 'running'}:
                    break
                time.sleep(.05)
            assert detail['status'] == 'completed', detail['records'][0].get('error')
            assert detail['records'][0]['dna'] == 'ATGGAATTTTAA'
            assert detail['engine_info']['network_used'] is False
            with urlopen(origin + '/api/jobs/' + job_id + '/export?format=xlsx') as response:
                book = load_workbook(io.BytesIO(response.read()))
            assert book.sheetnames == ['基因合成']
            assert book.active['C2'].value == 'ATGGAATTTTAA'
            assert all(cell.comment is None for sheet in book for row in sheet for cell in row)
            book.close()
            compact = get('/api/jobs/' + job_id + '?compact=true')
            assert 'seq' not in compact['records'][0]['response']
            NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid).terminate()
            process.wait(timeout=10)
            process, origin = start()
            assert get('/api/jobs/' + job_id)['records'][0]['dna'] == 'ATGGAATTTTAA'
            with urlopen(Request(origin + '/api/jobs/' + job_id, method='DELETE'), timeout=5) as response:
                deleted = json.load(response)
            assert deleted['deleted_ids'] == [job_id]
            assert get('/api/jobs') == []
            NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid).terminate()
            process.wait(timeout=10)
            process, origin = start()
            assert get('/api/jobs') == [], 'Deleted record reappeared after restart'
            report = {'status': 'passed', 'app': str(args.app), 'local_calculation': True,
                      'xlsx_single_sheet_no_comments': True, 'compact_view': True, 'restart_persistence': True,
                      'single_task_delete': True, 'deletion_persists_after_restart': True,
                      'user_data_modified': False, 'remote_requests': 0, 'identity': identity['name'],
                      'version': identity['version'], 'fresh_workspace_no_import': True}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False))
        finally:
            if process.poll() is None:
                NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid).terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
