#!/usr/bin/env bash
# Best-effort Windows build on Linux: installs Windows Python under Wine and
# runs the same PyInstaller spec as a real Windows machine.
#
#   ./packaging/windows/build-under-wine.sh
#   WINEPREFIX=/tmp/wine-py PYVER=3.12.8 ./packaging/windows/build-under-wine.sh
#
# Official releases should still be built on Windows or via GitHub Actions;
# Wine is only a fallback for machines without Windows.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYVER="${PYVER:-3.12.8}"
CACHE="${CACHE:-$ROOT/.cache/windows-python}"
export WINEPREFIX="${WINEPREFIX:-$ROOT/.wine-pyinstaller}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-mscoree,mshtml=}"

command -v wine >/dev/null || { echo "wine not found; install wine64 first" >&2; exit 1; }
mkdir -p "$CACHE"
setup="$CACHE/python-$PYVER-amd64.exe"
if [[ ! -s "$setup" ]]; then
  # python.org is often slow from mainland China; try mirrors first.
  urls=(
    "${PYTHON_URL:-}"
    "https://registry.npmmirror.com/-/binary/python/$PYVER/python-$PYVER-amd64.exe"
    "https://mirrors.tuna.tsinghua.edu.cn/python/$PYVER/python-$PYVER-amd64.exe"
    "https://mirrors.huaweicloud.com/python/$PYVER/python-$PYVER-amd64.exe"
    "https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe"
  )
  for url in "${urls[@]}"; do
    [[ -z "$url" ]] && continue
    echo "== downloading Windows Python $PYVER: $url"
    if curl -fL -C - --max-time 600 --retry 2 -o "$setup" "$url"; then
      break
    fi
    rm -f "$setup"
  done
fi
[[ -s "$setup" ]] || { echo "could not download a Windows Python installer" >&2; exit 2; }

cd "$ROOT"
python3 tools/stamp_build.py >/dev/null
python3 packaging/windows/make_version_info.py

echo "== installing Windows Python ($WINEPREFIX) =="
wine "$setup" /quiet InstallAllUsers=0 Include_pip=1 Include_test=0 \
  PrependPath=0 Include_launcher=0 'TargetDir=C:\py312'
wine 'C:\py312\python.exe' --version

echo "== installing PyInstaller =="
wine 'C:\py312\python.exe' -m pip install --disable-pip-version-check --no-cache-dir \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org \
  "pyinstaller>=6.0"

echo "== building mcmgr.exe =="
wine 'C:\py312\python.exe' -m PyInstaller --clean --noconfirm \
  packaging\\windows\\mcmgr.spec

ls -l "$ROOT/dist"
sha256sum "$ROOT/dist/mcmgr.exe"
