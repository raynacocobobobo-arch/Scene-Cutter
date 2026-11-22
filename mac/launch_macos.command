#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo '请先执行：bash install_macos.command'
  exit 1
fi
logdir="$HOME/Library/Logs/SceneCutter"
mkdir -p "$logdir"
echo "镜头切片 第3.4版 · 运行日志：$logdir/launcher.log"
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1
.venv/bin/python app.py 2>&1 | tee -a "$logdir/launcher.log"
