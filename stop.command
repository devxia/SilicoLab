#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m silicolab --stop
else
  printf "未找到客户端运行环境，无需停止。\n"
fi
