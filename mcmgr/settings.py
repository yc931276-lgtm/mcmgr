"""Per-version launch settings, saved by ``mcmgr config``.

The file is plain JSON kept outside the game directory (``<root>/launch/<id>.json``),
so ``mcmgr remove --all-files`` can delete the instance without losing the setup.
Only values the user actually set are stored; everything else falls back to the
built-in defaults or the version metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SETTINGS_VERSION = 1

#: Fields that may be cleared with ``mcmgr config --unset``.
SCALAR_FIELDS = ("username", "uuid", "memory", "java", "width", "height")


@dataclass
class LaunchSettings:
    """Launch options remembered for one installed version."""

    username: str | None = None
    #: Custom UUID, or ``"offline"`` to keep deriving it from the username.
    uuid: str | None = None
    memory: str | None = None
    java: str | None = None
    width: int | None = None
    height: int | None = None
    jvm_args: list[str] = field(default_factory=list)
    game_args: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            [
                self.username,
                self.uuid,
                self.memory,
                self.java,
                self.width,
                self.height,
                self.jvm_args,
                self.game_args,
            ]
        )

    def to_dict(self) -> dict:
        data: dict = {"settings_version": SETTINGS_VERSION}
        data.update({name: getattr(self, name) for name in SCALAR_FIELDS if getattr(self, name) is not None})
        if self.jvm_args:
            data["jvm_args"] = list(self.jvm_args)
        if self.game_args:
            data["game_args"] = list(self.game_args)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "LaunchSettings":
        settings = cls()
        for name in SCALAR_FIELDS:
            value = data.get(name)
            if value is None:
                continue
            if name in {"width", "height"}:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            if isinstance(value, str):
                value = value.strip() or None
            setattr(settings, name, value)
        for name in ("jvm_args", "game_args"):
            values = data.get(name)
            if isinstance(values, list):
                setattr(settings, name, [str(item) for item in values if str(item).strip()])
        return settings

    @classmethod
    def load(cls, path: Path) -> "LaunchSettings":
        try:
            raw = path.read_text("utf-8")
        except FileNotFoundError:
            return cls()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return cls()
        return cls.from_dict(data) if isinstance(data, dict) else cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", "utf-8")
