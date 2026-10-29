# Build from the project root with packaging/macos/build.sh.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parents[1]
backend_src = root / 'backend' / 'src'
sys.path.insert(0, str(backend_src))
from silicolab.branding import APP_NAME, APP_VERSION, MACOS_BUNDLE_ID

# Keep local.py as a real file: engine provenance hashes the source at runtime.
datas = [(str(root / 'frontend' / 'dist'), 'frontend/dist'),
         (str(backend_src / 'silicolab/features/codon/local.py'), 'silicolab/features/codon')]
datas += collect_data_files('silicolab', includes=['features/codon/resources/*'])
datas += collect_data_files('certifi')
a = Analysis([str(root / 'packaging/macos/desktop-entry.py')], pathex=[str(backend_src)], datas=datas,
             hiddenimports=['webview.platforms.cocoa', 'uvicorn.logging', 'uvicorn.loops.asyncio',
                            'uvicorn.protocols.http.h11_impl', 'uvicorn.lifespan.on', 'certifi',
                            'silicolab.features.codon.local'],
             excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'gtk', 'gi',
                       'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.winforms',
                       'IPython', 'pytest', 'pandas', 'numpy', 'matplotlib', 'scipy'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          argv_emulation=False, target_arch='x86_64', codesign_identity=None, entitlements_file=None)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
app = BUNDLE(collection, name=f'{APP_NAME}.app', icon=str(root / 'packaging/macos/assets/SilicoLab.icns'),
             bundle_identifier=MACOS_BUNDLE_ID, version=APP_VERSION,
             info_plist={'CFBundleDisplayName': APP_NAME,
                         'CFBundleShortVersionString': APP_VERSION,
                         'CFBundleVersion': APP_VERSION,
                         'NSHighResolutionCapable': True,
                         'LSMinimumSystemVersion': '13.0',
                         'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
                         'NSHumanReadableCopyright': APP_NAME,
                         'NSSupportsAutomaticTermination': False})
