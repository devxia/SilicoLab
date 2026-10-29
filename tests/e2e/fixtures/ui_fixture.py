"""Isolated UI test server. Deterministic fake upstream, never used by the launcher."""
import os
from pathlib import Path
import sys
import tempfile
import time

from silicolab.server import create_app

counts = {}
def fake_upstream(payload):
    time.sleep(0.8)
    name = payload['fileName']
    counts[name] = counts.get(name, 0) + 1
    if name == 'fail-once' and counts[name] == 1:
        return {'success': '0', 'msg': 'Test constraint warning'}
    return {'success': '1', 'seq': ''.join({'M':'ATG','K':'AAG','*':'TAA'}[aa] for aa in payload['sequence']), 'log_id': 'ui-fixture'}

# Always create a fresh, disposable DB. No production history is read or modified.
with tempfile.TemporaryDirectory(prefix='codon-ui-fixture-') as directory:
    app = create_app(Path(directory) / 'fixture.sqlite3', optimizer=fake_upstream, delay=0.1)
    if __name__ == '__main__':
        import uvicorn
        uvicorn.run(app, host='127.0.0.1', port=8766)
