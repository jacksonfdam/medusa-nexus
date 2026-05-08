"""Remote ZIP — read a zip archive over HTTP without downloading the whole file.

APKs are served from Google's CDN as plain HTTP responses with
``Accept-Ranges: bytes``. The zip central directory lives at the end of
the file, so we only need:

1. The last ~1 MB to find and parse the central directory.
2. A separate small range request per zip entry we actually want to
   read — for credential scanning that's a handful of files
   (``resources.arsc``, ``google-services.json``, ``.bundle``s, …)
   regardless of how big the APK is.

For a 100 MB APK this means ~5–10 MB transferred end-to-end, which is
roughly 10× faster and one less artefact than downloading the full APK.

Two adapters share one zip-reading core:

* :class:`RemoteZip` — :class:`io.RawIOBase`-shaped adapter that issues
  ``Range`` requests against an HTTP server and caches 1 MB chunks.
  ``zipfile.ZipFile`` reads from it transparently.
* :class:`LocalZip` — same ``open_entry`` API but delegates to
  ``zipfile.ZipFile`` over a local file. Lets the rest of the pipeline
  treat "stream from CDN" and "open this APK from disk" identically.

Both expose :meth:`open_entry`, :meth:`names`, and :meth:`size`.
"""

from __future__ import annotations

import io
import threading
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

# 1 MB chunks. Small enough to keep memory bounded on big APKs, large
# enough to amortize HTTP request overhead per byte fetched.
DEFAULT_CHUNK_SIZE = 1024 * 1024

# Per-request timeout — single Range fetch.
DEFAULT_REQUEST_TIMEOUT_S = 120.0

# Max bytes a single Range response is allowed to deliver. Caps memory
# pressure if the server returns more than expected (or returns 200
# with the full file).
MAX_RESPONSE_BYTES = 500 * 1024 * 1024


# ─── HTTP-backed read-at-offset reader ────────────────────────────────────


