"""APK source — pluggable strategies for getting at an APK's bytes.

The analyzer needs the same downstream behavior whether the APK comes
from Google Play, a local file, or a pre-resolved CDN URL. The three
sources here implement the same protocol; the analyzer never branches
on which one produced the data.

Sources:

* :class:`LocalAPKSource` — wraps a path on disk. Always available;
  ideal for offline analysis or when the user already has the APK.
* :class:`DirectURLSource` — wraps a (URL, size, headers) tuple.
  Useful when another tool has already resolved the Play CDN URL
  (``apkeep --print-url``, ``gpapi-python``, the Go reference binary)
  and you want to feed it straight to the analyzer.
* :class:`PlayBinarySource` — subprocess wrapper around the existing
  Go reference binary (``poc-firebase-google``). When that binary is
  on ``$PATH`` (or its location is provided), this source bridges the
  full Google Play protocol — auth, GetDownloadInfo, signed CDN URLs —
  without re-implementing it in Python.

A future :class:`PlayProtocolSource` could implement the full protocol
in Python directly (anchor: ``apkeep`` Rust source +
``gpapi-python``); the abstraction is set up so adding it is purely
additive.

All sources expose :meth:`open` which returns a context-managed
:class:`mnexus.playintel.remote_zip.LocalZip` or
:class:`~mnexus.playintel.remote_zip.RemoteZip`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from typing import TYPE_CHECKING

from mnexus.playintel.play_client import (
    PlayClient,
    PlayCredentials,
)

if TYPE_CHECKING:
    from mnexus.core.artifact_store import ArtifactStore

from mnexus.playintel.remote_zip import LocalZip, RemoteZip


@dataclass(slots=True)
class DownloadInfo:
    """Bundle of attributes the Play CDN exposes for one APK + its splits."""

    package_name: str
    base_url: str
    base_size: int
    splits: list["SplitInfo"]
    additional_files: list["FileInfo"]
    headers: dict[str, str] | None = None


@dataclass(slots=True)
class SplitInfo:
    name: str
    url: str
    size: int


@dataclass(slots=True)
class FileInfo:
    name: str
    url: str
    size: int


class APKSource(Protocol):
    """Common protocol for the three source kinds.

    Every source can resolve a package name to a :class:`DownloadInfo`
    and stream zip readers for the base APK + each split.
    """

    def get_download_info(self, package_name: str) -> DownloadInfo: ...

    @contextmanager
    def open_base(self, info: DownloadInfo) -> Iterator[LocalZip | RemoteZip]: ...

    @contextmanager
    def open_split(self, info: DownloadInfo, split: SplitInfo) -> Iterator[LocalZip | RemoteZip]: ...


# ─── Local file ───────────────────────────────────────────────────────────


class LocalAPKSource:
    """Source backed by a local APK file.

    ``get_download_info`` ignores the package_name argument — there's
    nothing to resolve — and returns a single-target :class:`DownloadInfo`.
    """

    def __init__(self, apk_path: Path) -> None:
        self.apk_path = Path(apk_path).expanduser().resolve()
        if not self.apk_path.exists():
            raise FileNotFoundError(f"APK not found: {self.apk_path}")

    def get_download_info(self, package_name: str) -> DownloadInfo:
        return DownloadInfo(
            package_name=package_name or self.apk_path.stem,
            base_url=str(self.apk_path),
            base_size=self.apk_path.stat().st_size,
            splits=[],
            additional_files=[],
        )

    @contextmanager
    def open_base(self, info: DownloadInfo) -> Iterator[LocalZip]:
        with LocalZip(Path(info.base_url)) as z:
            yield z

    @contextmanager
    def open_split(self, info: DownloadInfo, split: SplitInfo) -> Iterator[LocalZip]:  # noqa: ARG002
        # LocalAPKSource never produces splits.
        raise RuntimeError("LocalAPKSource has no splits")


# ─── Direct URL ───────────────────────────────────────────────────────────


class DirectURLSource:
    """Source backed by pre-resolved CDN URLs.

    Useful when another tool has done the Play protocol dance and
    handed you the signed download URL, the byte size, and (optionally)
    the headers required to fetch it.
    """

    def __init__(
        self,
        package_name: str,
        base_url: str,
        base_size: int,
        *,
        headers: dict[str, str] | None = None,
        splits: list[SplitInfo] | None = None,
        additional_files: list[FileInfo] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.package_name = package_name
        self.base_url = base_url
        self.base_size = base_size
        self.headers = headers
        self.splits = splits or []
        self.additional_files = additional_files or []
        self._client = client

    def get_download_info(self, package_name: str) -> DownloadInfo:  # noqa: ARG002
        return DownloadInfo(
            package_name=self.package_name,
            base_url=self.base_url,
            base_size=self.base_size,
            splits=self.splits,
            additional_files=self.additional_files,
            headers=self.headers,
        )

    @contextmanager
    def open_base(self, info: DownloadInfo) -> Iterator[RemoteZip]:
        with RemoteZip(
            info.base_url, info.base_size, headers=info.headers, client=self._client
        ) as z:
            yield z

    @contextmanager
    def open_split(self, info: DownloadInfo, split: SplitInfo) -> Iterator[RemoteZip]:
        with RemoteZip(split.url, split.size, headers=info.headers, client=self._client) as z:
            yield z


# ─── Google Play (native pure-Python protocol) ────────────────────────────


class PlayProtocolSource:
    """Source backed by the native :class:`PlayClient`.

    Talks the Google Play protocol directly in Python — no Go binary,
    no `apkeep` subprocess. Authentication uses the same
    ``~/.config/apkeep/apkeep.ini`` schema apkeep itself uses, so
    existing setups roll forward without re-pairing.

    One-line usage::

        source = PlayProtocolSource()  # loads creds from apkeep.ini
        outcome = analyze_package(source, "com.example.app", workspace=ws)

    The source owns the underlying ``PlayClient`` lifetime via a
    context manager. Splits and OBB additional files come back from
    Play in the same DownloadInfo so the analyzer pipeline scans
    every part of the app (base + per-ABI splits + per-locale splits).
    """

    def __init__(
        self,
        *,
        credentials: PlayCredentials | None = None,
        account_name: str | None = None,
        store: "ArtifactStore | None" = None,
        device_props: dict[str, str] | None = None,
        client: PlayClient | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            creds = credentials or PlayCredentials.load(
                store=store, account_name=account_name
            )
            self._client = PlayClient(creds, device_props=device_props, store=store)
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> PlayProtocolSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_download_info(self, package_name: str) -> DownloadInfo:
        """Resolve a package name → signed CDN URL via the Play protocol."""
        play_info = self._client.get_download_info(package_name)
        return DownloadInfo(
            package_name=play_info.package_name,
            base_url=play_info.base_url,
            base_size=play_info.base_size,
            splits=[SplitInfo(name=s.name, url=s.url, size=s.size) for s in play_info.splits],
            additional_files=[
                FileInfo(name=f.name, url=f.url, size=f.size)
                for f in play_info.additional_files
            ],
            headers=None,
        )

    @contextmanager
    def open_base(self, info: DownloadInfo) -> Iterator[RemoteZip]:
        with RemoteZip(info.base_url, info.base_size, headers=info.headers) as z:
            yield z

    @contextmanager
    def open_split(self, info: DownloadInfo, split: SplitInfo) -> Iterator[RemoteZip]:
        with RemoteZip(split.url, split.size, headers=info.headers) as z:
            yield z
