# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file console executable for modern Windows.

Build it on Windows (PyInstaller cannot cross-compile):

    python packaging\\windows\\make_version_info.py
    python -m PyInstaller --clean --noconfirm packaging\\windows\\mcmgr.spec

or simply run ``packaging\\windows\\build.ps1``.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
sys.path.insert(0, ROOT)

datas = []
_stamp = os.path.join(ROOT, "mcmgr", "_build.json")
if os.path.exists(_stamp):
    # doctor.build_info() reads this next to the frozen package.
    datas.append((_stamp, "mcmgr"))

_version_file = os.path.join(SPECPATH, "version_info.txt")
if not os.path.exists(_version_file):
    _version_file = None

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "test", "doctest", "pydoc", "pdb", "lib2to3"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mcmgr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_file,
)
