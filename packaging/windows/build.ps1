# Build the standalone Windows executable (mcmgr.exe).
#
# Requirements: Windows 10/11, Python 3.10+ on PATH (Python from python.org,
# not the Microsoft Store stub).  Run from anywhere:
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#
# The script creates .venv-win, installs PyInstaller, refreshes the build
# stamp, and writes dist\mcmgr.exe.

param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

Write-Host "== mcmgr Windows build =="
Write-Host "project : $root"
python --version
if ($LASTEXITCODE -ne 0) {
    throw "python not found on PATH; install Python 3.10+ from python.org first"
}
# PyInstaller installs a bootloader wheel for the interpreter's architecture:
# win_amd64 on x64 Windows, win_arm64 on Windows on ARM.
python -c "import platform, sys; print('python arch:', platform.machine(), '| executable:', sys.executable)"

# Real build time shown by `mcmgr env`, and the exe's version resource.
python tools\stamp_build.py
python packaging\windows\make_version_info.py

$venv = Join-Path $root ".venv-win"
if (-not (Test-Path $venv)) {
    python -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"

& $py -m pip install --disable-pip-version-check --quiet --upgrade pip
& $py -m pip install --disable-pip-version-check --quiet "pyinstaller>=6.0"

if ($Clean) {
    Remove-Item -Recurse -Force (Join-Path $root "build") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $root "dist") -ErrorAction SilentlyContinue
}

& $py -m PyInstaller --clean --noconfirm packaging\windows\mcmgr.spec

$exe = Join-Path $root "dist\mcmgr.exe"
if (-not (Test-Path $exe)) {
    throw "build failed: $exe was not produced"
}

Write-Host ""
Write-Host "built: $exe"
Write-Host ("size : {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
Get-FileHash $exe -Algorithm SHA256 | Format-List

Write-Host "smoke test:"
& $exe --version
if ($LASTEXITCODE -ne 0) {
    throw "smoke test failed with exit code $LASTEXITCODE"
}
Write-Host ""
Write-Host "Done. Copy dist\mcmgr.exe next to other tools, or attach it to a release."
