#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo '请先执行：bash install_macos.command'
  exit 1
fi
bash generate_macos_icon.command
.venv/bin/python -m pip install 'pyinstaller>=6,<7'
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --name '镜头切片' \
  --osx-bundle-identifier com.scenecutter.app \
  --collect-submodules PySide6.QtMultimedia \
  --collect-submodules PySide6.QtMultimediaWidgets \
  --icon "assets/app_icon.icns" \
  --add-data "assets:assets" \
  app.py
# 中文应用显示名称和 ASCII Bundle ID 分离，避免打包后的 Metal 兼容性问题。
APP_PATH="dist/镜头切片.app"
ACTUAL_ID=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_PATH/Contents/Info.plist")
if [ "$ACTUAL_ID" != 'com.scenecutter.app' ]; then
  echo "错误：Bundle ID 不正确：$ACTUAL_ID" >&2
  exit 1
fi
# ad-hoc 签名：供本地使用，不代表 Apple Developer 公证。
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --verbose=2 "$APP_PATH"
printf '\n打包完成：%s\nBundle ID: %s\n需要本机 FFmpeg，安装命令：brew install ffmpeg\n' "$APP_PATH" "$ACTUAL_ID"
