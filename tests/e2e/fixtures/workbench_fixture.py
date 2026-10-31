"""Temporary local workbench server; rejects all actual science network calls."""
import os
from pathlib import Path
import tempfile
import uvicorn
from silicolab.server import create_app

if __name__ == '__main__':
    # Subprocess science transport must also stay off the real service.
    os.environ['SILICOLAB_SCIENCE_REMOTE'] = 'http://127.0.0.1:9/toDnaAjaxCodon'
    with tempfile.TemporaryDirectory(prefix='silicolab-workbench-server-') as directory:
        def no_remote(_payload):
            raise RuntimeError('External scientific calls are forbidden in this fixture')
        app = create_app(Path(directory) / 'app.sqlite3', optimizer=no_remote, delay=0, skill_roots=[])
        uvicorn.run(app, host='127.0.0.1', port=8767, log_level='warning')
