"""Window-independent local service owner; native UI processes only attach."""
import argparse
import fcntl
import json
import os
import secrets
import socket
import threading
import uuid

from fastapi import FastAPI, HTTPException, Request
import uvicorn

from silicolab.branding import DATABASE_FILENAME, SERVICE_ID
from silicolab.desktop_lifecycle import atomic_json
from silicolab.paths import application_directory
from silicolab.server import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-resources', action='store_true')
    args = parser.parse_args(argv)
    directory = application_directory()
    lease = (directory / 'background.lock').open('a+')
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lease.close()
        return 0
    identity, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128); listener.setblocking(False)
    port = listener.getsockname()[1]
    workbench = create_app(directory / DATABASE_FILENAME, skill_roots=[] if args.isolated_resources else None, mcp_roots=[] if args.isolated_resources else None)
    app = FastAPI(lifespan=workbench.router.lifespan_context)
    server = uvicorn.Server(uvicorn.Config(app, loop='asyncio', http='h11', ws='none', log_config=None, access_log=False, timeout_graceful_shutdown=2))
    state = {'app': SERVICE_ID, 'pid': os.getpid(), 'serviceId': identity, 'port': port}

    @app.get('/api/desktop/status')
    def status():
        return dict(state, lifecycle='independent-background', windowClose='continues', quit='explicit')

    @app.post('/api/desktop/quit')
    def quit_application(request: Request):
        import hmac
        if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
            raise HTTPException(403, '不允许此来源退出应用')
        def stop():
            app.state.loop.call_soon_threadsafe(workbench.state.stopping.set)
            server.should_exit = True
        threading.Timer(0.05, stop).start()
        return {'stopping': True}

    from silicolab.decision_notifications import DecisionNotifications
    notifications=DecisionNotifications(workbench.state.workbench,directory)

    workbench.state.workbench.notifications=notifications

    app.mount('/', workbench)
    descriptor = directory / 'background.json'
    atomic_json(descriptor, dict(state, token=token))
    try:
        notifications.start()
        server.run(sockets=[listener])
    finally:
        notifications.close()
        workbench.state.workbench.close()
        listener.close()
        try:
            if json.loads(descriptor.read_text()).get('serviceId') == identity: descriptor.unlink()
        except (OSError, ValueError):
            pass
        fcntl.flock(lease, fcntl.LOCK_UN); lease.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
