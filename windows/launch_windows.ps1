$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw '未安装依赖，请先运行 install_windows.cmd' }
# 便于 Windows Agent 排查：启动时保留控制台，异常还可查 %LOCALAPPDATA%\SceneCutter\Logs\crash.log
& $python (Join-Path $PSScriptRoot 'app.py')
exit $LASTEXITCODE
