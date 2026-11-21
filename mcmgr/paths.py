"""Filesystem layout and constants for the mcmgr store.

Everything mcmgr downloads lives under a single root directory
(``~/.mcmgr`` by default, overridable with ``MCMGR_HOME`` or ``--root``):

    <root>/
      meta/                    cached Mojang metadata (version manifest)
      versions/<id>/<id>.json  version manifest document for one version
      versions/<id>/<id>.jar   client jar
      libraries/               maven-style library tree
      assets/indexes/          asset index json files
      assets/objects/xx/<sha1> content-addressed asset objects
      assets/log_configs/      log4j configuration files
      natives/<id>/            extracted legacy natives
      instances/<id>/          game directory (worlds, options.txt, ...)
      launch/<id>.json         remembered launch settings (see mcmgr config)
"""

from __future__ import annotations

import os
from pathlib import Path

LAUNCHER_NAME = "mcmgr"
LAUNCHER_VERSION = "0.6.0"
USER_AGENT = f"{LAUNCHER_NAME}/{LAUNCHER_VERSION}"

VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RESOURCES_URL = "https://resources.download.minecraft.net/"


def default_root() -> Path:
    """The store root, honouring ``MCMGR_HOME``."""
    env = os.environ.get("MCMGR_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".mcmgr"


class Store:
    """Paths inside one mcmgr store."""

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        mirror: str | None = None,
    ) -> None:
        from .mirror import DEFAULT_MODE

        self.root = Path(root).expanduser().resolve() if root else default_root().expanduser().resolve()
        # Download source: official | bmclapi | auto (see mcmgr.mirror).
        self.mirror = mirror or os.environ.get("MCMGR_MIRROR") or DEFAULT_MODE

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Store({self.root})"

    # -- top level ---------------------------------------------------------
    @property
    def meta(self) -> Path:
        return self.root / "meta"

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def libraries(self) -> Path:
        return self.root / "libraries"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def natives(self) -> Path:
        return self.root / "natives"

    @property
    def instances(self) -> Path:
        return self.root / "instances"

    @property
    def launch(self) -> Path:
        return self.root / "launch"

    # -- assets ------------------------------------------------------------
    @property
    def indexes(self) -> Path:
        return self.assets / "indexes"

    @property
    def objects(self) -> Path:
        return self.assets / "objects"

    @property
    def log_configs(self) -> Path:
        return self.assets / "log_configs"

    # -- helpers -----------------------------------------------------------
    def ensure(self) -> None:
        for directory in (
            self.meta,
            self.versions,
            self.libraries,
            self.assets,
            self.indexes,
            self.objects,
            self.log_configs,
            self.natives,
            self.instances,
            self.launch,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def version_dir(self, version_id: str) -> Path:
        return self.versions / version_id

    def version_json_path(self, version_id: str) -> Path:
        return self.version_dir(version_id) / f"{version_id}.json"

    def client_jar(self, version_id: str) -> Path:
        return self.version_dir(version_id) / f"{version_id}.jar"

    def install_record(self, version_id: str) -> Path:
        return self.version_dir(version_id) / "install.json"

    def library_path(self, relative: str) -> Path:
        return self.libraries / relative

    def index_path(self, index_id: str) -> Path:
        return self.indexes / f"{index_id}.json"

    def object_path(self, digest: str) -> Path:
        return self.objects / digest[:2] / digest

    def natives_dir(self, version_id: str) -> Path:
        return self.natives / version_id

    def instance_dir(self, version_id: str) -> Path:
        return self.instances / version_id

    def launch_config(self, version_id: str) -> Path:
        return self.launch / f"{version_id}.json"

    def manifest_cache(self) -> Path:
        return self.meta / "version_manifest_v2.json"
