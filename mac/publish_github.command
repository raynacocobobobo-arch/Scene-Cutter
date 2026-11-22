#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
REPO="raynacocobobobo-arch/Scene-Cutter"

command -v git >/dev/null || { echo "请先安装 Git：xcode-select --install"; exit 1; }
command -v gh >/dev/null || { echo "请先安装 GitHub CLI：brew install gh"; exit 1; }
if ! gh auth status >/dev/null 2>&1; then
  gh auth login
fi
if ! gh repo view "$REPO" >/dev/null 2>&1; then
  echo "目标 GitHub 仓库不存在或无法访问：https://github.com/$REPO"
  exit 1
fi
if [ -d .git ]; then
  echo "已有 .git 目录，为避免覆盖现有工作，本脚本不自动执行。"
  echo "请检查 git remote -v 后自行推送。"
  exit 1
fi
if [ -n "$(gh api "repos/$REPO/commits" --jq '.[0].sha' 2>/dev/null || true)" ]; then
  echo "远端仓库已有提交。请先克隆仓库并合并更改，脚本不会覆盖。"
  exit 1
fi
read -r -p "将 3.4 Mac 定版源码推送到 $REPO 的 main 分支，输入 YES 确认：" CONFIRM
[ "$CONFIRM" = YES ] || { echo "已取消"; exit 0; }
git init -b main
git add .
git commit -m 'Release 镜头切片 3.4 for macOS with official icon'
git remote add origin "https://github.com/$REPO.git"
git push -u origin main
echo "发布完成：https://github.com/$REPO"
