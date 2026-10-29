"""Measure an actual frozen .app using isolated data; no test endpoints or network jobs."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import Quartz
from AppKit import NSRunningApplication


def rss(pid):
    output = subprocess.check_output(['ps', '-axo', 'pid=,rss=,comm='], text=True)
    rows = {}
    for line in output.splitlines():
        values = line.strip().split(None, 2)
        if len(values) == 3:
            rows[int(values[0])] = (int(values[1]) / 1024, values[2])
    return rows


def has_window(pid):
    return any(row.get('kCGWindowOwnerPID') == pid and row.get('kCGWindowBounds', {}).get('Width', 0) >= 900
               for row in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    measurements = []
    for index in range(args.runs):
        with tempfile.TemporaryDirectory(prefix='codon-frozen-perf-') as directory:
            data = Path(directory)
            env = dict(os.environ, SILICOLAB_APP_DATA=directory)
            before = set(rss(os.getpid()))
            start = time.perf_counter()
            with (data / 'launch.log').open('w') as log:
                process = subprocess.Popen([str(args.app.resolve() / 'Contents/MacOS/SilicoLab')], cwd='/tmp', env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                window_at, api_at = None, None
                try:
                    while time.perf_counter() - start < 20:
                        if process.poll() is not None:
                            raise RuntimeError((data / 'launch.log').read_text())
                        if window_at is None and has_window(process.pid):
                            window_at = time.perf_counter() - start
                        preferences = data / 'desktop.json'
                        if api_at is None and preferences.exists():
                            port = json.loads(preferences.read_text())['port']
                            try:
                                with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=.1) as response:
                                    if response.status == 200:
                                        api_at = time.perf_counter() - start
                            except OSError:
                                pass
                        if window_at is not None and api_at is not None:
                            break
                        time.sleep(.05)
                    if window_at is None or api_at is None:
                        raise RuntimeError('Window/API did not become ready')
                    time.sleep(2)
                    rows = rss(process.pid)
                    main_rss = rows[process.pid][0]
                    webkit_rss = sum(value[0] for pid, value in rows.items() if pid not in before and 'WebKit' in value[1])
                    closing = time.perf_counter()
                    NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid).terminate()
                    process.wait(timeout=10)
                    shutdown = time.perf_counter() - closing
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                result = {'window_seconds': window_at, 'api_seconds': api_at, 'main_rss_mib': main_rss,
                          'webkit_rss_mib': webkit_rss, 'terminate_seconds': shutdown}
                measurements.append(result)
                print(json.dumps({'run': index + 1, **{k: round(v, 3) for k, v in result.items()}}), flush=True)
    medians = {key: statistics.median(row[key] for row in measurements) for key in measurements[0]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'app': str(args.app), 'method': 'actual frozen app, clean isolated DB, sequential launches, OS visible window and API; NSApplication terminate; RSS not footprint', 'medians': medians, 'runs': measurements}, indent=2))
    print('Medians', medians)


if __name__ == '__main__':
    main()
