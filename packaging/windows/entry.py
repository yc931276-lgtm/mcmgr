"""Entry point used by PyInstaller when building the Windows executable."""

from __future__ import annotations

import sys

# Legacy Windows consoles may use a non-UTF-8 code page; never crash on the
# progress bar / non-ASCII characters.  Per-version launch text is unaffected.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from mcmgr.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
