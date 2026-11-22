@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" %*
if errorlevel 1 (
  echo.
  echo [错误] 操作未完成。请保留窗口内容交给本地 Agent 排查。
  pause
  exit /b 1
)
