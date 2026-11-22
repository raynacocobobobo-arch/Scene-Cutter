param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw '请先运行 install_windows.cmd' }
if (-not $SkipInstall) {
    & $python -m pip install 'pyinstaller>=6,<7'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 安装失败' }
}
$here = [System.IO.Path]::GetFullPath($PSScriptRoot)
$parent = Split-Path $here -Parent
$assetsDir = Join-Path $here 'assets'
if (-not (Test-Path (Join-Path $assetsDir 'app_icon.png'))) {
    $assetsDir = Join-Path $parent 'assets'
}
if (-not (Test-Path (Join-Path $assetsDir 'app_icon.png'))) { throw '缺少正式图标 app_icon.png' }
$ico = Join-Path $assetsDir 'app_icon.ico'
& $python -c 'import sys; from PIL import Image; Image.open(sys.argv[1]).convert("RGBA").save(sys.argv[2], format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])' (Join-Path $assetsDir 'app_icon.png') $ico
if ($LASTEXITCODE -ne 0) { throw 'Windows ICO 生成失败' }
$distDir = Join-Path $here 'dist'
$workDir = Join-Path $here 'build'
& $python -m PyInstaller --noconfirm --clean --windowed `
    --name '镜头切片' `
    --icon $ico `
    --add-data "${assetsDir};assets" `
    --paths $here `
    --collect-submodules PySide6.QtMultimedia `
    --collect-submodules PySide6.QtMultimediaWidgets `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $workDir `
    (Join-Path $here 'app.py')
if ($LASTEXITCODE -ne 0) { throw 'Windows exe 打包失败' }
$exe = Join-Path $distDir '镜头切片\镜头切片.exe'
if (-not (Test-Path $exe)) { throw "未找到打包产物：$exe" }
Write-Host ''
Write-Host "已生成：$exe"
Write-Host '这是目录版：分发时请连同 _internal 文件夹一起复制，不要只复制 exe。'
Write-Host 'FFmpeg 本工具依赖外部安装，不会自动嵌入可执行文件。'
