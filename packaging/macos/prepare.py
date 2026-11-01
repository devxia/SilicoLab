"""Prepare pinned public runtime resources; no application/user data is collected."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
STAGE=ROOT/'build/bundled-runtime'


def prepare():
    lock=json.loads((ROOT/'packaging/macos/runtime-lock.json').read_text())
    if STAGE.exists():raise ValueError('Refusing to overwrite bundled-runtime stage; use a clean source checkout')
    STAGE.mkdir(parents=True)
    node=lock['node'];archive=STAGE/'node.tar.gz'
    with urllib.request.urlopen(node['url'],timeout=60) as response,archive.open('xb') as out:shutil.copyfileobj(response,out)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=node['sha256']:raise ValueError('Pinned Node archive hash mismatch')
    with tarfile.open(archive) as source:source.extractall(STAGE/'node-source',filter='data')
    node_source=STAGE/'node-source'/f'node-v{node["version"]}-{node["architecture"]}'
    runtime=STAGE/'runtime';runtime.mkdir()
    for name in ('package.json','package-lock.json'):shutil.copy2(ROOT/'runtime'/name,runtime/name)
    shutil.copytree(ROOT/'runtime/src',runtime/'src')
    subprocess.run(['npm','ci','--omit=dev','--no-audit','--no-fund'],cwd=runtime,check=True)
    (runtime/'bin').mkdir();shutil.copy2(node_source/'bin/node',runtime/'bin/node');shutil.copy2(node_source/'LICENSE',runtime/'NODE-LICENSE')
    actual=subprocess.check_output([str(runtime/'bin/node'),'--version'],text=True).strip()
    if actual!='v'+node['version']:raise ValueError('Bundled Node version mismatch')
    for folder in ('analysis','notifications'): (STAGE/folder).mkdir()
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/python-runtime/build.py'),'--output',str(STAGE/'analysis/PythonBoundaryProbe.app')],check=True,cwd=ROOT)
    subprocess.run([sys.executable,'-B',str(ROOT/'tools/macos-notifications/build.py'),'--output',str(STAGE/'notifications/SilicoLabNotifications.app')],check=True,cwd=ROOT)
    backend=STAGE/'backend-src/silicolab';backend.mkdir(parents=True)
    for path in sorted((ROOT/'backend/src/silicolab').rglob('*')):
        if path.is_file() and path.suffix in ('.py','.json','.xlsx') and '__pycache__' not in path.parts:
            target=backend/path.relative_to(ROOT/'backend/src/silicolab');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    (STAGE/'tools/python-runtime').mkdir(parents=True)
    shutil.copy2(ROOT/'tools/python-runtime/runtime-lock.json',STAGE/'tools/python-runtime/runtime-lock.json')
    print('Prepared pinned Node, production dependencies, independent Python, notifications and public source identities.')


if __name__=='__main__':prepare()
