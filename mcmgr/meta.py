"""Mojang metadata: the version manifest and per-version documents."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import mirror
from .net import download
from .paths import VERSION_MANIFEST_URL, Store

MANIFEST_TTL = 6 * 3600  # seconds; refreshes at most a few times a day


class VersionNotFound(LookupError):
    """The requested version id is not in the Mojang manifest."""


def get_manifest(store: Store, *, force: bool = False) -> dict:
    """Return the (cached) version manifest."""
    store.ensure()
    path = store.manifest_cache()
    fresh = path.is_file() and (time.time() - path.stat().st_mtime) < MANIFEST_TTL
    if force or not fresh:
        try:
            urls = mirror.candidates(store.mirror, VERSION_MANIFEST_URL)
            download(urls[0], path, alternates=urls[1:])
        except Exception:  # noqa: BLE001 - fall back to a stale cache offline
            if not path.is_file():
                raise
    return json.loads(path.read_text("utf-8"))


def find_version(manifest: dict, version_id: str) -> dict | None:
    for entry in manifest.get("versions", []):
        if entry.get("id") == version_id:
            return entry
    return None


def resolve_version_id(manifest: dict, version_id: str) -> str:
    """Accept a version id, or the aliases ``latest``/``latest-release``/``latest-snapshot``."""
    aliases = {
        "latest": "release",
        "latest-release": "release",
        "latest-snapshot": "snapshot",
    }
    key = aliases.get(version_id)
    if key is None:
        return version_id
    return manifest.get("latest", {}).get(key, version_id)


def get_version_json(store: Store, version_id: str, *, force: bool = False) -> dict:
    """Load (and cache) the version document for *version_id*."""
    path = store.version_json_path(version_id)
    if path.is_file() and not force:
        return json.loads(path.read_text("utf-8"))

    manifest = get_manifest(store)
    entry = find_version(manifest, version_id)
    if entry is None:
        raise VersionNotFound(f"unknown version {version_id!r}; try `mcmgr versions`")

    urls = mirror.candidates(store.mirror, entry["url"], version_id=version_id)
    download(urls[0], path, entry.get("sha1"), entry.get("size"), alternates=urls[1:])
    return json.loads(Path(path).read_text("utf-8"))


def list_versions(manifest: dict, kind: str = "release", search: str | None = None) -> list[dict]:
    """Filter the manifest's version list.

    *kind* is one of ``release``, ``snapshot``, ``old`` (old_beta/old_alpha) or
    ``all``.
    """
    versions = manifest.get("versions", [])
    if kind == "release":
        versions = [v for v in versions if v.get("type") == "release"]
    elif kind == "snapshot":
        versions = [v for v in versions if v.get("type") == "snapshot"]
    elif kind == "old":
        versions = [v for v in versions if v.get("type") in {"old_beta", "old_alpha"}]
    if search:
        needle = search.lower()
        versions = [v for v in versions if needle in str(v.get("id", "")).lower()]
    return versions
