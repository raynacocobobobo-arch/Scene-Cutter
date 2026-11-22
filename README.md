# 镜头切片 · Scene Cutter 3.4.1

**同一版本的 macOS 与 Windows 双平台源码仓库。** 主程序使用 Python + PySide6 + FFmpeg，镜头识别及原分辨率 JPG 抽帧功能保持一致，无须 AI 模型。

| 平台 | 版本定位 | 源码与安装说明 | 构建产物 |
|---|---|---|---|
| macOS | **3.4.1 正式定版**（已经 Mac 实机验证） | [mac/](mac/) · [Mac 使用说明](mac/README.md) | `镜头切片.app` |
| Windows 10/11 x64 | **3.4.1 移植版，待本地 Agent 实机验收** | [windows/](windows/) · [Windows 使用说明](windows/README.md) | `镜头切片.exe`（目录版） |

## macOS

```bash
cd mac
bash install_macos.command
bash launch_macos.command
bash build_macos.command
```

macOS 显示名为「镜头切片」，**Bundle ID 固定为 `com.scenecutter.app`**，不可用中文名称代替，否则可能引发打包后的 macOS 图形渲染异常。

## Windows

```powershell
cd windows
winget install -e --id Gyan.FFmpeg
.\install_windows.cmd
.\run_tests_windows.cmd
.\launch_windows.cmd
.\build_windows.cmd
```

Windows 为 PyInstaller 目录版，发布时需复制整个 `dist\镜头切片` 目录。Windows 的 `Windows Agent` 需按照 [验收交接说明](windows/WINDOWS_AGENT_HANDOFF.md) 逐项验证 exe 后再视为正式发行。

## CI / 平台隔离

- [Mac 自动测试与打包](.github/workflows/build-macos.yml)：`macos-latest`，仅在 Mac 源码变更时触发。
- [Windows 自动测试与打包](.github/workflows/build-windows.yml)：`windows-latest`，仅在 Windows 源码变更时触发。
- 两个平台的配置、打包脚本、图标、日志目录分别管理；不要以 Windows 变更覆盖 Mac 已定版的业务逻辑。
- 所有截图、源视频、缓存、虚拟环境和本机日志均不得提交仓库。

> GitHub CI 仅证明自动构建与测试状态，不能代替 Windows 实机的播放、GPU 解码、中文路径、拖拽、4K 抽帧与关闭窗口验证。
