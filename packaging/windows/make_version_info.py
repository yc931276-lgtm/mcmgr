"""Generate packaging/windows/version_info.txt for the PyInstaller build."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcmgr import __version__  # noqa: E402


def numeric_version(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", version)[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def main() -> int:
    filevers = numeric_version(__version__)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'mcmgr'),
        StringStruct('FileDescription', 'mcmgr - Minecraft Java Edition manager'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('InternalName', 'mcmgr'),
        StringStruct('OriginalFilename', 'mcmgr.exe'),
        StringStruct('ProductName', 'mcmgr'),
        StringStruct('ProductVersion', '{__version__}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    target = Path(__file__).with_name("version_info.txt")
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} (version {__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
