"""Custom default-character skins for offline players.

Minecraft draws players that have no skin (everyone in offline mode) with a
built-in default skin.  Instead of editing the client jar, this module writes a
small resource pack that replaces those textures and selects it in the
instance's ``options.txt``.  The jar stays untouched, so ``mcmgr verify`` keeps
passing and a normal reinstall never loses anything.

Both texture layouts are covered:

* legacy, up to 1.19.2 -- ``textures/entity/steve.png`` (classic model) and
  ``textures/entity/alex.png`` (slim model);
* modern, 1.19.4 and later -- ``textures/entity/player/wide/*.png`` and
  ``textures/entity/player/slim/*.png`` (all the built-in default skins).

The pack is enabled through ``resourcePacks`` in ``options.txt`` and removed
again by ``mcmgr skin <version> --clear``.
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
import zipfile
from pathlib import Path

TEXTURE_ROOT = "assets/minecraft/textures/entity"
PACK_NAME = "mcmgr-default-skin.zip"
PACK_ID = f"file/{PACK_NAME}"
PACK_DESCRIPTION = "mcmgr default character skin"
STATE_NAME = ".mcmgr-skin.json"

#: Every built-in default skin name used by modern versions.
DEFAULT_SKIN_NAMES = ("alex", "ari", "efe", "kai", "makena", "noor", "steve", "sunny", "zuri")

LEGACY_CLASSIC = f"{TEXTURE_ROOT}/steve.png"
LEGACY_SLIM = f"{TEXTURE_ROOT}/alex.png"
MODERN_WIDE = tuple(f"{TEXTURE_ROOT}/player/wide/{name}.png" for name in DEFAULT_SKIN_NAMES)
MODERN_SLIM = tuple(f"{TEXTURE_ROOT}/player/slim/{name}.png" for name in DEFAULT_SKIN_NAMES)

#: Accepted skin image sizes (vanilla supports the classic 64x32 and 64x64).
VALID_SIZES = {(64, 64), (64, 32)}
MODELS = ("both", "classic", "slim")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: First release of every resource-pack format, used when a version jar has no
#: ``version.json`` (1.7.10 and earlier): (release date, pack format).
_PACK_FORMAT_ERAS = (
    ("2016-02-29", 2),  # 1.9
    ("2016-11-14", 3),  # 1.11
    ("2018-07-18", 4),  # 1.13
    ("2019-12-10", 5),  # 1.15
    ("2020-08-11", 6),  # 1.16.2
    ("2021-06-08", 7),  # 1.17
    ("2021-11-30", 8),  # 1.18
    ("2022-06-07", 9),  # 1.19
    ("2022-12-07", 12),  # 1.19.3
    ("2023-03-14", 13),  # 1.19.4
    ("2023-06-07", 15),  # 1.20
    ("2023-09-21", 18),  # 1.20.2
    ("2023-12-05", 22),  # 1.20.3
    ("2024-04-23", 32),  # 1.20.5
    ("2024-06-13", 34),  # 1.21
    ("2024-10-22", 42),  # 1.21.2
    ("2024-12-03", 46),  # 1.21.4
)


class SkinError(RuntimeError):
    """A skin image or resource pack could not be installed."""


# -- image helpers --------------------------------------------------------


def read_png_size(path: str | Path) -> tuple[int, int]:
    """Return ``(width, height)`` after checking that *path* is a PNG skin."""
    path = Path(path).expanduser()
    try:
        with path.open("rb") as handle:
            header = handle.read(33)
    except OSError as error:
        raise SkinError(f"cannot read skin image {path}: {error}") from error
    if header[:8] != PNG_SIGNATURE:
        raise SkinError(f"{path} is not a PNG image")
    if len(header) < 24 or header[12:16] != b"IHDR":
        raise SkinError(f"{path}: PNG file has no IHDR header")
    width, height = struct.unpack(">II", header[16:24])
    if (width, height) not in VALID_SIZES:
        raise SkinError(
            f"{path} is {width}x{height}; Minecraft skins must be 64x64 (or the legacy 64x32)"
        )
    return width, height


# -- version helpers ------------------------------------------------------


def _version_document(store, version_id: str) -> dict:
    path = store.version_json_path(version_id)
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _jar_pack_format(store, version_id: str) -> int | None:
    jar = store.client_jar(version_id)
    try:
        with zipfile.ZipFile(jar) as archive:
            raw = archive.read("version.json")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
        value = (data.get("pack_version") or {}).get("resource")
        return int(value) if value is not None else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _format_for_release(release: str | None) -> int:
    if not release:
        return 9
    stamp = str(release)[:10]
    chosen = 1
    for start, pack_format in _PACK_FORMAT_ERAS:
        if stamp >= start:
            chosen = pack_format
        else:
            break
    return chosen


def pack_format(store, version_id: str) -> int:
    """The resource-pack format the installed version expects."""
    value = _jar_pack_format(store, version_id)
    if value is not None:
        return value
    document = _version_document(store, version_id)
    return _format_for_release(document.get("releaseTime") or document.get("time"))


def detect_layout(store, version_id: str) -> str:
    """``"modern"`` when the jar ships ``player/wide`` textures, else ``"legacy"``."""
    jar = store.client_jar(version_id)
    try:
        with zipfile.ZipFile(jar) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile) as error:
        raise SkinError(f"cannot read installed client jar {jar}: {error}") from error
    prefix = "assets/minecraft/textures/entity/player/"
    return "modern" if any(name.startswith(prefix) for name in names) else "legacy"


def textures_for(model: str) -> tuple[str, ...]:
    """Texture entries a pack must contain for the requested model set."""
    if model not in MODELS:
        raise SkinError(f"unknown skin model {model!r}; use one of {', '.join(MODELS)}")
    entries: list[str] = []
    if model in ("both", "classic"):
        entries.append(LEGACY_CLASSIC)
        entries.extend(MODERN_WIDE)
    if model in ("both", "slim"):
        entries.append(LEGACY_SLIM)
        entries.extend(MODERN_SLIM)
    return tuple(entries)


# -- options.txt ----------------------------------------------------------


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text("utf-8").splitlines()
    except FileNotFoundError:
        return []


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", "utf-8")
    temporary.replace(path)


def _option(lines: list[str], key: str) -> tuple[int | None, str]:
    prefix = f"{key}:"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index, line[len(prefix):]
    return None, ""


def _json_list(raw: str) -> list:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _enable_in_options(options: Path) -> None:
    lines = _read_lines(options)
    index, raw = _option(lines, "resourcePacks")
    if index is None:
        # Keep the vanilla pack selected; without it the game loses its assets.
        lines.append("resourcePacks:" + json.dumps(["vanilla", PACK_ID]))
    else:
        packs = _json_list(raw)
        if PACK_ID not in packs:
            packs.append(PACK_ID)
            lines[index] = "resourcePacks:" + json.dumps(packs)
    index, raw = _option(lines, "incompatibleResourcePacks")
    if index is not None:
        bad = _json_list(raw)
        if PACK_ID in bad:
            lines[index] = "incompatibleResourcePacks:" + json.dumps([p for p in bad if p != PACK_ID])
    _write_lines(options, lines)


def _disable_in_options(options: Path) -> bool:
    if not options.is_file():
        return False
    lines = _read_lines(options)
    changed = False
    for key in ("resourcePacks", "incompatibleResourcePacks"):
        index, raw = _option(lines, key)
        if index is None:
            continue
        values = _json_list(raw)
        if PACK_ID in values:
            remaining = [value for value in values if value != PACK_ID]
            if key == "resourcePacks" and not remaining:
                # The vanilla pack is always selected; never leave the list empty.
                remaining = ["vanilla"]
            lines[index] = f"{key}:" + json.dumps(remaining)
            changed = True
    if changed:
        _write_lines(options, lines)
    return changed


# -- install / remove -----------------------------------------------------


def _pack_path(store, version_id: str) -> Path:
    return store.instance_dir(version_id) / "resourcepacks" / PACK_NAME


def _state_path(store, version_id: str) -> Path:
    return store.instance_dir(version_id) / STATE_NAME


def _write_metadata(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(state_path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", "utf-8")
    temporary.replace(state_path)


def install(
    store,
    version_id: str,
    image: str | Path,
    *,
    model: str = "both",
) -> dict:
    """Build and enable a default-character skin pack, returning its details."""
    jar = store.client_jar(version_id)
    if not jar.is_file():
        raise SkinError(f"{version_id} is not installed; run `mcmgr install {version_id}` first")
    image = Path(image).expanduser()
    width, height = read_png_size(image)
    entries = textures_for(model)
    try:
        payload = image.read_bytes()
    except OSError as error:
        raise SkinError(f"cannot read skin image {image}: {error}") from error

    fmt = pack_format(store, version_id)
    layout = detect_layout(store, version_id)
    meta = {"pack": {"pack_format": fmt, "description": PACK_DESCRIPTION}}
    destination = _pack_path(store, version_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack.mcmeta", json.dumps(meta, indent=2) + "\n")
        for entry in entries:
            archive.writestr(entry, payload)
    temporary.replace(destination)

    options = store.instance_dir(version_id) / "options.txt"
    _enable_in_options(options)

    state = {
        "state_version": 1,
        "version_id": version_id,
        "image": str(image.resolve()),
        "image_size": [width, height],
        "image_sha1": hashlib.sha1(payload).hexdigest(),
        "model": model,
        "pack_format": fmt,
        "layout": layout,
        "textures": len(entries),
        "pack": str(destination),
        "options": str(options),
        "installed_at": int(time.time()),
    }
    _write_metadata(_state_path(store, version_id), state)
    return info(store, version_id) or state


def info(store, version_id: str) -> dict | None:
    """Describe the installed skin pack, or ``None`` when there is none."""
    state_path = _state_path(store, version_id)
    try:
        state = json.loads(state_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    pack = _pack_path(store, version_id)
    state["pack_exists"] = pack.is_file()
    options = store.instance_dir(version_id) / "options.txt"
    index, raw = _option(_read_lines(options), "resourcePacks")
    state["enabled"] = index is not None and PACK_ID in _json_list(raw)
    return state


def remove(store, version_id: str) -> bool:
    """Delete the pack and deselect it, returning whether anything was removed."""
    removed = False
    pack = _pack_path(store, version_id)
    try:
        pack.unlink()
        removed = True
    except FileNotFoundError:
        pass
    state_path = _state_path(store, version_id)
    try:
        state_path.unlink()
        removed = True
    except FileNotFoundError:
        pass
    if _disable_in_options(store.instance_dir(version_id) / "options.txt"):
        removed = True
    return removed
