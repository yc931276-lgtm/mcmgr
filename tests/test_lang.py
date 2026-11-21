"""Offline tests for system-language selection and options.txt handling."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mcmgr import cli, lang
from mcmgr.paths import Store

MODERN_LANGS = ("zh_cn.json", "zh_tw.json", "en_us.json", "en_gb.json", "ja_jp.json")
LEGACY_LANGS = ("zh_CN.lang", "zh_TW.lang", "en_US.lang", "en_GB.lang")


def make_store(
    directory: str,
    version_id: str = "1.19.2",
    index_id: str = "1.19",
    lang_files: tuple[str, ...] = MODERN_LANGS,
) -> Store:
    store = Store(directory)
    store.ensure()
    store.version_dir(version_id).mkdir(parents=True, exist_ok=True)
    store.version_json_path(version_id).write_text(
        json.dumps(
            {
                "id": version_id,
                "assetIndex": {"id": index_id, "url": "https://example.invalid/index.json"},
                "releaseTime": "2022-08-05T12:00:00+00:00",
            }
        ),
        "utf-8",
    )
    objects = {f"minecraft/lang/{name}": {"hash": "0" * 40, "size": 1} for name in lang_files}
    objects["minecraft/sounds.json"] = {"hash": "1" * 40, "size": 1}
    store.index_path(index_id).write_text(json.dumps({"objects": objects}), "utf-8")
    return store


class SystemLocaleTests(unittest.TestCase):
    def test_lang_environment_variable(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
            self.assertEqual(lang.system_locale(), "zh_CN")

    def test_lc_all_wins_and_encoding_is_stripped(self) -> None:
        environ = {"LANG": "en_US.UTF-8", "LC_ALL": "ja_JP.UTF-8", "LC_MESSAGES": "fr_FR.UTF-8"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual(lang.system_locale(), "ja_JP")

    def test_language_list_is_used_before_lang(self) -> None:
        environ = {"LANG": "C.UTF-8", "LANGUAGE": "pt_BR:en_US"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual(lang.system_locale(), "pt_BR")

    def test_posix_locale_has_no_mapping(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "C.UTF-8"}, clear=True), mock.patch.object(
            lang.localemod, "getdefaultlocale", return_value=(None, None)
        ):
            self.assertIsNone(lang.system_locale())

    def test_hyphen_and_modifier_are_normalised(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "sr-RS@latin.UTF-8"}, clear=True):
            self.assertEqual(lang.system_locale(), "sr_RS")


class CodeSelectionTests(unittest.TestCase):
    def test_default_code_uses_version_style(self) -> None:
        self.assertEqual(lang.default_code("zh_CN", "1.7.10"), "zh_CN")
        self.assertEqual(lang.default_code("zh_CN", "1.12.2"), "zh_CN")
        self.assertEqual(lang.default_code("zh_CN", "1.19.2"), "zh_cn")
        self.assertEqual(lang.default_code("en_GB", "1.21.4"), "en_gb")

    def test_default_region_for_bare_language(self) -> None:
        self.assertEqual(lang.default_code("zh", "1.19.2"), "zh_cn")
        self.assertEqual(lang.default_code("en", "1.7.10"), "en_US")
        self.assertIsNone(lang.default_code("xx", "1.19.2"))

    def test_pick_exact_match(self) -> None:
        codes = ["en_us", "en_gb", "zh_cn", "zh_tw"]
        self.assertEqual(lang.pick("zh_CN", codes), "zh_cn")
        self.assertEqual(lang.pick("zh_TW", codes), "zh_tw")
        self.assertEqual(lang.pick("en_GB", codes), "en_gb")

    def test_pick_prefers_the_language_default_region(self) -> None:
        codes = ["en_au", "en_gb", "en_us", "zh_tw", "zh_cn"]
        self.assertEqual(lang.pick("en", codes), "en_us")
        self.assertEqual(lang.pick("zh", codes), "zh_cn")

    def test_pick_returns_none_for_an_unknown_language(self) -> None:
        self.assertIsNone(lang.pick("fr_FR", ["en_us", "zh_cn"]))

    def test_available_reads_the_asset_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            codes = lang.available(store, "1.19.2")
            self.assertEqual(codes, ["en_gb", "en_us", "ja_jp", "zh_cn", "zh_tw"])

    def test_available_legacy_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, version_id="1.7.10", index_id="1.7.10", lang_files=LEGACY_LANGS)
            codes = lang.available(store, "1.7.10")
            self.assertIn("zh_CN", codes)
            self.assertIn("en_US", codes)


class OptionsTests(unittest.TestCase):
    def test_write_preserves_other_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            path = lang.options_path(store, "1.19.2")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fov:0.5\nlang:en_us\nguiScale:2\n", "utf-8")
            lang.write(store, "1.19.2", "zh_cn")
            lines = path.read_text("utf-8").splitlines()
            self.assertEqual(lines, ["fov:0.5", "lang:zh_cn", "guiScale:2"])
            self.assertEqual(lang.current(store, "1.19.2"), "zh_cn")

    def test_write_appends_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            lang.write(store, "1.19.2", "zh_cn")
            self.assertEqual(lang.current(store, "1.19.2"), "zh_cn")

    def test_clear_removes_the_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            path = lang.options_path(store, "1.19.2")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("lang:zh_cn\nfov:0.5\n", "utf-8")
            self.assertTrue(lang.clear(store, "1.19.2"))
            self.assertIsNone(lang.current(store, "1.19.2"))
            self.assertIn("fov:0.5", path.read_text("utf-8"))
            self.assertFalse(lang.clear(store, "1.19.2"))

    def test_canonical_normalises_the_region_case(self) -> None:
        self.assertEqual(lang.canonical("zh_cn", "1.7.10"), "zh_CN")
        self.assertEqual(lang.canonical("zh_CN", "1.19.2"), "zh_cn")
        self.assertEqual(lang.canonical("zh_cn", "1.19.2", ["zh_cn", "en_us"]), "zh_cn")
        with self.assertRaises(lang.LangError):
            lang.canonical("fr_fr", "1.19.2", ["zh_cn", "en_us"])
        with self.assertRaises(lang.LangError):
            lang.canonical("not a code", "1.19.2")


class DefaultLanguageTests(unittest.TestCase):
    def test_set_language_from_system_locale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
                code = lang.set_language(store, "1.19.2", "system")
            self.assertEqual(code, "zh_cn")
            self.assertEqual(lang.current(store, "1.19.2"), "zh_cn")

    def test_set_language_legacy_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, version_id="1.7.10", index_id="1.7.10", lang_files=LEGACY_LANGS)
            with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
                code = lang.set_language(store, "1.7.10", "system")
            self.assertEqual(code, "zh_CN")
            self.assertEqual(lang.current(store, "1.7.10"), "zh_CN")

    def test_ensure_default_sets_only_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
                self.assertEqual(lang.ensure_default(store, "1.19.2"), ("zh_cn", "zh_CN"))
                self.assertIsNone(lang.ensure_default(store, "1.19.2"))
            # A language chosen later (in game or with --set) must never be overwritten.
            lang.write(store, "1.19.2", "en_us")
            with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
                self.assertIsNone(lang.ensure_default(store, "1.19.2"))
            self.assertEqual(lang.current(store, "1.19.2"), "en_us")

    def test_unknown_system_language_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            with mock.patch.dict(os.environ, {"LANG": "xx_YY.UTF-8"}, clear=True):
                self.assertIsNone(lang.ensure_default(store, "1.19.2"))
            self.assertIsNone(lang.current(store, "1.19.2"))

    def test_info_reports_system_and_available_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
                info = lang.info(store, "1.19.2")
            self.assertEqual(info["system_locale"], "zh_CN")
            self.assertEqual(info["suggested"], "zh_cn")
            self.assertEqual(info["available"], 5)
            self.assertIsNone(info["language"])


class LangCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = make_store(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["--root", self.tempdir.name, *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_show_prints_the_detected_language(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
            code, out, _ = self.run_cli("lang", "1.19.2", "--show")
        self.assertEqual(code, 0)
        self.assertIn("zh_CN -> zh_cn", out)
        self.assertIn("language : (not set", out)

    def test_set_system_writes_options(self) -> None:
        with mock.patch.dict(os.environ, {"LANG": "zh_CN.UTF-8"}, clear=True):
            code, out, _ = self.run_cli("lang", "1.19.2", "--set", "system")
        self.assertEqual(code, 0)
        self.assertIn("language for 1.19.2: zh_cn", out)
        self.assertEqual(lang.current(self.store, "1.19.2"), "zh_cn")

    def test_set_explicit_code(self) -> None:
        code, out, _ = self.run_cli("lang", "1.19.2", "--set", "en_gb")
        self.assertEqual(code, 0)
        self.assertIn("en_gb", out)
        self.assertEqual(lang.current(self.store, "1.19.2"), "en_gb")

    def test_unsupported_code_exits_with_an_error(self) -> None:
        code, _, err = self.run_cli("lang", "1.19.2", "--set", "fr_fr")
        self.assertEqual(code, 1)
        self.assertIn("unsupported language", err)

    def test_list_prints_codes(self) -> None:
        code, out, _ = self.run_cli("lang", "1.19.2", "--list")
        self.assertEqual(code, 0)
        self.assertIn("zh_cn", out.splitlines())
        self.assertIn("en_us", out.splitlines())

    def test_json_output(self) -> None:
        code, out, _ = self.run_cli("lang", "1.19.2", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["version"], "1.19.2")
        self.assertEqual(data["suggested"], "zh_cn")

    def test_clear(self) -> None:
        lang.write(self.store, "1.19.2", "zh_cn")
        code, out, _ = self.run_cli("lang", "1.19.2", "--clear")
        self.assertEqual(code, 0)
        self.assertIn("removed", out)
        self.assertIsNone(lang.current(self.store, "1.19.2"))


if __name__ == "__main__":
    unittest.main()
