"""Read-only DMG mount, exact app inventory and actual copied-app local smoke."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dmg',type=Path,required=True);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    inventory=json.loads(args.manifest.read_text());device=None
    with tempfile.TemporaryDirectory(prefix='silicolab-dmg-install-') as directory:
        root=Path(directory);mount=root/'mounted';mount.mkdir()
        try:
            subprocess.run(['/usr/bin/hdiutil','verify',str(args.dmg.resolve())],check=True,capture_output=True)
            subprocess.run(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-noautoopen','-mountpoint',str(mount),str(args.dmg.resolve())],check=True,capture_output=True);device=mount
            assert (mount/'Applications').is_symlink() and str((mount/'Applications').readlink())=='/Applications'
            copied=root/'Installed SilicoLab.app';subprocess.run(['/usr/bin/ditto',str(mount/'SilicoLab.app'),str(copied)],check=True)
            for name,digest in inventory['files'].items():assert hashlib.sha256((copied/name).read_bytes()).hexdigest()==digest,name
            subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(copied)],check=True,capture_output=True)
            subprocess.run(['/usr/bin/hdiutil','detach',str(mount)],check=True,capture_output=True);device=None
            subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('smoke_bundle.py')),'--app',str(copied),'--output',str(root/'manual.json')],check=True)
            result={'status':'passed','dmgSha256':hashlib.sha256(args.dmg.read_bytes()).hexdigest(),'readOnlyMount':True,'dragInstallTarget':'/Applications','copiedAppInventoryExact':True,'mountedImageDetachedBeforeExecution':True,'actualCopiedAppManualSmoke':json.loads((root/'manual.json').read_text())}
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
        finally:
            if device:subprocess.run(['/usr/bin/hdiutil','detach',str(device)],check=True,capture_output=True)


if __name__=='__main__':main()
