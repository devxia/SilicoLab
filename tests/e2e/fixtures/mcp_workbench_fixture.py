"""Artificial HTTP + restricted stdio config; discovery never starts either."""
import json
from pathlib import Path
import sys
import tempfile
import uvicorn
from fastapi import FastAPI
from silicolab.server import create_app
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'backend/tests'))
from test_mcp_resources import HttpMcp,SERVER

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='silicolab-mcp-ui-') as directory,HttpMcp() as endpoint:
        root=Path(directory);project=root/'project';project.mkdir()
        (project/'server.py').write_text(SERVER)
        (project/'.mcp.json').write_text(json.dumps({'mcpServers':{'local':{'type':'stdio','command':'silicolab-restricted-python','args':['server.py']},'remote':{'type':'http','url':endpoint.url},'unsupported':{'type':'stdio','command':'/bin/sh','args':['never-execute']}}}))
        app_workbench=create_app(root/'app.sqlite3',skill_roots=[],mcp_roots=[],delay=0)
        app=FastAPI(lifespan=app_workbench.router.lifespan_context)
        @app.get('/__test/mcp-fixture')
        def info():return {'path':str(project),'requests':len(endpoint.messages)}
        app.mount('/',app_workbench)
        uvicorn.run(app,host='127.0.0.1',port=8767,log_level='warning')
