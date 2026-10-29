#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
if [ ! -x .desktop-venv/bin/python ]; then
  python3 -m venv .desktop-venv
fi
.desktop-venv/bin/python -m pip install -e "./backend[desktop]"
npm --prefix frontend ci --no-fund --no-audit
npm --prefix frontend run build
.desktop-venv/bin/python -m PyInstaller packaging/macos/SilicoLab.spec --distpath release --workpath build/pyinstaller --noconfirm
codesign --verify --deep --strict --verbose=2 release/SilicoLab.app
bash packaging/macos/create-dmg.sh
app_version=$(.desktop-venv/bin/python -c 'from silicolab.branding import APP_VERSION; print(APP_VERSION)')
ditto -c -k --sequesterRsrc --keepParent release/SilicoLab.app "release/SilicoLab-$app_version-macOS-x86_64.zip"
printf '\nBuilt: %s/release/SilicoLab.app\n' "$PWD"
