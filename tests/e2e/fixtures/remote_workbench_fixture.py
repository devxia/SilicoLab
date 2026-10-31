"""Artificial ProteinFactory HTTP endpoint + workbench; never uses the real service."""
import os
from pathlib import Path
import sys
import tempfile
import uvicorn
from fastapi import FastAPI
from silicolab.server import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend' / 'tests'))
from test_workbench_remote import RemoteEndpoint

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='silicolab-remote-ui-') as directory, RemoteEndpoint(['normal', 'accepted_then_drop', 'normal']) as remote:
        os.environ['SILICOLAB_SCIENCE_REMOTE'] = remote.url
        def no_legacy_remote(_payload):
            raise RuntimeError('Legacy science jobs forbidden in this fixture')
        workbench = create_app(Path(directory) / 'app.sqlite3', optimizer=no_legacy_remote, delay=0, skill_roots=[], mcp_roots=[])
        app = FastAPI(lifespan=workbench.router.lifespan_context)
        @app.get('/__test/science-requests')
        def requests():
            return {'requests': remote.requests}
        app.mount('/', workbench)
        uvicorn.run(app, host='127.0.0.1', port=8767, log_level='warning')
