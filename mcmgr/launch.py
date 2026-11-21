"""Building and running the Minecraft launch command (offline mode)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import java as javamod
from . import meta
from .installer import extract_natives, library_plan
from .paths import LAUNCHER_NAME, LAUNCHER_VERSION, Store
from .rules import rules_allow

_PLACEHOLDER_RE = re.compile(r"\$\{([a-zA-Z0-9_]+)\}")


class LaunchError(RuntimeError):
    """The game cannot be launched as configured."""


def offline_uuid(player_name: str) -> str:
    """The UUID a vanilla server assigns offline players (``OfflinePlayer:<name>``)."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{player_name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30  # version 3
    digest[8] = (digest[8] & 0x3F) | 0x80  # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(digest)))


#: Accepted spellings of "keep deriving the UUID from the username".
OFFLINE_UUID_WORDS = {"offline", "auto", "default", "vanilla"}


def normalize_uuid(value: str) -> str:
    """Validate a player UUID; ``offline``/``auto``/``default`` mean derived.

    Accepts the canonical dashed form as well as 32 bare hex digits.
    """
    text = str(value).strip().lower()
    if text in OFFLINE_UUID_WORDS:
        return "offline"
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError) as exc:
        raise LaunchError(
            f"invalid player UUID {value!r}; expected 8-4-4-4-12 hex digits, "
            "32 hex digits, or 'offline'"
        ) from exc


def substitute(value: str, mapping: dict[str, str]) -> str:
    """Replace ``${placeholders}``; unknown ones are left untouched."""
    return _PLACEHOLDER_RE.sub(lambda match: str(mapping.get(match.group(1), match.group(0))), value)


def _unresolved(argv: list[str]) -> list[str]:
    return sorted({m.group(1) for arg in argv for m in _PLACEHOLDER_RE.finditer(arg)})


def _flatten_arguments(entries: list, features: dict, mapping: dict[str, str]) -> list[str]:
    result: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            result.append(substitute(entry, mapping))
            continue
        if not isinstance(entry, dict):
            continue
        if not rules_allow(entry.get("rules"), features):
            continue
        value = entry.get("value")
        if isinstance(value, str):
            result.append(substitute(value, mapping))
        elif isinstance(value, list):
            result.extend(substitute(str(item), mapping) for item in value)
    return result


@dataclass
class LaunchPlan:
    java: str
    java_major: int | None
    argv: list[str]
    cwd: Path
    version_id: str
    warnings: list[str] = field(default_factory=list)

    def command_line(self) -> str:
        return " ".join(shlex.quote(part) for part in [self.java, *self.argv])


