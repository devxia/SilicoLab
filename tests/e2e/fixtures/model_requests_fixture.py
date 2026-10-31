"""Held artificial first request and transient second protocol for switching UI."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import uvicorn
from fastapi import FastAPI
from silicolab.server import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend' / 'tests'))
from test_model_configuration import FakeModelEndpoint, MemorySecrets

if __name__ == '__main__':
    os.environ['SILICOLAB_SCIENCE_REMOTE'] = 'http://127.0.0.1:9/toDnaAjaxCodon'
    with tempfile.TemporaryDirectory(prefix='silicolab-request-ui-') as directory, ExitStack() as stack:
        first = stack.enter_context(FakeModelEndpoint('openai-responses', 'artificial-a', 'hold'))
        second = stack.enter_context(FakeModelEndpoint('anthropic-messages', 'artificial-b', ['rate_limit', 'normal']))
        def no_science(_payload):
            raise RuntimeError('No real science in model requests fixture')
        workbench = create_app(Path(directory) / 'app.sqlite3', optimizer=no_science, delay=0, credential_store=MemorySecrets(), skill_roots=[])
        app = FastAPI(lifespan=workbench.router.lifespan_context)
        @app.get('/__test/model-requests')
        def info():
            return {'first': {'url': first.url, 'requests': len(first.requests)}, 'second': {'url': second.url, 'requests': len(second.requests)}}
        @app.post('/__test/release-first')
        def release():
            first.release.set()
            return {'released': True}
        app.mount('/', workbench)
        uvicorn.run(app, host='127.0.0.1', port=8767, log_level='warning')
