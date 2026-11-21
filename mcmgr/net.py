"""HTTP downloading with hash verification, retries and multi-threaded transfers.

Two independent levels of parallelism:

* :func:`fetch_many` downloads many files at once (``workers``);
* :func:`download` can split a single large file into byte ranges that are
  fetched over several connections (``threads``) using HTTP ``Range`` requests.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Sequence

from .paths import USER_AGENT

CHUNK = 1 << 16
DEFAULT_RETRIES = 4
DEFAULT_TIMEOUT = 30
DEFAULT_WORKERS = 16
DEFAULT_THREADS = 4

# Files smaller than this are not worth splitting across connections.
MIN_SEGMENT_BYTES = 1 << 20

_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


class DownloadError(RuntimeError):
    """A file could not be downloaded or failed verification."""


def _backoff(attempt: int) -> None:
    """Sleep a little longer after every failed attempt (with jitter)."""
    delay = min(4.0, 0.5 * (2 ** (attempt - 1)))
    time.sleep(delay + random.uniform(0.0, 0.3))


_NETWORK_MARKERS = (
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "temporary failure",
    "name or service not known",
    "network is unreachable",
    "no route to host",
    "ssl",
)


def _network_hint(error: Exception, *, direct: bool = False) -> str:
    """A short, actionable hint for connectivity-looking failures."""
    text = str(error).lower()
    if not any(marker in text for marker in _NETWORK_MARKERS):
        return ""
    proxies = proxy_settings()
    hint = "\n  hint: network problem while downloading"
    if proxies:
        if direct:
            hint += (
                f"; proxy env vars are set {proxies} and were bypassed because the proxy refused "
                "connections — unset them if the proxy is not running"
            )
        else:
            hint += f"; proxy env vars are set {proxies} — if that proxy is not running, unset them"
    else:
        hint += " (no proxy env vars are set)"
    hint += "; this command already retries, so running it again is safe."
    return hint


def sha1_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def file_matches(path: Path, sha1: str | None = None, size: int | None = None) -> bool:
    """Whether *path* already contains the wanted file (hash/size check)."""
    try:
        stat = path.stat()
    except OSError:
        return False
    if size is not None and stat.st_size != size:
        return False
    if sha1 is not None and sha1_file(path) != sha1:
        return False
    return True


def _open(url: str, *, timeout: int, headers: dict[str, str] | None = None, direct: bool = False):
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    if direct or _FORCE_DIRECT:
        # Ignore http_proxy/https_proxy: used when a configured proxy refuses
        # connections (e.g. a closed Clash/V2Ray port).
        return _direct_opener().open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


_DIRECT_OPENER: urllib.request.OpenerDirector | None = None
_PROXY_KEYS = {"http_proxy", "https_proxy", "all_proxy"}
_BYPASS_NOTE_SHOWN = False
#: Set once a configured proxy is found to be dead; every later request then
#: skips it instead of paying one failed connection per file.
_FORCE_DIRECT = False


def _direct_opener() -> urllib.request.OpenerDirector:
    global _DIRECT_OPENER
    if _DIRECT_OPENER is None:
        _DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _DIRECT_OPENER


def proxy_settings() -> dict[str, str]:
    """The proxy environment variables currently in effect, if any."""
    return {
        key: value
        for key, value in os.environ.items()
        if key.lower() in _PROXY_KEYS and value
    }


def _is_connection_refused(error: BaseException) -> bool:
    """Whether *error* (or something it wraps) looks like "proxy is not running"."""
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ConnectionRefusedError):
            return True
        if "connection refused" in str(current).lower():
            return True
        for attribute in ("reason", "__cause__", "__context__"):
            inner = getattr(current, attribute, None)
            if isinstance(inner, BaseException):
                pending.append(inner)
    return False


def _force_direct(proxies: dict[str, str]) -> None:
    global _BYPASS_NOTE_SHOWN, _FORCE_DIRECT
    _FORCE_DIRECT = True
    if _BYPASS_NOTE_SHOWN:
        return
    _BYPASS_NOTE_SHOWN = True
    text = ", ".join(f"{key}={value}" for key, value in sorted(proxies.items()))
    print(
        f"note: proxy connection refused ({text}); retrying without a proxy",
        file=sys.stderr,
        flush=True,
    )


def _content_range_total(headers) -> int | None:
    match = _CONTENT_RANGE.search(headers.get("Content-Range") or "")
    if not match or match.group(3) == "*":
        return None
    return int(match.group(3))


def probe_size(url: str, *, timeout: int = DEFAULT_TIMEOUT, direct: bool = False) -> int | None:
    """Return the total size of *url* if the server honours byte ranges."""
    try:
        with _open(url, timeout=timeout, headers={"Range": "bytes=0-0"}, direct=direct) as response:
            if getattr(response, "status", None) != 206:
                return None
            total = _content_range_total(response.headers)
            if total is None:
                length = response.headers.get("Content-Length")
                total = int(length) if length and length.isdigit() else None
            response.read(1)
            return total
    except Exception:  # noqa: BLE001 - "no range support" is a normal answer
        return None


def plan_segments(total: int, threads: int, *, min_bytes: int = MIN_SEGMENT_BYTES) -> list[tuple[int, int]]:
    """Split ``total`` bytes into at most ``threads`` contiguous ``(start, end)`` ranges."""
    threads = max(1, threads)
    if total <= 0 or threads == 1 or total < min_bytes * 2:
        return [(0, total - 1)] if total > 0 else []
    count = min(threads, max(1, total // min_bytes))
    base = total // count
    segments: list[tuple[int, int]] = []
    start = 0
    for index in range(count):
        end = total - 1 if index == count - 1 else start + base - 1
        segments.append((start, end))
        start = end + 1
    return segments


def _fetch_range(
    url: str,
    path: Path,
    start: int,
    end: int,
    *,
    timeout: int,
    retries: int,
    direct: bool = False,
) -> None:
    """Download ``bytes=start-end`` into *path* (a dedicated per-segment file)."""
    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            with _open(
                url, timeout=timeout, headers={"Range": f"bytes={start}-{end}"}, direct=direct
            ) as response:
                if getattr(response, "status", None) != 206:
                    raise DownloadError(f"server ignored range request for {url}")
                written = 0
                with open(path, "wb") as handle:
                    while True:
                        block = response.read(CHUNK)
                        if not block:
                            break
                        handle.write(block)
                        written += len(block)
                if written != end - start + 1:
                    raise DownloadError(
                        f"short range for {url}: expected {end - start + 1} bytes, got {written}"
                    )
            return
        except Exception as error:  # noqa: BLE001 - retried below
            last_error = error
            path.unlink(missing_ok=True)
            if attempt < retries:
                _backoff(attempt)
    raise DownloadError(f"{url} (bytes {start}-{end}): {last_error}{_network_hint(last_error)}")


def _download_segmented(
    url: str,
    partial: Path,
    total: int,
    *,
    threads: int,
    timeout: int,
    retries: int,
    direct: bool = False,
) -> None:
    """Fetch *url* over ``threads`` connections and concatenate the ranges."""
    segments = plan_segments(total, threads)
    if len(segments) <= 1:
        _download_plain(url, partial, timeout=timeout, retries=retries, direct=direct)
        return

    parts = [partial.with_name(f"{partial.name}.seg{index}") for index in range(len(segments))]
    try:
        with ThreadPoolExecutor(max_workers=len(segments)) as pool:
            futures = [
                pool.submit(
                    _fetch_range,
                    url,
                    part,
                    start,
                    end,
                    timeout=timeout,
                    retries=retries,
                    direct=direct,
                )
                for part, (start, end) in zip(parts, segments)
            ]
            for future in futures:
                future.result()

        with open(partial, "wb") as output:
            for part in parts:
                with open(part, "rb") as handle:
                    while True:
                        block = handle.read(CHUNK)
                        if not block:
                            break
                        output.write(block)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)


def _download_plain(url: str, partial: Path, *, timeout: int, retries: int, direct: bool = False) -> None:
    last_error: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            with _open(url, timeout=timeout, direct=direct) as response, open(partial, "wb") as handle:
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
            return
        except Exception as error:  # noqa: BLE001 - retried below
            last_error = error
            partial.unlink(missing_ok=True)
            if attempt < retries:
                _backoff(attempt)
    raise DownloadError(f"{url}: {last_error}{_network_hint(last_error)}")


def _download_candidate(
    url: str,
    dest: Path,
    partial: Path,
    *,
    sha1: str | None,
    size: int | None,
    retries: int,
    timeout: int,
    threads: int,
) -> None:
    """Download one candidate URL to *partial*; raises DownloadError on failure."""
    last_error: Exception | None = None
    direct = False
    segmented = threads > 1
    known_total = size

    for attempt in range(1, max(1, retries) + 1):
        try:
            if segmented:
                if known_total is None:
                    known_total = probe_size(url, timeout=timeout, direct=direct)
                if known_total is not None and len(plan_segments(known_total, threads)) > 1:
                    _download_segmented(
                        url,
                        partial,
                        known_total,
                        threads=threads,
                        timeout=timeout,
                        retries=2,
                        direct=direct,
                    )
                else:
                    _download_plain(url, partial, timeout=timeout, retries=1, direct=direct)
            else:
                _download_plain(url, partial, timeout=timeout, retries=1, direct=direct)

            if sha1 is not None:
                actual = sha1_file(partial)
                if actual != sha1:
                    raise DownloadError(f"sha1 mismatch for {url}: expected {sha1}, got {actual}")
            if size is not None and partial.stat().st_size != size:
                raise DownloadError(
                    f"size mismatch for {url}: expected {size}, got {partial.stat().st_size}"
                )
            os.replace(partial, dest)
            return
        except Exception as error:  # noqa: BLE001 - retried below
            last_error = error
            partial.unlink(missing_ok=True)
            # A dead proxy (Clash/V2Ray not running, remote tunnel closed...)
            # answers "connection refused" for every request; go direct instead.
            if not direct and not _FORCE_DIRECT:
                proxies = proxy_settings()
                if proxies and _is_connection_refused(error):
                    _force_direct(proxies)
                    direct = True
                    continue
            # Range/connection problems should not cost correctness: retry
            # single-streamed if the parallel attempt failed.
            segmented = False
            if attempt < retries:
                _backoff(attempt)

    if isinstance(last_error, DownloadError):
        raise last_error
    raise DownloadError(f"{url}: {last_error}{_network_hint(last_error, direct=direct)}")


def download(
    url: str,
    dest: str | os.PathLike[str],
    sha1: str | None = None,
    size: int | None = None,
    *,
    retries: int = DEFAULT_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
    threads: int = 1,
    alternates: Sequence[str] = (),
) -> bool:
    """Download *url* to *dest*, skipping files that already match.

    Returns ``True`` when bytes were written, ``False`` when the destination was
    already correct.  The file is written to ``<dest>.part`` and moved into
    place only after verification, so an interrupted download never leaves a
    corrupt file behind.

    ``alternates`` are fallback URLs (e.g. a China mirror) tried in order when
    the primary URL keeps failing.  With ``threads > 1`` each source is split
    into byte ranges fetched over parallel connections (when the server
    supports ``Range`` and the file is large enough); otherwise it falls back
    to a single stream.
    """
    dest = Path(dest)
    if dest.is_file() and file_matches(dest, sha1, size):
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")

    sources = [url, *(candidate for candidate in alternates if candidate and candidate != url)]
    last_error: Exception | None = None
    for source in sources:
        try:
            _download_candidate(
                source,
                dest,
                partial,
                sha1=sha1,
                size=size,
                retries=retries,
                timeout=timeout,
                threads=threads,
            )
            return True
        except DownloadError as error:
            last_error = error
            partial.unlink(missing_ok=True)

    if isinstance(last_error, DownloadError):
        raise last_error
    raise DownloadError(f"{url}: download failed")


class Progress:
    """Thread-safe counter that renders a single-line progress bar."""

    def __init__(self, total: int, label: str, stream=None, width: int = 24) -> None:
        self.total = total
        self.label = label
        self.stream = stream if stream is not None else sys.stderr
        self.width = width
        self.done = 0
        self.failed = 0
        self._lock = threading.Lock()
        self._interactive = bool(getattr(self.stream, "isatty", lambda: False)())

    def start(self) -> None:
        if not self._interactive:
            return
        text = f"  {self.label}: 0/{self.total}"
        print(f"\r{text:<60}", end="", file=self.stream, flush=True)

    def step(self, failed: bool = False) -> None:
        with self._lock:
            self.done += 1
            if failed:
                self.failed += 1
            done, total = self.done, self.total
        if not self._interactive:
            return
        ratio = done / total if total else 1.0
        filled = int(self.width * ratio)
        bar = "#" * filled + "-" * (self.width - filled)
        text = f"  {self.label}: [{bar}] {done}/{total}"
        if self.failed:
            text += f" ({self.failed} failed)"
        print(f"\r{text:<70}", end="", file=self.stream, flush=True)

    def finish(self) -> None:
        if self._interactive:
            print(file=self.stream)


def fetch_many(
    items: Sequence[dict],
    workers: int = DEFAULT_WORKERS,
    label: str = "files",
    *,
    threads: int = 1,
    progress: bool = True,
    stream=None,
) -> tuple[int, list[tuple[str, str]]]:
    """Download many ``{"url", "dest", "sha1", "size"}`` items concurrently.

    ``workers`` is the number of files fetched at the same time; ``threads``
    allows each large file to use several connections as well.

    Returns ``(downloaded_count, [(dest, error_message), ...])``.
    """
    if not items:
        return 0, []

    tracker = Progress(len(items), label, stream=stream)
    tracker.start()
    errors: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                download,
                item["url"],
                item["dest"],
                item.get("sha1"),
                item.get("size"),
                threads=threads,
                alternates=item.get("alternates") or (),
            ): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                future.result()
                tracker.step()
            except Exception as error:  # noqa: BLE001 - collected in the result
                errors.append((str(item.get("dest")), str(error)))
                tracker.step(failed=True)

    tracker.finish()
    return len(items) - len(errors), errors


def fetch_many_quiet(
    items: Iterable[dict], workers: int = DEFAULT_WORKERS, *, threads: int = 1
) -> tuple[int, list[tuple[str, str]]]:
    return fetch_many(list(items), workers=workers, threads=threads, progress=False)