def build_command(
    store: Store,
    version_id: str,
    *,
    username: str = "Player",
    uuid_override: str | None = None,
    java: str | None = None,
    memory: str | None = None,
    width: int | None = None,
    height: int | None = None,
    jvm_args: list[str] | None = None,
    game_args: list[str] | None = None,
) -> LaunchPlan:
    """Assemble everything needed to spawn the game.

    ``uuid_override`` replaces the UUID derived from ``username`` (pass
    ``"offline"`` to force the derived value); ``jvm_args`` are extra flags for
    the JVM and ``game_args`` are extra flags for the game itself.
    """
    version = meta.get_version_json(store, version_id)
    warnings: list[str] = []

    auth_uuid = offline_uuid(username)
    if uuid_override is not None:
        override = normalize_uuid(uuid_override)
        if override != "offline":
            auth_uuid = override

    client_jar = store.client_jar(version_id)
    if not client_jar.is_file():
        raise LaunchError(f"version {version_id} is not installed (missing {client_jar}); run `mcmgr install {version_id}`")

    required_major = (version.get("javaVersion") or {}).get("majorVersion")
    resolved = javamod.find_java(required_major, java)
    if resolved is None:
        if java:
            raise LaunchError(f"no runnable Java at {java}")
        raise LaunchError("no Java runtime found; install one or pass --java <path>")
    java_path, java_ver = resolved
    if required_major and java_ver < required_major:
        warnings.append(f"version {version_id} wants Java {required_major}+, using Java {java_ver}")

    artifacts, natives = library_plan(version)

    classpath_entries = [client_jar] + [store.library_path(artifact["path"]) for artifact in artifacts]
    missing = [str(path) for path in classpath_entries if not path.is_file()]
    if missing:
        raise LaunchError(f"{len(missing)} file(s) missing (e.g. {missing[0]}); run `mcmgr install {version_id}`")

    natives_dir = store.natives_dir(version_id)
    natives_dir.mkdir(parents=True, exist_ok=True)
    if natives:
        extract_natives(store, version_id, natives)

    instance_dir = store.instance_dir(version_id)
    instance_dir.mkdir(parents=True, exist_ok=True)

    assets_root = store.assets
    index_info = version.get("assetIndex") or {}
    index_id = str(index_info.get("id") or "legacy")
    index_file = store.index_path(index_id)
    if index_info and index_file.is_file():
        index = json.loads(index_file.read_text("utf-8"))
        if index.get("virtual"):
            assets_root = store.assets / "virtual" / index_id
        elif index.get("map_to_resources"):
            assets_root = store.assets / "resources"

    logging_info = (version.get("logging") or {}).get("client") or {}
    log_config = store.log_configs / logging_info["file"]["id"] if logging_info.get("file") else None

    features = {
        "is_demo_user": False,
        "has_custom_resolution": width is not None and height is not None,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }

    mapping: dict[str, str] = {
        "auth_player_name": username,
        "version_name": version_id,
        "game_directory": str(instance_dir),
        "assets_root": str(assets_root),
        "assets_index_name": index_id,
        "auth_uuid": auth_uuid,
        "auth_access_token": "0",
        "auth_session": "0",
        "clientid": "",
        "auth_xuid": "0",
        "user_type": "legacy",
        "user_properties": "{}",
        "version_type": str(version.get("type") or "release"),
        "natives_directory": str(natives_dir),
        "launcher_name": LAUNCHER_NAME,
        "launcher_version": LAUNCHER_VERSION,
        "classpath": os.pathsep.join(str(path) for path in classpath_entries),
        "classpath_separator": os.pathsep,
        "library_directory": str(store.libraries),
        "path": str(log_config) if log_config else "",
    }
    if width is not None:
        mapping["resolution_width"] = str(width)
    if height is not None:
        mapping["resolution_height"] = str(height)

    argv: list[str] = []
    if memory:
        argv.append(f"-Xmx{memory}")
    if jvm_args:
        argv.extend(jvm_args)

    arguments = version.get("arguments") or {}
    legacy_arguments = version.get("minecraftArguments")

    if arguments.get("jvm") is not None:
        argv.extend(_flatten_arguments(arguments.get("jvm", []), features, mapping))
        argv.append(version["mainClass"])
        argv.extend(_flatten_arguments(arguments.get("game", []), features, mapping))
    elif legacy_arguments:
        argv.extend(["-Djava.library.path=" + str(natives_dir)])
        argv.extend(["-cp", mapping["classpath"]])
        argv.append(version["mainClass"])
        argv.extend(substitute(token, mapping) for token in shlex.split(legacy_arguments))
    else:
        raise LaunchError(f"version {version_id} has no launch arguments")

    if game_args:
        argv.extend(game_args)

    unresolved = _unresolved(argv)
    if unresolved:
        warnings.append("unresolved placeholders (may be harmless): " + ", ".join(unresolved))

    return LaunchPlan(
        java=java_path,
        java_major=java_ver,
        argv=argv,
        cwd=instance_dir,
        version_id=version_id,
        warnings=warnings,
    )


def launch(store: Store, version_id: str, *, plan: LaunchPlan | None = None, **kwargs) -> int:
    """Run the game and return its exit code."""
    plan = plan or build_command(store, version_id, **kwargs)
    process = subprocess.run([plan.java, *plan.argv], cwd=str(plan.cwd))
    return process.returncode
