"""Downloading and laying out one Minecraft version (vanilla only)."""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import meta, mirror
from .net import DEFAULT_THREADS, DEFAULT_WORKERS, download, fetch_many
from .paths import RESOURCES_URL, Store
from .rules import os_arch, os_name, rules_allow


@dataclass
class InstallResult:
    version_id: str
    client_written: bool = False
    libraries_written: int = 0
    assets_written: int = 0
    natives_written: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    java_major: int | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        parts = [f"version {self.version_id}"]
        if self.client_written:
            parts.append("client jar downloaded")
        parts.append(f"{self.libraries_written} library files written")
        parts.append(f"{self.assets_written} assets written")
        if self.natives_written:
            parts.append(f"{self.natives_written} native files extracted")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts)


def _alternates(store: Store, url: str, *, version_id: str | None = None) -> tuple[str, ...]:
    """Fallback URLs for *url* (China mirror, when enabled)."""
    return tuple(mirror.candidates(store.mirror, url, version_id=version_id)[1:])


def _artifact_entry(artifact: dict) -> dict:
    return {
        "path": artifact["path"],
        "url": artifact["url"],
        "sha1": artifact.get("sha1"),
        "size": artifact.get("size"),
    }


def library_plan(version: dict, features: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Split a version's libraries into classpath artifacts and legacy natives.

    Modern versions ship natives as ordinary artifacts selected by rules, so
    they land in the first list.  Versions before ~1.19 use ``natives`` +
    ``classifiers`` entry-level maps instead and need the jars unpacked.
    """
    artifacts: list[dict] = []
    natives: list[dict] = []

    for library in version.get("libraries", []):
        if not rules_allow(library.get("rules"), features):
            continue
        downloads = library.get("downloads") or {}

        artifact = downloads.get("artifact")
        if artifact and artifact.get("url"):
            artifacts.append(_artifact_entry(artifact))

        native_map = library.get("natives")
        if native_map:
            key = native_map.get(os_name())
            if not key:
                continue
            key = key.replace("${arch}", "64" if os_arch() in {"x86_64", "aarch64"} else "32")
            classifier = (downloads.get("classifiers") or {}).get(key)
            if classifier and classifier.get("url"):
                natives.append(_artifact_entry(classifier))

    return artifacts, natives


def plan_assets(store: Store, version: dict) -> tuple[dict | None, list[dict]]:
    """Return the asset index and the list of objects it references."""
    index_info = version.get("assetIndex")
    if not index_info:
        return None, []
    index_path = store.index_path(index_info["id"])
    urls = mirror.candidates(store.mirror, index_info["url"])
    download(
        urls[0],
        index_path,
        index_info.get("sha1"),
        index_info.get("size"),
        alternates=urls[1:],
    )
    index = json.loads(index_path.read_text("utf-8"))

    seen: dict[str, dict] = {}
    for entry in (index.get("objects") or {}).values():
        digest = entry["hash"]
        if digest in seen:
            continue
        object_url = f"{RESOURCES_URL}{digest[:2]}/{digest}"
        seen[digest] = {
            "url": object_url,
            "dest": store.object_path(digest),
            "sha1": digest,
            "size": entry.get("size"),
            "alternates": _alternates(store, object_url),
        }
    return index, list(seen.values())


def _materialize_virtual(store: Store, index_id: str, index: dict) -> None:
    """Recreate legacy ``virtual``/``map_to_resources`` asset trees."""
    if not (index.get("virtual") or index.get("map_to_resources")):
        return
    target = store.assets / ("resources" if index.get("map_to_resources") else "virtual") / index_id
    for name, entry in (index.get("objects") or {}).items():
        destination = target / name
        if destination.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(store.object_path(entry["hash"]), destination)


def extract_natives(store: Store, version_id: str, natives: list[dict]) -> int:
    """Unpack legacy natives jars into ``<root>/natives/<version>``."""
    target = store.natives_dir(version_id)
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for entry in natives:
        jar = store.library_path(entry["path"])
        if not jar.is_file():
            continue
        with zipfile.ZipFile(jar) as archive:
            for member in archive.infolist():
                name = member.filename
                if member.is_dir() or name.startswith("META-INF/"):
                    continue
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(destination, "wb") as output:
                    shutil.copyfileobj(source, output)
                written += 1
    return written


def install_version(
    store: Store,
    version_id: str,
    *,
    with_assets: bool = True,
    jobs: int = DEFAULT_WORKERS,
    threads: int = DEFAULT_THREADS,
    force: bool = False,
    log=print,
) -> InstallResult:
    """Download everything needed to run *version_id*."""
    store.ensure()
    result = InstallResult(version_id=version_id)

    version = meta.get_version_json(store, version_id, force=force)
    result.java_major = (version.get("javaVersion") or {}).get("majorVersion")

    # 1. client jar
    client = (version.get("downloads") or {}).get("client")
    if client:
        log("client jar ...")
        urls = mirror.candidates(store.mirror, client["url"], version_id=version_id)
        result.client_written = download(
            urls[0],
            store.client_jar(version_id),
            client.get("sha1"),
            client.get("size"),
            threads=threads,
            alternates=urls[1:],
        )
    else:
        log("client jar: this version has no client download (server-only?)")

    # 2. libraries
    artifacts, natives = library_plan(version)
    log(f"libraries ({len(artifacts)}) ...")
    items = [
        {
            "url": artifact["url"],
            "dest": store.library_path(artifact["path"]),
            "sha1": artifact.get("sha1"),
            "size": artifact.get("size"),
            "alternates": _alternates(store, artifact["url"]),
        }
        for artifact in artifacts
    ]
    written, errors = fetch_many(items, workers=jobs, label="libraries", threads=threads)
    result.libraries_written = written
    result.errors.extend(errors)

    # 3. legacy natives
    if natives:
        log(f"natives ({len(natives)}) ...")
        native_items = [
            {
                "url": entry["url"],
                "dest": store.library_path(entry["path"]),
                "sha1": entry.get("sha1"),
                "size": entry.get("size"),
                "alternates": _alternates(store, entry["url"]),
            }
            for entry in natives
        ]
        _, native_errors = fetch_many(native_items, workers=jobs, label="natives", threads=threads)
        result.errors.extend(native_errors)
        result.natives_written = extract_natives(store, version_id, natives)

    # 4. assets
    index = None
    if with_assets:
        index, objects = plan_assets(store, version)
        if index is not None:
            log(f"assets ({len(objects)}) ...")
            written, errors = fetch_many(objects, workers=jobs, label="assets", threads=threads)
            result.assets_written = written
            result.errors.extend(errors)
            _materialize_virtual(store, str(index.get("id", "")), index)

    # 5. log4j config
    logging = (version.get("logging") or {}).get("client")
    if logging:
        info = logging["file"]
        urls = mirror.candidates(store.mirror, info["url"])
        download(
            urls[0],
            store.log_configs / info["id"],
            info.get("sha1"),
            info.get("size"),
            alternates=urls[1:],
        )

    # Assets are shared between versions, so report what is actually on disk
    # even when this run skipped them (--no-assets).
    assets_count = None
    index_info = version.get("assetIndex") or {}
    if index_info.get("id"):
        index_path = store.index_path(index_info["id"])
        if index_path.is_file():
            try:
                assets_count = len(json.loads(index_path.read_text("utf-8")).get("objects", {}))
            except (json.JSONDecodeError, OSError):
                assets_count = None

    record = {
        "version_id": version_id,
        "type": version.get("type"),
        "installed_at": int(time.time()),
        "assets_index": index_info.get("id"),
        "java_major": result.java_major,
        "libraries": len(artifacts),
        "natives": len(natives),
        "assets": assets_count,
    }
    store.install_record(version_id).write_text(json.dumps(record, indent=2) + "\n", "utf-8")
    return result


def verify_version(store: Store, version_id: str) -> list[str]:
    """Check installed files against their recorded hashes; return problems."""
    from .net import file_matches

    problems: list[str] = []
    version = meta.get_version_json(store, version_id)

    client = (version.get("downloads") or {}).get("client")
    if client and not file_matches(store.client_jar(version_id), client.get("sha1"), client.get("size")):
        problems.append(f"client jar: {store.client_jar(version_id)}")

    artifacts, natives = library_plan(version)
    for artifact in artifacts + natives:
        path = store.library_path(artifact["path"])
        if not file_matches(path, artifact.get("sha1"), artifact.get("size")):
            problems.append(f"library: {path}")

    index_info = version.get("assetIndex")
    if index_info:
        index_path = store.index_path(index_info["id"])
        if not index_path.is_file():
            problems.append(f"asset index: {index_path}")
        else:
            index = json.loads(index_path.read_text("utf-8"))
            missing = 0
            for entry in (index.get("objects") or {}).values():
                if not store.object_path(entry["hash"]).is_file():
                    missing += 1
            if missing:
                problems.append(f"assets: {missing} object(s) missing")

    if not store.version_json_path(version_id).is_file():
        problems.append("version json: missing")
    return problems


def remove_version(store: Store, version_id: str, *, keep_instance: bool = True) -> list[Path]:
    """Delete a version's files; returns the paths that were removed."""
    removed: list[Path] = []
    for path in (store.version_dir(version_id), store.natives_dir(version_id)):
        if path.exists():
            shutil.rmtree(path)
            removed.append(path)
    if not keep_instance and store.instance_dir(version_id).exists():
        shutil.rmtree(store.instance_dir(version_id))
        removed.append(store.instance_dir(version_id))
    return removed


def installed_versions(store: Store) -> list[dict]:
    """Return installed versions with their install records."""
    if not store.versions.is_dir():
        return []
    found: list[dict] = []
    for directory in sorted(store.versions.iterdir()):
        if not directory.is_dir():
            continue
        record = directory / "install.json"
        if not (directory / f"{directory.name}.json").is_file():
            continue
        data = {"id": directory.name, "installed_at": None, "type": None}
        if record.is_file():
            try:
                loaded = json.loads(record.read_text("utf-8"))
            except json.JSONDecodeError:
                loaded = {}
            data.update(loaded)
        found.append(data)
    return found
