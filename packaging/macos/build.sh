#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
export PYTHONDONTWRITEBYTECODE=1
python3 -B packaging/macos/bootstrap.py
.desktop-venv/bin/python -m pip install -r packaging/macos/requirements.lock
.desktop-venv/bin/python -m pip install --no-deps -e "./backend[desktop]"
npm --prefix frontend ci --no-fund --no-audit
npm --prefix frontend run build
.desktop-venv/bin/python -B packaging/macos/prepare.py
.desktop-venv/bin/python -m PyInstaller packaging/macos/SilicoLab.spec --distpath release --workpath build/pyinstaller --noconfirm
.desktop-venv/bin/python -B packaging/macos/finalize.py
codesign --verify --deep --strict --verbose=2 release/SilicoLab.app
bash packaging/macos/create-dmg.sh
app_version=$(.desktop-venv/bin/python -c 'from silicolab.branding import APP_VERSION; print(APP_VERSION)')
ditto -c -k --sequesterRsrc --keepParent release/SilicoLab.app "release/SilicoLab-$app_version-macOS-x86_64.zip"
printf '\nBuilt: %s/release/SilicoLab.app\n' "$PWD"
