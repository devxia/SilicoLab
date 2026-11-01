"""Install independently signed nested runtimes, then seal and inventory the app."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def finalize():
    app=ROOT/'release/SilicoLab.app';resources=app/'Contents/Resources';stage=ROOT/'build/bundled-runtime'
    for name in ('runtime','analysis','notifications','backend-src','tools'):
        target=resources/name
        if target.exists():raise ValueError('Nested runtime destination already exists')
        if name=='analysis':
            target.mkdir()
            for artifact in ('PythonBoundaryProbe.app','PythonBoundaryProbe-manifest.json'):
                subprocess.run(['/usr/bin/ditto',str(stage/name/artifact),str(target/artifact)],check=True)
        else:subprocess.run(['/usr/bin/ditto',str(stage/name),str(target)],check=True)
        # PyInstaller exposes _MEIPASS=Contents/Frameworks; bundled data live in
        # Resources and use internal links just like PyInstaller-collected data.
        (app/'Contents/Frameworks'/name).symlink_to('../Resources/'+name)
    entitlements=ROOT/'build/node-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps({'com.apple.security.cs.allow-jit':True,'com.apple.security.cs.allow-unsigned-executable-memory':True}))
    subprocess.run(['/usr/bin/codesign','--force','--sign','-','--options','runtime','--entitlements',str(entitlements),'--timestamp=none',str(resources/'runtime/bin/node')],check=True)
    for nested in ('analysis/PythonBoundaryProbe.app','notifications/SilicoLabNotifications.app'):
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(resources/nested)],check=True)
    # No --deep signing: it would rewrite independently verified Python/helper bytes.
    subprocess.run(['/usr/bin/codesign','--force','--sign','-','--timestamp=none',str(app)],check=True)
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
    files={}
    links={}
    for path in sorted(app.rglob('*')):
        name=path.relative_to(app).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):raise ValueError('Bundle link leaves application: '+name)
            links[name]=str(path.readlink())
        elif path.is_file():files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'format':'silicolab-product-inventory-v1','architecture':'x86_64','signing':'ad-hoc; app not notarized; independent Python and notification helper have Hardened Runtime',
              'runtimeLock':json.loads((ROOT/'packaging/macos/runtime-lock.json').read_text()),'files':files,'links':links}
    (ROOT/'release/SilicoLab-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Sealed standalone app;',len(files),'files;',len(links),'internal links.')


if __name__=='__main__':finalize()
