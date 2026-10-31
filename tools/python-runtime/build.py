"""Build a relocatable, ad-hoc signed boundary-probe app from hash-pinned public inputs.

Downloads are a trusted build step, never a capability available to analysis code.
No runtime or artifact is committed; output is under ignored build/release directories.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(item, directory):
    target = directory / item['sha256']
    if not target.exists():
        with urlopen(item['url'], timeout=120) as response, target.open('xb') as output:
            shutil.copyfileobj(response, output)
    if digest(target) != item['sha256']:
        raise ValueError('Downloaded source hash does not match lock; build blocked')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'release/PythonBoundaryProbe.app')
    args = parser.parse_args()
    if os.uname().sysname != 'Darwin' or os.uname().machine != 'x86_64':
        raise ValueError('This pinned runtime is validated only for macOS x86_64')
    lock = json.loads((Path(__file__).with_name('runtime-lock.json')).read_text())
    cache = ROOT / 'build/python-runtime-downloads'; cache.mkdir(parents=True, exist_ok=True)
    app = args.output.absolute()
    if app.exists():
        raise ValueError('Output already exists; choose a fresh path, never overwrite an app')
    resources = app / 'Contents/Resources'; resources.mkdir(parents=True)
    archive = download(lock['python'], cache)
    with tarfile.open(archive, 'r:gz') as source:
        for member in source.getmembers():
            if not member.name.startswith('python/') or member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('Unsafe runtime archive path')
        source.extractall(resources, filter='data')
    runtime = resources / 'python'
    packages = runtime / 'lib/python3.13/site-packages'
    for item in lock['wheels']:
        wheel = download(item, cache)
        with zipfile.ZipFile(wheel) as source:
            for name in source.namelist():
                if name.startswith('/') or '..' in Path(name).parts: raise ValueError('Unsafe wheel path')
            source.extractall(packages)
    probe = resources / 'probe'
    shutil.copytree(ROOT / 'tools/python-probe', probe, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'backend/src/silicolab/restricted_python.py', probe / 'execution.py')
    (app / 'Contents/MacOS').mkdir()
    subprocess.run(['/usr/bin/clang', '-O2', str(Path(__file__).with_name('probe-launcher.c')), '-o', str(app / 'Contents/MacOS/PythonBoundaryProbe')], check=True)
    with (app / 'Contents/Info.plist').open('wb') as output:
        plistlib.dump({'CFBundleIdentifier': 'com.silicolab.PythonBoundaryProbe', 'CFBundleName': 'PythonBoundaryProbe',
                       'CFBundleExecutable': 'PythonBoundaryProbe', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1',
                       'LSMinimumSystemVersion': '13.0', 'LSUIElement': True}, output)
    # Sign each real Mach-O file; preserve license/source metadata from upstream runtime/wheels.
    for path in sorted(runtime.rglob('*')):
        if path.is_symlink() or not path.is_file(): continue
        magic = path.open('rb').read(4)
        if magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--options', 'runtime', str(path)], check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--options', 'runtime', str(app)], check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    files = {str(path.relative_to(app)): digest(path) for path in sorted(app.rglob('*')) if path.is_file() and not path.is_symlink() and '_CodeSignature' not in path.parts}
    manifest = {'scope': 'issue-3-independent-runtime-distribution-probe', 'runtime_lock': lock, 'files': files,
                'signature': 'ad-hoc hardened runtime; not Developer ID; not notarized', 'target': 'macOS x86_64'}
    (app.parent / (app.stem + '-manifest.json')).write_text(json.dumps(manifest, indent=2))
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', str(app), str(app.with_suffix('.zip'))], check=True)
    print(json.dumps({'app': str(app), 'zip': str(app.with_suffix('.zip')), 'source_sha256': lock['python']['sha256']}))


if __name__ == '__main__':
    main()
