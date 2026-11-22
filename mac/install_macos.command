#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
echo '镜头切片 第3.4版 · 安装环境'
if ! command -v python3 >/dev/null 2>&1; then
  echo '未找到 Python 3。请安装 Python 3.10+（建议 3.11 或 3.12）。'
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' ; then
  echo '需要 Python >= 3.10。'
  exit 1
fi
if [ ! -x /opt/homebrew/bin/ffmpeg ] && [ ! -x /usr/local/bin/ffmpeg ] && ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  elif [ -x /opt/homebrew/bin/brew ]; then
    /opt/homebrew/bin/brew install ffmpeg
  elif [ -x /usr/local/bin/brew ]; then
    /usr/local/bin/brew install ffmpeg
  else
    echo 'FFmpeg 未安装。请先安装 Homebrew 和 FFmpeg：brew install ffmpeg'
    exit 1
  fi
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo 'Qt 绑定版本：'
.venv/bin/python -c 'import PySide6; print(PySide6.__version__)'
printf '\n安装完成。请运行：bash launch_macos.command\n'
