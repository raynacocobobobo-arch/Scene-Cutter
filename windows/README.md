# 镜头切片 3.4.1 · Windows 版

以 Mac 3.4.1 定版为功能基准。**Windows 适配是独立副本，Mac 版源码与打包脚本不做任何修改。**

- 界面：沿用中文极简黑白布局、小型静态人物线稿、绿色“开始解析”、播放器上方居中的“截图灵敏度”、播放器下方的“截取当前画面”。
- 功能：批量检测、高清 JPG（不缩放原画面）、镜头墙、手动补帧、去重、历史记录、自定义输出位置、下次导入时清理完成队列。
- 模型：不需要 AI 模型；依赖 Python + PySide6 + NumPy + Pillow + FFmpeg / FFprobe。
- 数据：Windows 本地 `%LOCALAPPDATA%\SceneCutter\state.json`；日志 `%LOCALAPPDATA%\SceneCutter\Logs\crash.log`。Mac 数据与 Windows 数据互不覆盖。

## Windows 10/11 本机运行

建议 Windows 11 / Windows 10 x64、Python 3.12 x64（也支持 3.11）、已安装 FFmpeg。

在 PowerShell 里安装 FFmpeg：

```powershell
winget install -e --id Gyan.FFmpeg
```

安装后**重新打开终端**，确认 `ffmpeg -version`、`ffprobe -version` 都能运行。然后双击：

1. `install_windows.cmd`：创建独立虚拟环境并安装固定依赖；
2. `launch_windows.cmd`：调试运行并显示日志；
3. `run_tests_windows.cmd`：测试（需 FFmpeg）；
4. `build_windows.cmd`：生成 `dist\镜头切片\镜头切片.exe`。

生成的是 PyInstaller **目录版 exe**：复制 `dist\镜头切片` **整个文件夹**（包括 `_internal`），不要只复制 exe。FFmpeg 是另行安装的系统依赖，打包不会自动提供它。Windows 安装包尚未进行数字签名，SmartScreen 可能需要人工确认来源。

## Windows 特殊处理

- 使用 `.ico` 正式黑白场记板图标；保留原始 PNG 供窗口内部使用。
- 默认使用 Qt Multimedia 自行选择的 Windows 后端；没有强行指定 Mac 的 `darwin` 后端。Windows 媒体播放需在实机验证。
- FFmpeg/FFprobe 优先搜索手动配置的 `SCENECUTTER_FFMPEG_DIR`，其次是 exe 所在目录、`bin`、winget 常用目录以及 PATH。
- 截图与探测子进程使用 Windows 隐藏控制台参数，不频繁弹出黑色命令行窗口。
- 在 Windows `%LOCALAPPDATA%` 下保存任务配置及崩溃日志；简体中文 Windows 字体用于结果总览图。
- `.exe` 启动、打开/退出稳定性、GPU 解码、文件拖放、4K 视频抽帧等仍需 **Windows 本地 Agent 实机验收**。

## 自动化测试与构建

GitHub Actions 建议使用 `windows-latest` 跑测试并打包。注意：跨平台主机不能直接替代 Windows 构建。

参见 `WINDOWS_AGENT_HANDOFF.md`，里面包含实际交给 Windows Agent 的验收命令与具体用例。
