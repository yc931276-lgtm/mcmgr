"""Offline unit tests: no network access required."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcmgr import launch as launchmod
from mcmgr import meta
from mcmgr.cli import _parse_memory, build_parser
from mcmgr.installer import library_plan, verify_version
from mcmgr.paths import Store
from mcmgr.rules import os_name, rules_allow
from mcmgr.settings import LaunchSettings


def make_store(directory: str) -> Store:
    store = Store(directory)
    store.ensure()
    return store


class RuleTests(unittest.TestCase):
    def test_empty_rules_allow(self) -> None:
        self.assertTrue(rules_allow(None))
        self.assertTrue(rules_allow([]))

    def test_os_specific_allow(self) -> None:
        self.assertFalse(rules_allow([{"action": "allow", "os": {"name": "__nope__"}}]))
        self.assertTrue(rules_allow([{"action": "allow", "os": {"name": os_name()}}]))

    def test_disallow_then_allow(self) -> None:
        rules = [{"action": "disallow", "os": {"name": "__nope__"}}, {"action": "allow"}]
        self.assertTrue(rules_allow(rules))

    def test_features(self) -> None:
        rules = [{"action": "allow", "features": {"is_demo_user": True}}]
        self.assertFalse(rules_allow(rules, {}))
        self.assertTrue(rules_allow(rules, {"is_demo_user": True}))


class LibraryPlanTests(unittest.TestCase):
    def test_legacy_natives_go_to_natives_list(self) -> None:
        version = {
            "libraries": [
                {
                    "name": "org.lwjgl.lwjgl:lwjgl:2.9.4",
                    "downloads": {
                        "artifact": {"path": "org/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4.jar", "url": "u", "sha1": "a"},
                        "classifiers": {
                            f"natives-{os_name()}": {
                                "path": f"org/lwjgl/lwjgl/2.9.4/lwjgl-2.9.4-natives-{os_name()}.jar",
                                "url": "u2",
                                "sha1": "b",
                            }
                        },
                    },
                    "natives": {os_name(): f"natives-{os_name()}"},
                }
            ]
        }
        artifacts, natives = library_plan(version)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(len(natives), 1)
        self.assertIn("natives", natives[0]["path"])

    def test_rule_filtered_library_is_skipped(self) -> None:
        version = {
            "libraries": [
                {
                    "name": "x",
                    "rules": [{"action": "allow", "os": {"name": "__nope__"}}],
                    "downloads": {"artifact": {"path": "x.jar", "url": "u", "sha1": "a"}},
                }
            ]
        }
        self.assertEqual(library_plan(version), ([], []))


class LaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = make_store(self.tempdir.name)
        self.vid = "1.0-test"
        version = {
            "id": self.vid,
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "javaVersion": {"majorVersion": 17},
            "assetIndex": {"id": "5", "url": "https://example.invalid/index.json"},
            "libraries": [
                {
                    "name": "lib",
                    "downloads": {"artifact": {"path": "lib/lib.jar", "url": "u", "sha1": "a"}},
                }
            ],
            "arguments": {
                "jvm": [
                    "-Djava.library.path=${natives_directory}",
                    "-cp",
                    "${classpath}",
                ],
                "game": [
                    "--username",
                    "${auth_player_name}",
                    "--version",
                    "${version_name}",
                    "--uuid",
                    "${auth_uuid}",
                    {"rules": [{"action": "allow", "features": {"is_demo_user": True}}], "value": "--demo"},
                ],
            },
        }
        path = self.store.version_json_path(self.vid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(version), "utf-8")
        self.store.client_jar(self.vid).write_bytes(b"jar")
        self.store.library_path("lib/lib.jar").parent.mkdir(parents=True, exist_ok=True)
        self.store.library_path("lib/lib.jar").write_bytes(b"lib")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_offline_uuid_matches_java(self) -> None:
        # java.util.UUID.nameUUIDFromBytes("OfflinePlayer:Player")
        self.assertEqual(launchmod.offline_uuid("Player"), "a01e3843-e521-3998-958a-f459800e4d11")
        self.assertEqual(launchmod.offline_uuid("Player")[14], "3")

    def test_build_command_substitutes_placeholders(self) -> None:
        with mock.patch.object(launchmod.javamod, "find_java", return_value=("/usr/bin/java", 21)):
            plan = launchmod.build_command(self.store, self.vid, username="Steve", memory="2G")
        argv = plan.argv
        self.assertEqual(argv[0], "-Xmx2G")
        self.assertIn("net.minecraft.client.main.Main", argv)
        self.assertNotIn("${auth_player_name}", argv)
        self.assertEqual(argv[argv.index("--username") + 1], "Steve")
        self.assertNotIn("--demo", argv)
        classpath = argv[argv.index("-cp") + 1]
        self.assertIn(str(self.store.client_jar(self.vid)), classpath.split(":"))
        self.assertIn(str(self.store.library_path("lib/lib.jar")), classpath.split(":"))
        self.assertEqual(plan.cwd, self.store.instance_dir(self.vid))

    def test_legacy_arguments_are_substituted(self) -> None:
        version = {
            "id": "1.7.10-test",
            "type": "release",
            "mainClass": "net.minecraft.client.main.Main",
            "assetIndex": {"id": "1.7.10", "url": "https://example.invalid/x.json"},
            "libraries": [],
            "minecraftArguments": (
                "--username '${auth_player_name}' --version '${version_name}' "
                "--uuid '${auth_uuid}' --userType '${user_type}' --assetsDir '${assets_root}'"
            ),
        }
        path = self.store.version_json_path("1.7.10-test")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(version), "utf-8")
        self.store.client_jar("1.7.10-test").write_bytes(b"jar")
        with mock.patch.object(launchmod.javamod, "find_java", return_value=("/usr/bin/java", 8)):
            plan = launchmod.build_command(self.store, "1.7.10-test", username="Alex")
        self.assertNotIn("${auth_player_name}", plan.argv)
        self.assertEqual(plan.argv[plan.argv.index("--username") + 1], "Alex")
        self.assertEqual(plan.argv[plan.argv.index("--userType") + 1], "legacy")
        self.assertEqual(plan.warnings, [])

    def test_uuid_override_and_extra_args(self) -> None:
        with mock.patch.object(launchmod.javamod, "find_java", return_value=("/usr/bin/java", 21)):
            plan = launchmod.build_command(
                self.store,
                self.vid,
                username="Steve",
                uuid_override="0123456789ABCDEF0123456789ABCDEF",
                memory="2G",
                jvm_args=["-Dfoo=bar"],
                game_args=["--fullscreen"],
            )
        self.assertEqual(plan.argv[:2], ["-Xmx2G", "-Dfoo=bar"])
        self.assertEqual(plan.argv[plan.argv.index("--uuid") + 1], "01234567-89ab-cdef-0123-456789abcdef")
        self.assertEqual(plan.argv[-1], "--fullscreen")

    def test_uuid_offline_word_keeps_derived_value(self) -> None:
        with mock.patch.object(launchmod.javamod, "find_java", return_value=("/usr/bin/java", 21)):
            plan = launchmod.build_command(self.store, self.vid, username="Steve", uuid_override="offline")
        self.assertEqual(plan.argv[plan.argv.index("--uuid") + 1], launchmod.offline_uuid("Steve"))

    def test_invalid_uuid_is_rejected(self) -> None:
        with self.assertRaises(launchmod.LaunchError):
            launchmod.normalize_uuid("not-a-uuid")
        self.assertEqual(launchmod.normalize_uuid("OFFLINE"), "offline")
        self.assertEqual(
            launchmod.normalize_uuid("01234567-89ab-cdef-0123-456789abcdef"),
            "01234567-89ab-cdef-0123-456789abcdef",
        )

    def test_missing_client_jar_is_an_error(self) -> None:
        self.store.client_jar(self.vid).unlink()
        with mock.patch.object(launchmod.javamod, "find_java", return_value=("/usr/bin/java", 21)):
            with self.assertRaises(launchmod.LaunchError):
                launchmod.build_command(self.store, self.vid)

    def test_verify_reports_missing_library(self) -> None:
        self.store.library_path("lib/lib.jar").unlink()
        problems = verify_version(self.store, self.vid)
        self.assertTrue(any("library" in problem for problem in problems))


class CliTests(unittest.TestCase):
    def test_memory_parsing(self) -> None:
        self.assertEqual(_parse_memory("2G"), "2G")
        self.assertEqual(_parse_memory("2048m"), "2048M")
        self.assertEqual(_parse_memory("512"), "512M")
        with self.assertRaises(Exception):
            _parse_memory("lots")

    def test_parser_accepts_subcommands(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "1.21.4"])
        self.assertEqual(args.command, "install")
        self.assertEqual(args.version, "1.21.4")
        args, extras = parser.parse_known_args(["launch", "1.21.4", "-u", "Alex", "--", "--fullscreen"])
        self.assertEqual(args.username, "Alex")
        if extras and extras[0] == "--":
            extras = extras[1:]
        self.assertIn("--fullscreen", extras)


class ErrorHandlingTests(unittest.TestCase):
    def test_download_error_is_reported_without_traceback(self) -> None:
        from mcmgr.cli import main
        from mcmgr.net import DownloadError

        buffer = io.StringIO()
        with mock.patch("mcmgr.cli.install_version", side_effect=DownloadError("boom")):
            with mock.patch("mcmgr.cli._resolve", return_value="1.7.10"):
                with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                    self.assertEqual(main(["install", "1.7.10"]), 1)


class SettingsTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "1.21.4.json"
            saved = LaunchSettings(
                username="Alex",
                uuid="01234567-89ab-cdef-0123-456789abcdef",
                memory="4G",
                width=1280,
                height=720,
                jvm_args=["-Dfoo=bar"],
                game_args=["--fullscreen"],
            )
            saved.save(path)
            loaded = LaunchSettings.load(path)
            self.assertEqual(loaded, saved)

    def test_missing_and_broken_files_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            self.assertTrue(LaunchSettings.load(path).is_empty())
            path.write_text("{not json", "utf-8")
            self.assertTrue(LaunchSettings.load(path).is_empty())
            path.write_text('{"width": "1280", "jvm_args": ["", "-Xfoo"], "bogus": 1}', "utf-8")
            loaded = LaunchSettings.load(path)
            self.assertEqual(loaded.width, 1280)
            self.assertEqual(loaded.jvm_args, ["-Xfoo"])

    def test_is_empty(self) -> None:
        self.assertTrue(LaunchSettings().is_empty())
        self.assertFalse(LaunchSettings(username="Alex").is_empty())


class ConfigCommandTests(unittest.TestCase):
    def run_cli(self, argv: list[str]):
        from mcmgr.cli import main

        buffer = io.StringIO()
        with mock.patch("mcmgr.cli._resolve", return_value="1.21.4"):
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                code = main(argv)
        return code, buffer.getvalue()

    def test_config_saves_and_shows_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(
                [
                    "--root",
                    directory,
                    "config",
                    "1.21.4",
                    "-u",
                    "Alex",
                    "--uuid",
                    "0123456789ABCDEF0123456789ABCDEF",
                    "--memory",
                    "3G",
                    "--jvm-arg=-Dfoo=bar",
                    "--game-arg=--fullscreen",
                    "--width",
                    "1280",
                    "--height",
                    "720",
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("saved launch settings", output)
            data = json.loads((Path(directory) / "launch" / "1.21.4.json").read_text("utf-8"))
            self.assertEqual(data["username"], "Alex")
            self.assertEqual(data["uuid"], "01234567-89ab-cdef-0123-456789abcdef")
            self.assertEqual(data["memory"], "3G")
            self.assertEqual(data["jvm_args"], ["-Dfoo=bar"])
            self.assertEqual(data["game_args"], ["--fullscreen"])
            self.assertEqual(data["width"], 1280)

            code, output = self.run_cli(["--root", directory, "config", "1.21.4", "--show"])
            self.assertEqual(code, 0)
            self.assertIn("Alex", output)
            self.assertIn("1280x720", output)
            self.assertIn("-Dfoo=bar", output)

    def test_config_clears_fields_and_args(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.run_cli(["--root", directory, "config", "1.21.4", "-u", "Alex", "--jvm-arg=-Xfoo"])
            self.run_cli(["--root", directory, "config", "1.21.4", "--unset", "username", "--clear-jvm-args"])
            data = json.loads((Path(directory) / "launch" / "1.21.4.json").read_text("utf-8"))
            self.assertNotIn("username", data)
            self.assertNotIn("jvm_args", data)

    def test_config_rejects_bad_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(["--root", directory, "config", "1.21.4", "--uuid", "nope"])
            self.assertEqual(code, 1)
            self.assertIn("invalid player UUID", output)

    def test_parser_accepts_config_and_launch_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["config", "1.21.4", "-u", "Alex", "--jvm-arg=-Dfoo=bar", "--game-arg=--fullscreen"]
        )
        self.assertEqual(args.username, "Alex")
        self.assertEqual(args.jvm_arg, ["-Dfoo=bar"])
        self.assertEqual(args.game_arg, ["--fullscreen"])
        args, extras = parser.parse_known_args(
            ["launch", "1.21.4", "--uuid", "01234567-89ab-cdef-0123-456789abcdef", "--jvm-arg=-Xfoo", "--save", "--", "--fullscreen"]
        )
        self.assertEqual(args.jvm_arg, ["-Xfoo"])
        self.assertTrue(args.save)
        self.assertEqual(extras, ["--", "--fullscreen"])


class ManifestTests(unittest.TestCase):
    def test_filter_and_alias(self) -> None:
        manifest = {
            "latest": {"release": "1.21.4", "snapshot": "25w01a"},
            "versions": [
                {"id": "1.21.4", "type": "release"},
                {"id": "25w01a", "type": "snapshot"},
                {"id": "b1.7.3", "type": "old_beta"},
            ],
        }
        self.assertEqual([v["id"] for v in meta.list_versions(manifest)], ["1.21.4"])
        self.assertEqual([v["id"] for v in meta.list_versions(manifest, "all")], ["1.21.4", "25w01a", "b1.7.3"])
        self.assertEqual(meta.resolve_version_id(manifest, "latest"), "1.21.4")
        self.assertEqual(meta.resolve_version_id(manifest, "latest-snapshot"), "25w01a")


if __name__ == "__main__":
    unittest.main()
