"""Tests for the ``mcmgr env`` report (offline)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from mcmgr import __version__, doctor
from mcmgr.cli import main
from mcmgr.paths import Store


class EnvReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = Store(self.tempdir.name)
        self.store.ensure()
        self.discover = mock.patch(
            "mcmgr.doctor.javamod.discover",
            return_value=[("/usr/lib/jvm/java-21-openjdk-amd64/bin/java", 21)],
        )
        self.discover.start()

    def tearDown(self) -> None:
        self.discover.stop()
        self.tempdir.cleanup()

    def test_collect_reports_core_facts(self) -> None:
        report = doctor.collect(self.store)
        self.assertEqual(report["mcmgr"]["version"], __version__)
        self.assertEqual(report["store"]["root"], str(self.store.root))
        self.assertTrue(report["store"]["writable"])
        self.assertEqual(report["java"]["runtimes"][0]["major"], 21)
        self.assertEqual(report["installed"], [])
        self.assertIn("build", report["mcmgr"])

    def test_collect_lists_installed_versions_and_configs(self) -> None:
        record = self.store.install_record("1.21.4")
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text("{}", "utf-8")
        self.store.launch_config("1.21.4").write_text("{}", "utf-8")
        report = doctor.collect(self.store)
        self.assertEqual(report["installed"], ["1.21.4"])
        self.assertEqual(report["launch_configs"], ["1.21.4"])

    def test_render_mentions_version_store_and_java(self) -> None:
        text = doctor.render(doctor.collect(self.store))
        self.assertIn(f"mcmgr {__version__}", text)
        self.assertIn(str(self.store.root), text)
        self.assertIn("Java 21", text)

    def test_build_info_falls_back_to_source_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            source = package / "mod.py"
            source.write_text("x = 1\n", "utf-8")
            os.utime(source, (1_700_000_000, 1_700_000_000))
            info = doctor.build_info(package, stamp_path=package / "missing.json")
            self.assertEqual(info["origin"], "source-mtime")
            self.assertAlmostEqual(info["epoch"], 1_700_000_000, delta=2)
            self.assertFalse(info["stale"])
            self.assertIn("newest source file", doctor._format_built(info))

    def test_build_info_prefers_stamp_and_detects_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            source = package / "mod.py"
            source.write_text("x = 1\n", "utf-8")
            os.utime(source, (time.time(), time.time()))
            stamp = package / "_build.json"
            stamp.write_text(
                json.dumps(
                    {
                        "version": "0.4.0",
                        "built_at": "2026-01-01T00:00:00+08:00",
                        "built_epoch": 1_700_000_000,
                        "commit": "abc1234",
                    }
                ),
                "utf-8",
            )
            info = doctor.build_info(package, stamp_path=stamp)
            self.assertEqual(info["origin"], "stamp")
            self.assertTrue(info["stale"])
            self.assertEqual(info["commit"], "abc1234")
            formatted = doctor._format_built(info)
            self.assertIn("2026-01-01T00:00:00+08:00", formatted)
            self.assertIn("commit abc1234", formatted)
            self.assertIn("sources newer than stamp", formatted)

            os.utime(source, (1_600_000_000, 1_600_000_000))
            info = doctor.build_info(package, stamp_path=stamp)
            self.assertFalse(info["stale"])

    def test_frozen_executable_is_reported_as_its_own_build(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True):
            report = doctor.collect(self.store)
        self.assertTrue(report["mcmgr"]["frozen"])
        self.assertIn("frozen executable", report["mcmgr"]["build"])
        self.assertEqual(report["mcmgr"]["source"], str(Path(sys.executable)))

    def test_collect_includes_build_time(self) -> None:
        report = doctor.collect(self.store)
        self.assertIn("built_at", report["mcmgr"])
        self.assertIn("build_origin", report["mcmgr"])
        self.assertIn("built     :", doctor.render(report))

    def test_cli_env_json(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--root", self.tempdir.name, "env", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(buffer.getvalue())
        self.assertEqual(data["store"]["root"], str(self.store.root))
        self.assertEqual(data["mcmgr"]["version"], __version__)

    def test_cli_env_text(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--root", self.tempdir.name, "env"])
        self.assertEqual(code, 0)
        self.assertIn("store", buffer.getvalue())
        self.assertIn("Java 21", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
