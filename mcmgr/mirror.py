"""Alternative download sources ("mirrors") for Minecraft files.

Mainland China often cannot reach Mojang's CDNs, or reaches them very slowly.
The community-run `BMCLAPI <https://bmclapi2.bangbang93.com>`_ mirrors the whole
official file set under different host names, so every URL can be rewritten
with simple prefix rules:

=======================  ===============================================
official                 BMCLAPI
=======================  ===============================================
piston-meta.mojang.com   bmclapi2.bangbang93.com  (same path)
launchermeta.mojang.com  bmclapi2.bangbang93.com  (same path)
piston-data.mojang.com   bmclapi2.bangbang93.com/version/<id>/client
libraries.minecraft.net  bmclapi2.bangbang93.com/maven/<path>
resources.download.net   bmclapi2.bangbang93.com/assets/<path>
=======================  ===============================================
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

BMCLAPI_BASE = "https://bmclapi2.bangbang93.com"

#: Supported mirror modes.
MODES = ("official", "bmclapi", "auto")
DEFAULT_MODE = "auto"

_OFFICIAL_CDN_HOSTS = {
    "piston-meta.mojang.com",
    "launchermeta.mojang.com",
    "launcher.mojang.com",
    "piston-data.mojang.com",
}
_LIBRARY_HOST = "libraries.minecraft.net"
_RESOURCE_HOST = "resources.download.minecraft.net"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def bmclapi_url(url: str, *, version_id: str | None = None) -> str | None:
    """Rewrite one official URL to its BMCLAPI equivalent.

    Returns ``None`` when the URL is not a known Mojang endpoint (nothing to
    rewrite).  ``version_id`` is required for client jars because BMCLAPI keys
    them by version instead of by object hash.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    host = _host(url)
    path = parts.path

    if host in _OFFICIAL_CDN_HOSTS:
        # The client jar is served by version id on the mirror.
        if version_id and path.startswith("/v1/objects/") and path.endswith("/client.jar"):
            return f"{BMCLAPI_BASE}/version/{version_id}/client"
        # Version documents are also available under /version/<id>/json.
        if version_id and path.startswith("/v1/packages/") and path.endswith(f"/{version_id}.json"):
            return f"{BMCLAPI_BASE}/version/{version_id}/json"
        return f"{BMCLAPI_BASE}{path}"

    if host == _LIBRARY_HOST:
        return f"{BMCLAPI_BASE}/maven{path}"

    if host == _RESOURCE_HOST:
        return f"{BMCLAPI_BASE}/assets{path}"

    return None


def candidates(mode: str, url: str, *, version_id: str | None = None) -> list[str]:
    """Return the URLs to try for *url*, in order of preference.

    ``official`` uses Mojang only, ``bmclapi`` prefers the China mirror and
    falls back to Mojang, ``auto`` tries Mojang first and falls back to the
    mirror.  The returned list always contains at least the original URL.
    """
    mode = mode or DEFAULT_MODE
    if mode not in MODES:
        raise ValueError(f"unknown mirror mode {mode!r}; expected one of {', '.join(MODES)}")

    mirror = bmclapi_url(url, version_id=version_id)
    if mirror is None or mirror == url:
        return [url]
    if mode == "bmclapi":
        return [mirror, url]
    if mode == "auto":
        return [url, mirror]
    return [url]


def describe(mode: str) -> str:
    """Human readable description of a mirror mode."""
    return {
        "official": "Mojang CDN only",
        "bmclapi": "BMCLAPI (China mirror), Mojang as fallback",
        "auto": "Mojang CDN first, BMCLAPI (China mirror) as fallback",
    }.get(mode or DEFAULT_MODE, mode)


def valid_mode(mode: str) -> bool:
    return mode in MODES


__all__ = [
    "BMCLAPI_BASE",
    "DEFAULT_MODE",
    "MODES",
    "bmclapi_url",
    "candidates",
    "describe",
    "valid_mode",
]
