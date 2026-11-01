"""Create the build venv from pinned public CPython, never the operator's Python library."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
import shutil

ROOT=Path(__file__).resolve().parents[2]


def bootstrap():
    if sys.version_info<(3,12):raise RuntimeError('Build bootstrap requires Python 3.12 or newer; no files downloaded')
    lock=json.loads((ROOT/'tools/python-runtime/runtime-lock.json').read_text())['python']
    base=ROOT/'build/backend-python';python=base/'python/bin/python3.13';venv=ROOT/'.desktop-venv'
    if venv.exists():
        actual=subprocess.check_output([str(venv/'bin/python'),'-I','-B','-c','import sys;print(sys.base_prefix)'],text=True).strip()
        if Path(actual).resolve()!=(base/'python').resolve():raise ValueError('Existing desktop venv uses a developer Python; use a fresh source checkout')
        return
    cache=ROOT/'build/python-runtime-downloads';cache.mkdir(parents=True,exist_ok=True);archive=cache/lock['sha256']
    if not archive.exists():
        with urllib.request.urlopen(lock['url'],timeout=120) as response,archive.open('xb') as out:shutil.copyfileobj(response,out)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=lock['sha256']:raise ValueError('Public backend Python archive hash mismatch')
    if not python.exists():
        base.mkdir(parents=True,exist_ok=True)
        with tarfile.open(archive) as source:source.extractall(base,filter='data')
    subprocess.run([str(python),'-I','-B','-m','venv',str(venv)],check=True)
    actual=subprocess.check_output([str(venv/'bin/python'),'-I','-B','-c','import sys;print(sys.version.split()[0])'],text=True).strip()
    if actual!=lock['version']:raise ValueError('Build Python version mismatch')
    print('Build environment uses public CPython',actual)


if __name__=='__main__':bootstrap()
