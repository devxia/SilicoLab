"""UI model settings with artificial sentinel keys and two loopback protocol servers."""
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
    with tempfile.TemporaryDirectory(prefix='silicolab-model-ui-') as directory, ExitStack() as stack:
        endpoints = {protocol: stack.enter_context(FakeModelEndpoint(protocol, 'artificial-ui-key-' + protocol)) for protocol in ('openai-responses', 'anthropic-messages')}
        def no_science(_payload):
            raise RuntimeError('No science calls in model UI fixture')
        workbench = create_app(Path(directory) / 'app.sqlite3', optimizer=no_science, delay=0, credential_store=MemorySecrets())
        app = FastAPI(lifespan=workbench.router.lifespan_context)
        @app.get('/__test/model-endpoints')
        def endpoint_info():
            return {p: {'url': e.url, 'requests': len(e.requests)} for p, e in endpoints.items()}
        app.mount('/', workbench)
        uvicorn.run(app, host='127.0.0.1', port=8767, log_level='warning')
