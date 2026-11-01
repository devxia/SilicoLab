"""Test-only owner of an actual installed app with a minimal child environment."""
import json
import os
from pathlib import Path
import subprocess
import time
import httpx
from contextlib import contextmanager
from silicolab.desktop_lifecycle import service_info


def wait(predicate,seconds=25):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.04)
    raise AssertionError('Packaged application condition timed out')


def windows(pid):
    from Quartz import CGWindowListCopyWindowInfo,kCGWindowListOptionOnScreenOnly,kCGNullWindowID
    return [dict(w) for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly,kCGNullWindowID) if w.get('kCGWindowOwnerPID')==pid and w.get('kCGWindowLayer')==0]


@contextmanager
def hidden_builder(builder):
    builder=Path(builder).resolve();hidden=builder.with_name(builder.name+'-temporarily-unavailable')
    if hidden.exists():raise ValueError('Temporary builder path already exists')
    builder.rename(hidden)
    try:yield
    finally:
        if hidden.exists():hidden.rename(builder)


class PackagedApp:
    def __init__(self,app,directory):
        self.app=Path(app).resolve();self.executable=self.app/'Contents/MacOS/SilicoLab';self.directory=Path(directory).resolve();self.directory.mkdir()
        self.env={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','SILICOLAB_APP_DATA':str(self.directory),
                  'SILICOLAB_NODE':'/unavailable/developer/node','SILICOLAB_RUNTIME':'/unavailable/developer/runtime','SILICOLAB_FRONTEND_DIST':'/unavailable/frontend'}
        self.log=(self.directory/'packaged.log').open('ab');self.processes=[];self.client=httpx.Client(timeout=30,trust_env=False);self.info=None
    def launch(self):
        start=time.monotonic();process=subprocess.Popen([str(self.executable),'--isolated-resources'],cwd='/tmp',env=self.env,stdout=self.log,stderr=self.log);self.processes.append(process)
        self.info=wait(lambda:service_info(self.directory) if process.poll() is None else None)
        wait(lambda:windows(process.pid))
        self.startup_seconds=time.monotonic()-start
        return process
    def api(self,path,body=None,method=None):
        response=self.client.request(method or ('POST' if body is not None else 'GET'),self.info['origin']+'/api/workbench'+path,json=body)
        assert response.status_code<400,(response.status_code,response.text[:1000]);return response.json()
    def raw(self,path,body=None,method=None):
        return self.client.request(method or ('POST' if body is not None else 'GET'),self.info['origin']+path,json=body)
    def command(self,*args):
        return subprocess.run([str(self.executable),*args],cwd='/tmp',env=self.env,stdout=self.log,stderr=self.log,timeout=30)
    def task(self,url,identity,status='answered'):
        return wait(lambda:next((t for t in self.api(url)['tasks'] if t['id']==identity and t['status']==status),None),45)
    def quit(self):
        result=self.command('--quit');assert result.returncode==0
        for process in self.processes:
            process.wait(timeout=15);assert not windows(process.pid)
        assert service_info(self.directory) is None
    def close(self):
        try:
            if self.processes:self.quit()
        finally:
            for process in self.processes:
                if process.poll() is None:process.kill();process.wait(timeout=5)
            self.log.close();self.client.close()
