"""Download tests against a local HTTP server (no internet needed)."""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import io
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from mcmgr import net
from mcmgr.net import download, plan_segments, probe_size


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    payload = b""
    support_ranges = True

    def log_message(self, *args):  # silence test output
        pass

    def do_GET(self):  # noqa: N802 - http.server API
        total = len(self.payload)
        header = self.headers.get("Range")
        if self.support_ranges and header and header.startswith("bytes="):
            first, _, last = header[len("bytes="):].partition("-")
            start = int(first) if first else 0
            end = int(last) if last else total - 1
            end = min(end, total - 1)
            body = self.payload[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(total))
        if self.support_ranges:
            self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(self.payload)


class _QuietServer(http.server.ThreadingHTTPServer):
    """Server that ignores aborted connections (normal in fallback tests)."""

    def handle_error(self, request, client_address) -> None:  # noqa: D102
        pass


class LocalServer:
    """Tiny threaded HTTP server serving one payload."""

    def __init__(self, payload: bytes, *, support_ranges: bool = True) -> None:
        handler = type(
            "Handler",
            (_RangeHandler,),
            {"payload": payload, "support_ranges": support_ranges},
        )
        self.httpd = _QuietServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/file.bin"

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class SegmentPlanTests(unittest.TestCase):
    def test_small_file_is_one_segment(self) -> None:
        self.assertEqual(plan_segments(1000, 4), [(0, 999)])
        self.assertEqual(plan_segments(0, 4), [])

    def test_segments_cover_whole_file(self) -> None:
        total = 10 * (1 << 20) + 7
        segments = plan_segments(total, 4)
        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0][0], 0)
        self.assertEqual(segments[-1][1], total - 1)
        for (_, end), (start, _) in zip(segments, segments[1:]):
            self.assertEqual(start, end + 1)


class SegmentedDownloadTests(unittest.TestCase):
    def test_multi_threaded_download(self) -> None:
        payload = os.urandom(3 * (1 << 20) + 123)
        digest = hashlib.sha1(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "client.jar"
            with LocalServer(payload) as url:
                self.assertEqual(probe_size(url), len(payload))
                self.assertTrue(download(url, target, digest, len(payload), threads=4))
            self.assertEqual(target.read_bytes(), payload)
            leftovers = sorted(path.name for path in Path(directory).iterdir())
            self.assertEqual(leftovers, ["client.jar"])

    def test_falls_back_when_server_has_no_range_support(self) -> None:
        payload = os.urandom(2 * (1 << 20))
        digest = hashlib.sha1(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "file.bin"
            with LocalServer(payload, support_ranges=False) as url:
                self.assertIsNone(probe_size(url))
                self.assertTrue(download(url, target, digest, len(payload), threads=4))
            self.assertEqual(target.read_bytes(), payload)

    def test_existing_file_is_skipped(self) -> None:
        payload = b"x" * (1 << 20)
        digest = hashlib.sha1(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "file.bin"
            target.write_bytes(payload)
            self.assertFalse(download("http://127.0.0.1:1/nope", target, digest, len(payload)))


class FallbackTests(unittest.TestCase):
    def test_alternate_url_is_used_when_primary_fails(self) -> None:
        payload = os.urandom(64 * 1024)
        digest = hashlib.sha1(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "file.bin"
            with LocalServer(payload) as url:
                self.assertTrue(
                    download(
                        "http://127.0.0.1:1/file.bin",
                        target,
                        digest,
                        len(payload),
                        retries=1,
                        alternates=[url],
                    )
                )
            self.assertEqual(target.read_bytes(), payload)

    def test_alternates_are_tried_in_order(self) -> None:
        payload = b"payload" * 1024
        digest = hashlib.sha1(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "file.bin"
            with LocalServer(payload) as url:
                self.assertTrue(
                    download(
                        "http://127.0.0.1:1/a.bin",
                        target,
                        digest,
                        len(payload),
                        retries=1,
                        alternates=["http://127.0.0.1:1/b.bin", url],
                    )
                )
            self.assertEqual(target.read_bytes(), payload)

    def test_dead_proxy_falls_back_to_direct_connection(self) -> None:
        """A configured-but-dead proxy must not block downloads (the 1.7.10 case)."""
        payload = os.urandom(128 * 1024)
        digest = hashlib.sha1(payload).hexdigest()
        net._BYPASS_NOTE_SHOWN = False
        net._FORCE_DIRECT = False
        # urllib caches its first opener, so a fresh process must be simulated
        # for the patched proxy environment to take effect.
        saved_opener = urllib.request._opener
        urllib.request._opener = None
        proxy = "http://127.0.0.1:1"
        env = {
            "HTTP_PROXY": proxy,
            "HTTPS_PROXY": proxy,
            "http_proxy": proxy,
            "https_proxy": proxy,
            "NO_PROXY": "",
            "no_proxy": "",
        }
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "file.bin"
                with LocalServer(payload) as url, mock.patch.dict(os.environ, env):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        self.assertTrue(download(url, target, digest, len(payload), retries=3))
                self.assertEqual(target.read_bytes(), payload)
                self.assertIn("retrying without a proxy", stderr.getvalue())
                self.assertTrue(net._FORCE_DIRECT)
        finally:
            urllib.request._opener = saved_opener
            net._FORCE_DIRECT = False
            net._BYPASS_NOTE_SHOWN = False



if __name__ == "__main__":
    unittest.main()