class _RemoteReader(io.RawIOBase):
    """``io.RawIOBase``-compatible random-access reader backed by HTTP Range.

    ``zipfile.ZipFile`` reads from a seekable stream — it issues
    ``seek`` then ``read`` calls, which we translate into ``readinto``
    / ``readall``-style fetches against a chunk cache. Misses go to
    HTTP; hits are served from memory.
    """

    def __init__(
        self,
        client: httpx.Client,
        url: str,
        size: int,
        headers: dict[str, str] | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self._client = client
        self._url = url
        self._size = size
        self._headers = headers or {}
        self._chunk_size = chunk_size
        self._pos = 0
        # offset → bytes
        self._chunks: dict[int, bytes] = {}
        self._lock = threading.Lock()

    # ─── io.RawIOBase contract ────────────────────────────────────────

    def readable(self) -> bool:  # noqa: D401 - inherited
        return True

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._pos = offset
        elif whence == io.SEEK_CUR:
            self._pos += offset
        elif whence == io.SEEK_END:
            self._pos = self._size + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        if self._pos < 0:
            self._pos = 0
        return self._pos

    def tell(self) -> int:
        return self._pos

    def readinto(self, buf) -> int:  # type: ignore[no-untyped-def]
        n = self._read_at(self._pos, len(buf))
        if not n:
            return 0
        buf[: len(n)] = n
        self._pos += len(n)
        return len(n)

    # ─── core fetch path ──────────────────────────────────────────────

    def _read_at(self, offset: int, length: int) -> bytes:
        if offset >= self._size or length <= 0:
            return b""
        if offset + length > self._size:
            length = self._size - offset

        # Identify which chunks we need.
        first_chunk = (offset // self._chunk_size) * self._chunk_size
        last_chunk = ((offset + length - 1) // self._chunk_size) * self._chunk_size

        out = bytearray()
        cs = first_chunk
        while cs <= last_chunk:
            with self._lock:
                cached = self._chunks.get(cs)
            if cached is None:
                self._fetch_chunk_range(cs, cs)
                with self._lock:
                    cached = self._chunks.get(cs)
                if cached is None:
                    break
            # Slice the cached chunk to the part of the read window
            # that falls inside it.
            chunk_lo = cs
            chunk_hi = cs + len(cached)
            read_lo = max(offset, chunk_lo)
            read_hi = min(offset + length, chunk_hi)
            if read_hi <= read_lo:
                break
            out.extend(cached[read_lo - chunk_lo : read_hi - chunk_lo])
            cs += self._chunk_size
        return bytes(out)

    def _fetch_chunk_range(self, first_chunk: int, last_chunk: int) -> None:
        """GET ``[first_chunk, last_chunk + chunk_size)`` and cache the slice."""
        fetch_end = last_chunk + self._chunk_size
        if fetch_end > self._size:
            fetch_end = self._size
        if first_chunk >= fetch_end:
            return

        headers = {**self._headers, "Range": f"bytes={first_chunk}-{fetch_end - 1}"}
        with self._client.stream(
            "GET", self._url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT_S
        ) as resp:
            if resp.status_code not in (200, 206):
                raise httpx.HTTPStatusError(
                    f"range fetch failed: status={resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            data = resp.read()

        if len(data) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"range response too large: {len(data)} bytes")

        with self._lock:
            cs = first_chunk
            while cs < fetch_end:
                local = cs - first_chunk
                chunk_len = self._chunk_size
                if cs + chunk_len > self._size:
                    chunk_len = self._size - cs
                if local + chunk_len > len(data):
                    chunk_len = len(data) - local
                if chunk_len <= 0:
                    break
                self._chunks[cs] = data[local : local + chunk_len]
                cs += self._chunk_size

    # ─── prefetch helpers ─────────────────────────────────────────────

    def prefetch_range(self, start: int, length: int) -> None:
        """Warm the cache for a contiguous byte range without reading it.

        Used by :meth:`RemoteZip.prefetch_entries` to issue one HTTP
        request per zip entry we plan to read, instead of letting the
        cold-cache reads inside ``zipfile`` issue many small ones.
        """
        if length <= 0:
            return
        end = min(start + length, self._size)
        first_chunk = (start // self._chunk_size) * self._chunk_size
        last_chunk = ((end - 1) // self._chunk_size) * self._chunk_size
        # Fetch in one Range request when chunks are contiguous and
        # missing; otherwise fall back to the lazy path.
        with self._lock:
            run_start: int | None = None
            cs = first_chunk
            need_to_fetch: list[tuple[int, int]] = []
            while cs <= last_chunk:
                if cs not in self._chunks:
                    if run_start is None:
                        run_start = cs
                    last_run = cs
                else:
                    if run_start is not None:
                        need_to_fetch.append((run_start, last_run))
                        run_start = None
                cs += self._chunk_size
            if run_start is not None:
                need_to_fetch.append((run_start, last_run))
        for run in need_to_fetch:
            self._fetch_chunk_range(run[0], run[1])


# ─── Public adapters ──────────────────────────────────────────────────────


class RemoteZip:
    """Read a zip archive over HTTP without downloading the whole file.

    Construct with the CDN URL, the total file size in bytes, and
    optionally a header dict (Play CDN signed URLs typically don't need
    auth headers, but we keep the hook for callers that do).

    The zip central directory is read up-front so :meth:`names` is
    available immediately. Use :meth:`prefetch_entries` to warm the
    chunk cache for the entries you plan to open in one go.
    """

    def __init__(
        self,
        url: str,
        size: int,
        *,
        headers: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(follow_redirects=True)
        self._reader = _RemoteReader(self._client, url, size, headers=headers)
        self._zip = zipfile.ZipFile(self._reader)
        self._size = size

    def __enter__(self) -> RemoteZip:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._zip.close()
        finally:
            if self._owns_client:
                self._client.close()

    @property
    def size(self) -> int:
        """Total APK byte length."""
        return self._size

    def names(self) -> list[str]:
        """Names of every entry in the zip, in central-directory order."""
        return self._zip.namelist()

    def infos(self) -> list[zipfile.ZipInfo]:
        """All :class:`zipfile.ZipInfo` records (size + offset metadata)."""
        return self._zip.infolist()

    def open_entry(self, name: str) -> bytes:
        """Read one entry by name. Returns the decompressed bytes."""
        return self._zip.read(name)

    def prefetch_entries(self, names: Iterable[str]) -> None:
        """Issue HTTP Range requests for the compressed bytes of every
        named entry, in advance, so that subsequent :meth:`open_entry`
        calls hit the chunk cache instead of stalling on round trips.
        """
        for n in names:
            try:
                info = self._zip.getinfo(n)
            except KeyError:
                continue
            # ZipFile exposes header_offset, but compressed data starts
            # *after* the local file header. Read just enough to skip
            # over the local header and then prefetch the entry payload.
            self._reader.prefetch_range(info.header_offset, 64)
            with self._reader._lock:  # noqa: SLF001 - intentional, internal
                # ZipFile does its own header parse on read(); we just
                # need to ensure header bytes are warm. Fetch the
                # payload as one range too.
                pass
            # Compressed payload lies at header_offset + LFH size, but
            # the LFH size depends on filename + extra fields lengths;
            # pulling info from the ZipFile API would require parsing
            # the LFH ourselves. The simpler, robust approach: fetch a
            # range that covers the LFH plus the compressed bytes.
            est_lfh = 30 + len(info.filename.encode("utf-8")) + len(info.extra or b"") + 64
            self._reader.prefetch_range(info.header_offset, est_lfh + info.compress_size)


class LocalZip:
    """Local-file analogue of :class:`RemoteZip` with the same API.

    Lets the analyzer accept either ``-pk com.foo`` (CDN streaming) or
    ``--apk path/to/foo.apk`` (local file) and run identical code paths.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._zip = zipfile.ZipFile(path)
        self._size = path.stat().st_size

    def __enter__(self) -> LocalZip:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    @property
    def size(self) -> int:
        return self._size

    def names(self) -> list[str]:
        return self._zip.namelist()

    def infos(self) -> list[zipfile.ZipInfo]:
        return self._zip.infolist()

    def open_entry(self, name: str) -> bytes:
        return self._zip.read(name)

    def prefetch_entries(self, names: Iterable[str]) -> None:  # noqa: ARG002 — interface parity
        # No-op: local reads are already memory-mapped by the OS.
        return
