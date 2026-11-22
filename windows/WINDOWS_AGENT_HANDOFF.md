# Windows Agent · 镜头切片 3.4.1 实机验收

目标：在真实 Windows 10/11 x64 桌面上完成源码运行、PyInstaller exe 打包、视频播放和导出检查。Mac 3.4.1 不能修改。

## 操作步骤

1. 解压 Windows 完整项目，先确认 `python --version` 或 `py -3.12 --version`，并准备好 FFmpeg / FFprobe。缺失时执行 `winget install -e --id Gyan.FFmpeg`，重新打开终端。
2. 依次执行 `install_windows.cmd`、`run_tests_windows.cmd`，记下测试结果、FFmpeg 与 PySide6 版本。
3. 运行 `launch_windows.cmd`，首次进入选择统一 JPG 输出目录（可含中文及空格）。确认“截图灵敏度”标题在大播放器正上方，绿色“开始解析”明显。
4. 同时导入 MP4/MOV、不同帧率、中文名称/空格路径的视频；完成后拖入新文件，旧已完成任务仅从队列清除；历史 JPEG 不应消失。同一个视频再次拖入应重新生成独立结果目录。
5. 打开 1080P 与 4K 视频，验证正式截图分辨率对应原片，画面不拉伸；查看镜头墙，向右切换大图；播放、暂停、拖动时间轴，手动点击“截取当前画面”并验证 JPG。
6. 验证停止任务后没有悬挂 ffmpeg.exe，已完成 JPG 不丢失。连续启动/退出 10 次；播放后退出、执行任务后退出分别 5 次。
7. 执行 `build_windows.cmd`，检查 `dist\镜头切片\镜头切片.exe` 存在且具有黑白场记板图标。**必须用打包出的 exe 重复步骤 3–6，不以源码运行替代实机打包测试。**
8. 在 125%、150% Windows 缩放下检查界面不遮挡；针对不同显示器检查视频正常；若黑屏记录 QMediaPlayer 错误并检查 `%LOCALAPPDATA%\SceneCutter\Logs\crash.log`。
9. 若打包构建或运行失败，修复应限制在 Windows 文件和构建配置；Mac 基准代码不要直接改。修复后重新运行全部测试并存档。

## 必须回传的验收资料

- Windows 版本 / CPU 架构、Python / PySide6 / FFmpeg 版本；
- `run_tests_windows.cmd` 输出、`build_windows.cmd` 输出；
- 最终 `.exe` 是否可以双击独立启动（运行时安装 FFmpeg 仍是前提）；
- 4K JPG 原始分辨率截图、含中文路径处理截图、镜头墙与首次引导窗口截图；
- `%LOCALAPPDATA%\SceneCutter\Logs\crash.log`（有问题时），Windows 事件查看器崩溃模块；
- 若所有场景通过，标记 Windows 3.4.1 通过实机验收，而不是只报告 Python 语法测试通过。

安全约束：只处理本地素材，不上传视频，未经授权不删除历史 JPG；Windows 版不能覆盖 Mac 3.4.1。
