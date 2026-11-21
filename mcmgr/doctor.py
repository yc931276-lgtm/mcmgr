"""``mcmgr env``: report the runtime environment and installation details."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from . import java as javamod
from .paths import LAUNCHER_NAME, LAUNCHER_VERSION, Store


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def _build_label(source_root: Path) -> str:
    """Best-effort build identity: git commit, or a note that there is none."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "source tree (no VCS metadata)"
    if commit.returncode != 0 or not commit.stdout.strip():
        return "source tree (no VCS metadata)"
    label = f"git {commit.stdout.strip()}"
    try:
        status = subprocess.run(
            ["git", "-C", str(source_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if status.returncode == 0 and status.stdout.strip():
            label += " (modified)"
    except (OSError, subprocess.SubprocessError):
        pass
    return label


#: Written by ``tools/stamp_build.py``; absent when running from a plain copy.
BUILD_STAMP = Path(__file__).resolve().parent / "_build.json"


def _ago(epoch: float | None) -> str:
    if not epoch:
        return "unknown"
    seconds = max(0, int(time.time() - epoch))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _newest_source_mtime(package_dir: Path) -> float | None:
    newest = None
    for path in package_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or stamp > newest:
            newest = stamp
    return newest


def build_info(package_dir: Path | None = None, stamp_path: Path | None = None) -> dict:
    """Resolve the real build time.

    Prefers the stamp written by ``tools/stamp_build.py``; falls back to the
    newest source file mtime so a plain checkout still shows something honest.
    ``stale`` is true when sources are newer than the recorded build.
    """
    package_dir = package_dir or Path(__file__).resolve().parent
    stamp_path = stamp_path or BUILD_STAMP
    newest = _newest_source_mtime(package_dir)
    info: dict = {
        "built_at": None,
        "epoch": None,
        "origin": None,
        "commit": None,
        "stale": False,
        "age": "unknown",
    }
    data = None
    try:
        data = json.loads(stamp_path.read_text("utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict) and data.get("built_epoch"):
        epoch = float(data["built_epoch"])
        info.update(
            built_at=data.get("built_at"),
            epoch=epoch,
            origin="stamp",
            commit=data.get("commit") or None,
            stale=bool(newest and newest > epoch + 2),
        )
    elif newest:
        info.update(
            built_at=datetime.fromtimestamp(newest).astimezone().isoformat(timespec="seconds"),
            epoch=newest,
            origin="source-mtime",
            stale=False,
        )
    info["age"] = _ago(info["epoch"])
    return info


def _directory_size(root: Path) -> int:
    total = 0
    for directory, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(directory, name))
            except OSError:
                continue
    return total


def _proxy_env() -> dict[str, str]:
    keys = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
    found: dict[str, str] = {}
    for name, value in os.environ.items():
        lowered = name.lower()
        if lowered in keys and value.strip():
            found[name] = value
    return found


def _writable(target: Path) -> bool:
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def collect(store: Store) -> dict:
    """Gather version/build/environment facts as JSON-serialisable data."""
    source_root = Path(__file__).resolve().parent.parent
    build = build_info()
    frozen = bool(getattr(sys, "frozen", False))
    source = str(Path(sys.executable)) if frozen else str(source_root)
    build_label = "frozen executable (PyInstaller)" if frozen else _build_label(source_root)
    runtimes = [{"path": path, "major": major} for path, major in javamod.discover()]
    store_root = store.root
    installed = sorted(
        path.parent.name
        for path in store.versions.glob("*/install.json")
        if path.parent.name and not path.parent.name.startswith(".")
    )
    launch_configs = sorted(path.stem for path in store.launch.glob("*.json")) if store.launch.is_dir() else []
    usage = None
    if store_root.exists():
        try:
            usage = shutil.disk_usage(str(store_root))
        except OSError:
            usage = None
    return {
        "mcmgr": {
            "name": LAUNCHER_NAME,
            "version": __version__,
            "launcher_version": LAUNCHER_VERSION,
            "source": source,
            "build": build_label,
            "frozen": frozen,
            "built_at": build["built_at"],
            "built_epoch": build["epoch"],
            "build_origin": build["origin"],
            "build_commit": build["commit"],
            "build_stale": build["stale"],
            "build_age": build["age"],
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_os": os.name,
        },
        "store": {
            "root": str(store_root),
            "exists": store_root.exists(),
            "writable": _writable(store_root),
            "size_bytes": _directory_size(store_root) if store_root.exists() else 0,
            "free_bytes": usage.free if usage else None,
        },
        "mirror": {
            "mode": store.mirror,
            "from_env": os.environ.get("MCMGR_MIRROR") or None,
        },
        "proxy": _proxy_env(),
        "java": {
            "JAVA_HOME": os.environ.get("JAVA_HOME") or None,
            "runtimes": runtimes,
        },
        "installed": installed,
        "launch_configs": launch_configs,
    }


def _format_built(info: dict) -> str:
    if not info["built_at"]:
        return "unknown (no build stamp and no source files found)"
    origin = info.get("build_origin") or info.get("origin")
    age = info.get("build_age") or info.get("age") or "unknown"
    commit = info.get("build_commit") or info.get("commit")
    stale = info.get("build_stale", info.get("stale", False))
    if origin == "stamp":
        suffix = f", {age}"
        if commit:
            suffix += f", commit {commit}"
        if stale:
            suffix += " [sources newer than stamp]"
    else:
        suffix = f" ({age}, newest source file; no build stamp)"
    return f"{info['built_at']}{suffix}"


def render(report: dict) -> str:
    """Format a :func:`collect` report for humans."""
    info = report["mcmgr"]
    python = report["python"]
    system = report["platform"]
    store = report["store"]
    mirror = report["mirror"]
    java = report["java"]
    lines = [
        f"{info['name']} {info['version']}  (launcher version {info['launcher_version']})",
        f"  build     : {info['build']}",
        f"  built     : {_format_built(info)}",
        f"  source    : {info['source']}",
        f"  python    : {python['version']} ({python['implementation']}) {python['executable']}",
        f"  platform  : {system['system']} {system['release']} {system['machine']}",
        f"  store     : {store['root']}"
        + ("" if store["exists"] else " (missing)")
        + ("" if store["writable"] else " (not writable)")
        + f" — {_human_size(store['size_bytes'])} used"
        + (f", {_human_size(store['free_bytes'])} free" if store["free_bytes"] is not None else ""),
        f"  mirror    : {mirror['mode']}"
        + (f" (MCMGR_MIRROR={mirror['from_env']})" if mirror["from_env"] else " (default)"),
        f"  proxy     : {', '.join(f'{k}={v}' for k, v in report['proxy'].items()) or '(none)'}",
        f"  java home : {java['JAVA_HOME'] or '(not set)'}",
    ]
    if java["runtimes"]:
        summary = ", ".join(f"Java {entry['major']}" for entry in java["runtimes"])
        lines.append(f"  java      : {len(java['runtimes'])} runtime(s) — {summary}")
    else:
        lines.append("  java      : (none detected)")
    versions = report["installed"]
    lines.append(f"  installed : {', '.join(versions) if versions else '(none)'}")
    configs = report["launch_configs"]
    lines.append(f"  launch cfg: {', '.join(configs) if configs else '(none)'}")
    return "\n".join(lines)
