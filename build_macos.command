#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo '请先执行：bash install_macos.command'
  exit 1
fi
.venv/bin/python -m pip install 'pyinstaller>=6,<7'
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --name '镜头切片' \
  --collect-submodules PySide6.QtMultimedia \
  --collect-submodules PySide6.QtMultimediaWidgets \
  --icon "assets/app_icon.icns" \
  --add-data "assets:assets" \
  app.py
printf '\n打包完成：dist/镜头切片.app\n需要本机 FFmpeg，安装命令：brew install ffmpeg\n'
