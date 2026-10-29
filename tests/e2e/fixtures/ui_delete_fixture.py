"""Deletion browser fixture: temporary SQLite; controlled async work; no upstream IO."""
import asyncio
from pathlib import Path
import sys
import tempfile

from fastapi.responses import JSONResponse
from silicolab.features.codon.engines import engine_metadata
from silicolab.server import create_app

if __name__ == '__main__':
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='codon-delete-ui-') as directory:
        releases = {}

        async def controlled_optimizer(payload):
            key = payload['fileName']
            event = releases.setdefault(key, asyncio.Event())
            await event.wait()
            return {'success': '1', 'seq': 'ATGAAGTAA', 'log_id': 'isolated-fixture'}

        app = create_app(Path(directory) / 'db.sqlite3', optimizer=controlled_optimizer, delay=0)

        @app.middleware('http')
        async def controls(request, call_next):
            if request.url.path == '/test/requeue':
                job_id = request.query_params['id']
                def requeue(job):
                    job.update(engine='remote', engine_info=engine_metadata('remote'), status='queued')
                    for record in job['records']:
                        record.update(status='pending', dna=None, checks=None, response=None, error=None)
                        releases[record['name']] = asyncio.Event()
                app.state.store.mutate(job_id, requeue)
                app.state.worker.wake.set()
                return JSONResponse({'ok': True})
            if request.url.path == '/test/release':
                for event in releases.values():
                    event.set()
                return JSONResponse({'ok': True})
            return await call_next(request)

        uvicorn.run(app, host='127.0.0.1', port=8766)
