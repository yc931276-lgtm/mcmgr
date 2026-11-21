#!/usr/bin/env python3
"""Stamp the source tree with a real build time.

Run this after changing the code and before packaging/copying the project::

    python3 tools/stamp_build.py          # write mcmgr/_build.json
    python3 tools/stamp_build.py --print  # only show what would be written
    python3 tools/stamp_build.py --clean  # remove the stamp

``mcmgr env`` reads the stamp and shows ``built <time> (<age>)``; when the stamp
is missing it falls back to the newest source file mtime, and when sources are
newer than the stamp it marks the build as stale.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / "mcmgr" / "_build.json"
VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def project_version() -> str:
    text = (ROOT / "mcmgr" / "__init__.py").read_text("utf-8")
    match = VERSION_RE.search(text)
    return match.group(1) if match else "unknown"


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def stamp() -> dict:
    now = int(datetime.now().timestamp())
    return {
        "version": project_version(),
        "built_at": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
        "built_epoch": now,
        "commit": git_commit(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write mcmgr/_build.json with the current time.")
    parser.add_argument("--print", dest="only_print", action="store_true", help="print the stamp without writing it")
    parser.add_argument("--clean", action="store_true", help="delete the stamp instead of writing one")
    args = parser.parse_args(argv)

    if args.clean:
        if STAMP.exists():
            STAMP.unlink()
            print(f"removed {STAMP}")
        else:
            print(f"no stamp at {STAMP}")
        return 0

    data = stamp()
    if args.only_print:
        print(json.dumps(data, indent=2))
        return 0
    STAMP.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    print(f"wrote {STAMP}")
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
