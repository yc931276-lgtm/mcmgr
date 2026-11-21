"""Offline tests for ``mcmgr skin`` (custom default-character skins)."""

from __future__ import annotations

import contextlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from mcmgr import skin as skinmod
from mcmgr.cli import build_parser, main
from mcmgr.paths import Store

PACK_ID = "file/mcmgr-default-skin.zip"


def make_png(width: int = 64, height: int = 64, color: bytes = b"\xc8\x28\x28\xff") -> bytes:
    rows = b"".join(b"\x00" + color * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def make_version(
    store: Store,
    version_id: str = "1.19.2",
    *,
    pack_format: int | None = 9,
    release: str = "2022-08-05T11:55:20+00:00",
    modern: bool = False,
    jar_version: bool = True,
) -> Store:
    store.ensure()
    store.version_dir(version_id).mkdir(parents=True, exist_ok=True)
    store.version_json_path(version_id).write_text(
        json.dumps({"id": version_id, "releaseTime": release}), "utf-8"
    )
    with zipfile.ZipFile(store.client_jar(version_id), "w") as archive:
        if jar_version:
            archive.writestr(
                "version.json", json.dumps({"id": version_id, "pack_version": {"resource": pack_format}})
            )
        archive.writestr("assets/minecraft/textures/entity/steve.png", b"")
        if modern:
            archive.writestr("assets/minecraft/textures/entity/player/wide/steve.png", b"")
    return store


def options_packs(store: Store, version_id: str) -> list:
    path = store.instance_dir(version_id) / "options.txt"
    for line in path.read_text("utf-8").splitlines():
        if line.startswith("resourcePacks:"):
            return json.loads(line[len("resourcePacks:"):])
    return []


class SkinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.store = Store(self.home)
        self.store.ensure()
        self.image = self.home / "skin.png"
        self.image.write_bytes(make_png())

    def test_reads_png_size(self) -> None:
        self.assertEqual(skinmod.read_png_size(self.image), (64, 64))
        legacy = self.home / "legacy.png"
        legacy.write_bytes(make_png(64, 32))
        self.assertEqual(skinmod.read_png_size(legacy), (64, 32))

    def test_rejects_non_png_and_bad_sizes(self) -> None:
        text = self.home / "notes.txt"
        text.write_text("not an image", "utf-8")
        with self.assertRaises(skinmod.SkinError):
            skinmod.read_png_size(text)
        small = self.home / "small.png"
        small.write_bytes(make_png(32, 32))
        with self.assertRaises(skinmod.SkinError) as caught:
            skinmod.read_png_size(small)
        self.assertIn("64x64", str(caught.exception))

    def test_pack_format_comes_from_the_jar(self) -> None:
        make_version(self.store, pack_format=9)
        self.assertEqual(skinmod.pack_format(self.store, "1.19.2"), 9)
        make_version(self.store, "1.21.4", pack_format=46, modern=True)
        self.assertEqual(skinmod.pack_format(self.store, "1.21.4"), 46)

    def test_pack_format_falls_back_to_release_date(self) -> None:
        make_version(self.store, "1.7.10", jar_version=False, release="2014-06-25T00:00:00+00:00")
        self.assertEqual(skinmod.pack_format(self.store, "1.7.10"), 1)
        make_version(self.store, "1.19.2x", jar_version=False, release="2022-08-05T11:55:20+00:00")
        self.assertEqual(skinmod.pack_format(self.store, "1.19.2x"), 9)
        make_version(self.store, "1.21.4x", jar_version=False, release="2024-12-03T10:12:27+00:00")
        self.assertEqual(skinmod.pack_format(self.store, "1.21.4x"), 46)

    def test_detects_layout(self) -> None:
        make_version(self.store, "1.19.2")
        self.assertEqual(skinmod.detect_layout(self.store, "1.19.2"), "legacy")
        make_version(self.store, "1.21.4", pack_format=46, modern=True)
        self.assertEqual(skinmod.detect_layout(self.store, "1.21.4"), "modern")

    def test_install_builds_pack_and_enables_it(self) -> None:
        make_version(self.store)
        state = skinmod.install(self.store, "1.19.2", self.image)
        self.assertTrue(state["enabled"])
        self.assertEqual(state["pack_format"], 9)
        self.assertEqual(state["layout"], "legacy")
        self.assertEqual(state["model"], "both")
        self.assertEqual(state["textures"], 20)
        self.assertEqual(state["image_size"], [64, 64])

        packs = options_packs(self.store, "1.19.2")
        self.assertIn("vanilla", packs)
        self.assertIn(PACK_ID, packs)

        pack = Path(state["pack"])
        self.assertTrue(pack.is_file())
        with zipfile.ZipFile(pack) as archive:
            names = archive.namelist()
            meta = json.loads(archive.read("pack.mcmeta").decode("utf-8"))
        self.assertEqual(meta["pack"]["pack_format"], 9)
        self.assertIn("assets/minecraft/textures/entity/steve.png", names)
        self.assertIn("assets/minecraft/textures/entity/alex.png", names)
        self.assertIn("assets/minecraft/textures/entity/player/wide/steve.png", names)
        self.assertIn("assets/minecraft/textures/entity/player/slim/alex.png", names)

    def test_install_preserves_unrelated_options(self) -> None:
        make_version(self.store)
        options = self.store.instance_dir("1.19.2") / "options.txt"
        options.parent.mkdir(parents=True, exist_ok=True)
        options.write_text(
            'fov:0.5\nresourcePacks:["vanilla", "file/other.zip"]\n'
            'incompatibleResourcePacks:["file/mcmgr-default-skin.zip"]\n',
            "utf-8",
        )
        skinmod.install(self.store, "1.19.2", self.image)
        text = options.read_text("utf-8")
        self.assertIn("fov:0.5", text)
        packs = options_packs(self.store, "1.19.2")
        self.assertEqual(packs, ["vanilla", "file/other.zip", PACK_ID])
        for line in text.splitlines():
            if line.startswith("incompatibleResourcePacks:"):
                self.assertNotIn(PACK_ID, json.loads(line[len("incompatibleResourcePacks:"):]))

    def test_slim_model_only_touches_slim_textures(self) -> None:
        make_version(self.store, modern=True)
        state = skinmod.install(self.store, "1.19.2", self.image, model="slim")
        self.assertEqual(state["textures"], 10)
        with zipfile.ZipFile(state["pack"]) as archive:
            names = archive.namelist()
        self.assertIn("assets/minecraft/textures/entity/alex.png", names)
        self.assertIn("assets/minecraft/textures/entity/player/slim/steve.png", names)
        self.assertNotIn("assets/minecraft/textures/entity/steve.png", names)
        self.assertNotIn("assets/minecraft/textures/entity/player/wide/steve.png", names)

    def test_remove_deletes_pack_and_deselects_it(self) -> None:
        make_version(self.store)
        state = skinmod.install(self.store, "1.19.2", self.image)
        self.assertTrue(skinmod.remove(self.store, "1.19.2"))
        self.assertFalse(Path(state["pack"]).exists())
        self.assertNotIn(PACK_ID, options_packs(self.store, "1.19.2"))
        self.assertIsNone(skinmod.info(self.store, "1.19.2"))
        self.assertFalse(skinmod.remove(self.store, "1.19.2"))

    def test_install_requires_an_installed_version(self) -> None:
        with self.assertRaises(skinmod.SkinError) as caught:
            skinmod.install(self.store, "9.9.9", self.image)
        self.assertIn("not installed", str(caught.exception))

    def test_cli_install_show_clear(self) -> None:
        make_version(self.store)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root", str(self.home), "skin", "1.19.2", "--file", str(self.image)])
        self.assertEqual(code, 0)
        self.assertIn("default character skin for 1.19.2", out.getvalue())
        self.assertIn("options : enabled", out.getvalue())

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root", str(self.home), "skin", "1.19.2", "--show", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["enabled"])

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root", str(self.home), "skin", "1.19.2", "--clear"])
        self.assertEqual(code, 0)
        self.assertIn("removed", out.getvalue())

    def test_cli_rejects_a_bad_image(self) -> None:
        make_version(self.store)
        bad = self.home / "bad.png"
        bad.write_bytes(make_png(10, 10))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["--root", str(self.home), "skin", "1.19.2", "--file", str(bad)])
        self.assertEqual(code, 1)
        self.assertIn("64x64", err.getvalue())

    def test_name_alias_for_launch_and_config(self) -> None:
        parser = build_parser()
        launch = parser.parse_args(["launch", "1.19.2", "--name", "Alex"])
        self.assertEqual(launch.username, "Alex")
        config = parser.parse_args(["config", "1.19.2", "--name", "Alex"])
        self.assertEqual(config.username, "Alex")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
