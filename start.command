#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import silicolab, fastapi, uvicorn, openpyxl' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -e ./backend
fi
if [ ! -f frontend/dist/index.html ]; then
  npm --prefix frontend ci --no-fund --no-audit
  npm --prefix frontend run build
fi
exec .venv/bin/python -m silicolab
