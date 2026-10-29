"""Repeatable native performance harness, isolated DB and synthetic benchmark inputs.

.desktop-venv/bin/python tools/benchmarks/perf_desktop.py --output outputs/perf-before.json --runs 3
Only --worker launches a GUI; it closes automatically after sampling. No network submissions.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def processes():
    output = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss=,comm='], text=True)
    result = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) == 4:
            result[int(parts[0])] = {'ppid': int(parts[1]), 'rss_kib': int(parts[2]), 'command': parts[3]}
    return result


def worker(output, directory):
    started = time.perf_counter()
    os.environ['SILICOLAB_APP_DATA'] = str(directory)
    baseline_processes = set(processes())
    from silicolab import desktop
    import threading
    metrics = {'import_seconds': time.perf_counter() - started}
    create_window = desktop.webview.create_window

    def patched_window(*args, **kwargs):
        window = create_window(*args, **kwargs)
        sampling_started = threading.Event()

        def shown():
            metrics['window_seconds'] = time.perf_counter() - started
        window.events.shown += shown

        def sample():
            try:
                for _ in range(60):
                    ready = window.evaluate_js("!!document.querySelector('#species-select') && !!window.pywebview?.api")
                    if ready:
                        break
                    time.sleep(.05)
                else:
                    raise RuntimeError('React/bridge did not become ready')
                metrics['ui_ready_seconds'] = time.perf_counter() - started
                # Keep SSE open to exercise the actual idle shutdown path.
                time.sleep(1.5)
                sampled = processes()
                attributed = {str(pid): info for pid, info in sampled.items()
                              if pid == os.getpid() or (pid not in baseline_processes and 'WebKit' in info['command'])}
                metrics['processes'] = attributed
                metrics['main_rss_mib'] = sampled[os.getpid()]['rss_kib'] / 1024
                metrics['webkit_rss_mib'] = sum(info['rss_kib'] for pid, info in attributed.items() if int(pid) != os.getpid()) / 1024
                metrics['main_threads'] = int(subprocess.check_output(['ps', '-M', '-p', str(os.getpid())], text=True).count('\n') - 1)
                metrics['close_requested_at'] = time.perf_counter() - started
                output.write_text(json.dumps(metrics))
                window.destroy()
            except Exception as exc:
                metrics['error'] = str(exc)
                output.write_text(json.dumps(metrics))
                window.destroy()
        def loaded():
            if not sampling_started.is_set():
                sampling_started.set()
                threading.Thread(target=sample, daemon=True).start()
        window.events.loaded += loaded
        return window

    desktop.webview.create_window = patched_window
    desktop.main()
    metrics['exit_seconds'] = time.perf_counter() - started
    metrics['close_seconds'] = metrics['exit_seconds'] - metrics['close_requested_at']
    output.write_text(json.dumps(metrics, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--assert-close-below', type=float)
    args = parser.parse_args()
    if args.worker:
        worker(args.output, args.directory)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for index in range(args.runs):
        with tempfile.TemporaryDirectory(prefix='codon-perf-') as directory:
            output = Path(directory) / 'metrics.json'
            started = time.perf_counter()
            process = subprocess.run([sys.executable, __file__, '--worker', '--output', str(output), '--directory', directory], cwd=ROOT, capture_output=True, text=True, timeout=35)
            if process.returncode != 0:
                raise RuntimeError(process.stderr)
            row = json.loads(output.read_text())
            row['wall_seconds'] = time.perf_counter() - started
            if row.get('error'):
                raise RuntimeError(row['error'])
            results.append(row)
            print(json.dumps({'run': index + 1, **{key: round(row[key], 3) for key in ['import_seconds', 'window_seconds', 'ui_ready_seconds', 'main_rss_mib', 'webkit_rss_mib', 'close_seconds']}}), flush=True)
    medians = {key: statistics.median(row[key] for row in results)
               for key in ['import_seconds', 'window_seconds', 'ui_ready_seconds', 'main_rss_mib', 'webkit_rss_mib', 'close_seconds']}
    args.output.write_text(json.dumps({'kind': 'source native Cocoa/WebKit; isolated clean DB; no remote calls; RSS not physical footprint', 'medians': medians, 'runs': results}, indent=2))
    print('Medians:', json.dumps(medians), flush=True)
    if args.assert_close_below is not None and medians['close_seconds'] >= args.assert_close_below:
        raise SystemExit(f"FAIL: median close {medians['close_seconds']:.3f}s >= {args.assert_close_below}s")


if __name__ == '__main__':
    main()
