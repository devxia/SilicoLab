"""Build and verify a signed ZIP copy from a source-only tree and a Unicode install path.

This is explicit trusted build/download work. It never enables runtime installation/network.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/python-runtime/distribution.json')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='silicolab-runtime-source-only-') as temporary:
        root = Path(temporary)
        source = root / 'source'
        # Exactly the public build/probe source, no repository/private input/environment copies.
        for folder in ('python-runtime', 'python-probe'):
            shutil.copytree(ROOT / 'tools' / folder, source / 'tools' / folder,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        boundary = source / 'backend/src/silicolab/restricted_python.py'
        boundary.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'backend/src/silicolab/restricted_python.py', boundary)
        assert not list(source.rglob('node_modules')) and not list(source.rglob('.venv'))
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(root / 'empty-home'), 'LANG': 'en_US.UTF-8'}
        Path(environment['HOME']).mkdir()
        built = source / 'release/PythonBoundaryProbe.app'
        build = subprocess.run([sys.executable, '-I', '-B', str(source / 'tools/python-runtime/build.py'), '--output', str(built)],
                               cwd='/', env=environment, capture_output=True, text=True, timeout=180)
        if build.returncode:
            raise RuntimeError('Independent build failed: ' + build.stderr[-2000:])
        destination = root / '独立 安装目录 "quoted"'
        destination.mkdir()
        archive = built.with_suffix('.zip')
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(destination)], check=True, env=environment)
        installed = destination / built.name
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(installed)], check=True, capture_output=True, env=environment)
        # Remove the entire builder/source/cache before running the relocated app.
        shutil.rmtree(source)
        run = subprocess.run([str(installed / 'Contents/MacOS/PythonBoundaryProbe')], cwd='/', env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
        if run.returncode:
            raise RuntimeError('Packaged boundary check failed: ' + run.stderr[-4000:])
        evidence = json.loads(run.stdout)
        if evidence['result'] != 'passed' or evidence['tests'] != 16:
            raise ValueError('Not all real boundary checks ran')
        if evidence['environment']['python'] != '3.13.18':
            raise ValueError('Unexpected packaged interpreter')
        report = {'result': 'passed', 'scope': 'issue-3-independent-zip-runtime-boundary', 'tests': evidence['tests'],
                  'source_only_builder': True, 'builder_removed_before_run': True, 'unicode_space_and_quote_install_path': True,
                  'developer_environments_absent': True, 'signature_verified': 'ad-hoc hardened runtime', 'developer_id_signed': False,
                  'notarized': False, 'archive_sha256': archive_sha, 'environment': evidence['environment'], 'probe_source_sha256': evidence['source_sha256'],
                  'limits': ['Deprecated Seatbelt/sandbox-exec; only macOS 15.7.7 x86_64 exercised.',
                             'Manual ZIP/CLI execution verified; no Gatekeeper/notarization approval claim.',
                             'Single process; fork/spawn denied; not a general process-tree sandbox.',
                             'Production workbench integration and crash supervision remain separate #16 work.']}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
