"""Synthetic history-cost benchmark (no remote requests or user DB)."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend' / 'tests'))
from fastapi.testclient import TestClient
from silicolab.server import create_app
from test_performance import synthetic_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(Path(directory) / 'db.sqlite3')
        # ~35 MB full history, with remote raw data repeated in each attempt.
        for index in range(80):
            job = synthetic_job(index)
            record = job['records'][0]
            record['attempts'] = [{'response': record['response']}] * 3
            app.state.store.save(job)
        timings = []
        with TestClient(app) as client:
            for _ in range(5):
                tracemalloc.start()
                started = time.perf_counter()
                response = client.get('/api/jobs')
                assert response.status_code == 200
                elapsed = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                timings.append({'seconds': elapsed, 'peak_python_mib': peak / 1024 ** 2, 'response_bytes': len(response.content)})
            small = client.get('/api/jobs/job-1?compact=true')
            full = client.get('/api/jobs/job-1')
        result = {'jobs': 80, 'database_mib': app.state.store.path.stat().st_size / 1024 ** 2,
                  'median_seconds': statistics.median(row['seconds'] for row in timings),
                  'median_peak_python_mib': statistics.median(row['peak_python_mib'] for row in timings),
                  'compact_detail_bytes': len(small.content), 'full_detail_bytes': len(full.content), 'runs': timings}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2))
        print(json.dumps({key: value for key, value in result.items() if key != 'runs'}))


if __name__ == '__main__':
    main()
