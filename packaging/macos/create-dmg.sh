#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
app_path="$PWD/release/SilicoLab.app"
app_version=$(.desktop-venv/bin/python -c 'from silicolab.branding import APP_VERSION; print(APP_VERSION)')
dmg_path="$PWD/release/SilicoLab-$app_version-macOS-x86_64.dmg"
if [ ! -d "$app_path" ]; then
  printf 'Build release/SilicoLab.app first.\n' >&2
  exit 1
fi
codesign --verify --deep --strict "$app_path"
.desktop-venv/bin/python packaging/macos/dmg-background.py
.desktop-venv/bin/dmgbuild -s packaging/macos/dmg-settings.py "SilicoLab" "$dmg_path"
hdiutil verify "$dmg_path"
printf '\nCreated: %s\n' "$dmg_path"
shasum -a 256 "$dmg_path"
