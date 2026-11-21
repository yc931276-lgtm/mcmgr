"""URL rewriting for the BMCLAPI (mainland China) mirror."""

from __future__ import annotations

import unittest

from mcmgr import mirror

CLIENT_URL = "https://piston-data.mojang.com/v1/objects/a7e5a6024bfd3cd614625aa05629adf760020304/client.jar"
LIBRARY_URL = "https://libraries.minecraft.net/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar"
ASSET_URL = "https://resources.download.minecraft.net/bd/bdf48ef6b5d0d23bbb02e17d04865216179f510a"


class BmclapiRewriteTests(unittest.TestCase):
    def test_manifest(self) -> None:
        self.assertEqual(
            mirror.bmclapi_url("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"),
            "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json",
        )

    def test_version_json_by_id(self) -> None:
        url = "https://piston-meta.mojang.com/v1/packages/c88775961e316f2be09859c54e13017660ee7770/1.21.4.json"
        self.assertEqual(
            mirror.bmclapi_url(url, version_id="1.21.4"),
            "https://bmclapi2.bangbang93.com/version/1.21.4/json",
        )

    def test_asset_index_keeps_packages_path(self) -> None:
        url = "https://piston-meta.mojang.com/v1/packages/480d8ec8280fe619ae1df49dbe1da6f3a1849c7b/19.json"
        self.assertEqual(
            mirror.bmclapi_url(url, version_id="1.21.4"),
            "https://bmclapi2.bangbang93.com/v1/packages/480d8ec8280fe619ae1df49dbe1da6f3a1849c7b/19.json",
        )

    def test_client_jar(self) -> None:
        self.assertEqual(
            mirror.bmclapi_url(CLIENT_URL, version_id="1.21.4"),
            "https://bmclapi2.bangbang93.com/version/1.21.4/client",
        )
        self.assertEqual(
            mirror.bmclapi_url(CLIENT_URL),
            "https://bmclapi2.bangbang93.com/v1/objects/a7e5a6024bfd3cd614625aa05629adf760020304/client.jar",
        )

    def test_library(self) -> None:
        self.assertEqual(
            mirror.bmclapi_url(LIBRARY_URL),
            "https://bmclapi2.bangbang93.com/maven/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar",
        )

    def test_asset(self) -> None:
        self.assertEqual(
            mirror.bmclapi_url(ASSET_URL),
            "https://bmclapi2.bangbang93.com/assets/bd/bdf48ef6b5d0d23bbb02e17d04865216179f510a",
        )

    def test_unknown_host_is_not_rewritten(self) -> None:
        self.assertIsNone(mirror.bmclapi_url("https://example.com/foo.jar"))
        self.assertIsNone(mirror.bmclapi_url("ftp://piston-meta.mojang.com/x"))


class CandidateOrderTests(unittest.TestCase):
    def test_official_only(self) -> None:
        self.assertEqual(mirror.candidates("official", LIBRARY_URL), [LIBRARY_URL])

    def test_bmclapi_prefers_mirror(self) -> None:
        self.assertEqual(
            mirror.candidates("bmclapi", LIBRARY_URL),
            [mirror.bmclapi_url(LIBRARY_URL), LIBRARY_URL],
        )

    def test_auto_prefers_official(self) -> None:
        self.assertEqual(
            mirror.candidates("auto", LIBRARY_URL),
            [LIBRARY_URL, mirror.bmclapi_url(LIBRARY_URL)],
        )

    def test_unrewritable_url_is_returned_alone(self) -> None:
        self.assertEqual(mirror.candidates("bmclapi", "https://example.com/x"), ["https://example.com/x"])

    def test_invalid_mode(self) -> None:
        with self.assertRaises(ValueError):
            mirror.candidates("cn-mirror", LIBRARY_URL)


if __name__ == "__main__":
    unittest.main()
