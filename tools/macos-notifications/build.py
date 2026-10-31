"""Build the bounded native notification helper; never requests notification permission."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess


def build(output):
    output=Path(output).absolute()
    if output.exists():raise ValueError('Refusing to overwrite existing notification helper')
    source=Path(__file__).with_name('main.swift')
    contents=output/'Contents';mac=contents/'MacOS';mac.mkdir(parents=True)
    identity='com.silicolab.notifications'
    info={'CFBundleIdentifier':identity,'CFBundleName':'SilicoLab','CFBundleDisplayName':'SilicoLab','CFBundleExecutable':'SilicoLabNotifications','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'1.0','LSUIElement':True,'LSMinimumSystemVersion':'13.0'}
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['xcrun','swiftc','-swift-version','5','-O','-framework','Cocoa','-framework','UserNotifications',str(source),'-o',str(mac/'SilicoLabNotifications')],check=True)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-','--options','runtime','--timestamp=none',str(output)],check=True)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(output)],check=True)
    manifest={'bundleId':identity,'signing':'ad-hoc Hardened Runtime; not notarized','sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'files':{p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()}}
    output.with_name(output.stem+'-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='release/SilicoLabNotifications.app');args=parser.parse_args()
    print(json.dumps(build(args.output),indent=2))
