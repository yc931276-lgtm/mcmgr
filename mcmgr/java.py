"""Locating a usable Java runtime without relying on ``PATH``."""

from __future__ import annotations

import glob as globmod
import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?[^"]*"')

_CANDIDATE_GLOBS = {
    "linux": ["/usr/lib/jvm/*/bin/java", "/usr/java/*/bin/java", "/opt/java/*/bin/java"],
    "osx": [
        "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
        "/System/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
    ],
    "windows": [
        r"C:\Program Files\Java\*\bin\java.exe",
        r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
        r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
    ],
}


def _explain_failure(path: str, error: Exception) -> str:
    return f"{path}: {error}"


def java_major(path: str | os.PathLike[str]) -> int | None:
    """The major version of the JVM at *path* (``None`` when it cannot run)."""
    try:
        completed = subprocess.run(
            [str(path), "-version"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = f"{completed.stdout}\n{completed.stderr}"
    match = _VERSION_RE.search(output)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):
        return int(match.group(2))  # 1.8.0_402 -> 8
    return major


@lru_cache(maxsize=1)
def discover() -> tuple[tuple[str, int], ...]:
    """Every runnable JVM found on this machine, newest first."""
    roots: list[Path] = []

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        roots.append(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java"))

    system = "windows" if os.name == "nt" else ("osx" if platform.system() == "Darwin" else "linux")
    for pattern in _CANDIDATE_GLOBS.get(system, []):
        try:
            # ``glob`` accepts absolute patterns (including drive letters), while
            # ``Path.glob`` rejects them; Windows paths are absolute.
            matched = sorted(globmod.glob(pattern))
        except (OSError, ValueError):
            continue
        roots.extend(Path(match) for match in matched)

    which = shutil.which("java")
    if which:
        roots.append(Path(which))

    found: dict[str, int] = {}
    for candidate in roots:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        key = str(resolved)
        if key in found:
            continue
        major = java_major(resolved)
        if major is not None:
            found[key] = major

    return tuple(sorted(found.items(), key=lambda item: (-item[1], item[0])))


def find_java(required_major: int | None = None, explicit: str | None = None) -> tuple[str, int] | None:
    """Pick a JVM: explicit path, else the best candidate for *required_major*."""
    if explicit:
        major = java_major(explicit)
        return (str(Path(explicit).expanduser()), major) if major is not None else None

    if required_major is None:
        return discover()[0] if discover() else None

    candidates = discover()
    exact = [c for c in candidates if c[1] == required_major]
    if exact:
        return exact[0]
    newer = [c for c in candidates if c[1] > required_major]
    if newer:
        return min(newer, key=lambda item: item[1])
    return candidates[0] if candidates else None
