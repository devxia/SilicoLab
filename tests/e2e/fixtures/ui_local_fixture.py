"""Isolated browser-test service: every network attempt fails and is counted."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from silicolab.server import create_app

attempts = []
def blocked(*args, **kwargs):
    attempts.append(str(args[0]) if args else 'remote optimizer')
    raise AssertionError('External network calls are forbidden in this test')

if __name__ == '__main__':
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='codon-local-ui-') as directory, \
            patch('silicolab.features.codon.client.request_json', side_effect=blocked), \
            patch('silicolab.features.codon.client.list_species', side_effect=blocked):
        app = create_app(Path(directory) / 'db.sqlite3', optimizer=blocked, delay=0)

        @app.middleware('http')
        async def stats(request, call_next):
            if request.url.path == '/test/network-attempts':
                from fastapi.responses import JSONResponse
                return JSONResponse({'attempts': attempts})
            return await call_next(request)

        uvicorn.run(app, host='127.0.0.1', port=8766)
