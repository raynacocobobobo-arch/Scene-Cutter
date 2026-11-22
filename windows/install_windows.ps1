# 镜头切片 3.4.1 · Windows 安装（Windows PowerShell 5.1 / PowerShell 7）
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($ver in @('-3.12','-3.11')) {
            & py $ver -c 'import sys; print(sys.version_info[:2])' *> $null
            if ($LASTEXITCODE -eq 0) { return @{Exe='py'; Args=@($ver)} }
        }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python -c 'import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 12)' *> $null
        if ($LASTEXITCODE -eq 0) { return @{Exe='python'; Args=@()} }
    }
    throw '请安装 64 位 Python 3.12（或 3.11），然后重新运行此脚本。可使用 winget install Python.Python.3.12'
}
$interp = Find-Python
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host '创建独立 Python 环境...'
    & $interp.Exe @($interp.Args) -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
}
$pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip 升级失败' }
& $pythonExe -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
& $pythonExe -c 'import PySide6, numpy, PIL; print("Python 依赖检查通过")'
if ($LASTEXITCODE -ne 0) { throw '依赖导入失败' }
Write-Host ''
Write-Host '依赖安装完成。FFmpeg 如未安装，请执行：'
Write-Host 'winget install -e --id Gyan.FFmpeg'
Write-Host '然后重新打开终端及软件。'
