"""Test-only background factory wired to an artificial, separately owned executor."""
import json
import os
from pathlib import Path
from urllib.request import urlopen
from silicolab import desktop_service

create=desktop_service.create_app
class IndependentExecutor:
    def __init__(self,url):self.url=url
    def info(self):
        with urlopen(self.url+'/info',timeout=3) as r:return json.load(r)
    def close(self):pass  # This fixture intentionally does not own the external process.
def application(*args,**kwargs):
    app=create(*args,**kwargs)
    info=json.loads(Path(os.environ['SILICOLAB_ARTIFICIAL_EXECUTOR']).read_text())
    app.state.workbench._simulated=IndependentExecutor(info['url'])
    return app

desktop_service.create_app=application
raise SystemExit(desktop_service.main(['--isolated-resources']))
