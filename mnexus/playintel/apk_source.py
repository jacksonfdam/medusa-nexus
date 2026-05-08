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

import shutil
import tempfile
import zipfile
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


# ─── Bundled formats: .apkm / .apks / .xapk ───────────────────────────────


_BASE_APK_CANDIDATES = ("base.apk", "base/base.apk")


def _pick_base_entry(zf: zipfile.ZipFile, apk_entries: list[str]) -> str:
    """Decide which entry in a bundle is the "base" APK.

    Tries the documented filenames first (top-level ``base.apk``,
    Bundletool-style ``base/base.apk``, then any ``*/base.apk``
    nested under any prefix). Falls back to the largest ``.apk``
    inside, which Bundletool guarantees is the base.

    Shared by :class:`BundledAPKSource` (which extracts every entry)
    and :func:`extract_base_from_bundle` (which only pulls the base
    out — used by the orchestrator path).
    """
    lower_to_orig = {n.lower(): n for n in apk_entries}
    for candidate in _BASE_APK_CANDIDATES:
        if candidate in lower_to_orig:
            return lower_to_orig[candidate]
        leaf = candidate.split("/")[-1]
        for lower_n, orig in lower_to_orig.items():
            if lower_n.endswith("/" + leaf):
                return orig
    # No documented filename matched — pick the largest .apk.
    return max(apk_entries, key=lambda n: zf.getinfo(n).file_size)


def extract_base_from_bundle(
    bundle_path: Path, workspace: Path | None = None
) -> tuple[Path, Path]:
    """Pull just the base APK out of a bundle to a fresh temp dir.

    Returns ``(base_path, temp_dir)``. The caller owns ``temp_dir`` and
    must ``shutil.rmtree`` it when done — there's no context-manager
    convenience here because the orchestrator already owns lifecycle.

    Splits inside the bundle are deliberately ignored. Use
    :class:`BundledAPKSource` instead when you also want them
    (playintel does; the orchestrator's project-ingest pipeline
    runs only against the base).
    """
    bundle_path = Path(bundle_path).expanduser().resolve()
    if not zipfile.is_zipfile(bundle_path):
        raise ValueError(f"not a zip: {bundle_path}")
    parent = (workspace / "playintel-uploads") if workspace is not None else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(
        tempfile.mkdtemp(
            prefix=f"bundle-base-{bundle_path.stem}-",
            dir=str(parent) if parent else None,
        )
    )
    try:
        with zipfile.ZipFile(bundle_path) as zf:
            apk_entries = [n for n in zf.namelist() if n.lower().endswith(".apk")]
            if not apk_entries:
                raise RuntimeError(
                    f"{bundle_path.name}: no .apk entries inside — not a recognised bundle"
                )
            base_entry = _pick_base_entry(zf, apk_entries)
            base_out = tmp_dir / "base.apk"
            with zf.open(base_entry) as src, base_out.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
        return base_out, tmp_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _looks_like_bundle(path: Path) -> bool:
    """Return True if ``path`` is a zip whose contents are nested APKs.

    APKM (APKMirror), APKS (Bundletool ``build-apks`` output), and XAPK
    (universal cross-store format) are all zips that ship a base APK
    plus per-config splits as inner ``*.apk`` entries. We don't trust
    the file extension alone because users rename these all the time;
    we sniff the central directory.
    """
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            for entry in zf.namelist():
                if entry.lower().endswith(".apk"):
                    return True
    except zipfile.BadZipFile:
        return False
    return False


class BundledAPKSource:
    """Source backed by a bundle (.apkm / .apks / .xapk) of nested APKs.

    On open, walks the outer zip and pulls each inner ``*.apk`` entry
    out to a temp directory under the workspace. The base APK is
    whichever entry matches :data:`_BASE_APK_CANDIDATES` (or, failing
    that, the largest ``.apk`` — Bundletool builds the base as the
    biggest split). Everything else becomes a :class:`SplitInfo` and
    flows through the analyzer's existing splits loop, so credential
    / Firebase recovery covers per-locale, per-ABI, and per-density
    splits without any pipeline changes.

    Temps live under ``<workspace>/playintel-uploads/bundled-<stem>/``
    and are removed on :meth:`close` (or on context-manager exit).
    """

    def __init__(self, bundle_path: Path, *, workspace: Path | None = None) -> None:
        self.bundle_path = Path(bundle_path).expanduser().resolve()
        if not self.bundle_path.exists():
            raise FileNotFoundError(f"bundle not found: {self.bundle_path}")
        self._workspace = workspace
        self._tmp_dir: Path | None = None
        self._base_path: Path | None = None
        self._splits: list[tuple[Path, int, str]] = []  # (path, size, name)
        self._extract()

    # ─── extraction ──────────────────────────────────────────────────

    def _extract(self) -> None:
        # Prefer a workspace-scoped temp so the analyst's saved-files
        # directory and the bundle scratch live next to each other;
        # fall back to a system temp dir for tests / standalone use.
        parent = (
            self._workspace / "playintel-uploads" if self._workspace is not None else None
        )
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        self._tmp_dir = Path(
            tempfile.mkdtemp(
                prefix=f"bundled-{self.bundle_path.stem}-",
                dir=str(parent) if parent else None,
            )
        )

        with zipfile.ZipFile(self.bundle_path) as zf:
            apk_entries = [n for n in zf.namelist() if n.lower().endswith(".apk")]
            if not apk_entries:
                raise RuntimeError(
                    f"{self.bundle_path.name} contained no .apk entries — "
                    "not a recognised .apkm / .apks / .xapk bundle"
                )
            base_entry = _pick_base_entry(zf, apk_entries)

            # Extract every inner .apk to disk; tag base + splits.
            for entry in apk_entries:
                # Flatten nested paths into a single filename so the
                # extracted layout is `<tmp>/base.apk`, `<tmp>/split_armv7a.apk`.
                flat_name = entry.replace("/", "_").replace("\\", "_")
                out = self._tmp_dir / flat_name
                with zf.open(entry) as src, out.open("wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                size = out.stat().st_size
                if entry == base_entry:
                    self._base_path = out
                else:
                    self._splits.append((out, size, _split_label(entry)))

        if self._base_path is None:
            raise RuntimeError("base APK could not be identified in bundle")

    # ─── APKSource protocol ──────────────────────────────────────────

    def get_download_info(self, package_name: str) -> DownloadInfo:
        assert self._base_path is not None
        splits = [
            SplitInfo(name=name, url=str(p), size=size)
            for p, size, name in self._splits
        ]
        return DownloadInfo(
            package_name=package_name or self.bundle_path.stem,
            base_url=str(self._base_path),
            base_size=self._base_path.stat().st_size,
            splits=splits,
            additional_files=[],
        )

    @contextmanager
    def open_base(self, info: DownloadInfo) -> Iterator[LocalZip]:
        with LocalZip(Path(info.base_url)) as z:
            yield z

    @contextmanager
    def open_split(self, info: DownloadInfo, split: SplitInfo) -> Iterator[LocalZip]:  # noqa: ARG002
        # Splits in a bundle are always real files on disk now.
        with LocalZip(Path(split.url)) as z:
            yield z

    # ─── lifecycle ───────────────────────────────────────────────────

    def close(self) -> None:
        if self._tmp_dir is not None and self._tmp_dir.exists():
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    def __enter__(self) -> BundledAPKSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _split_label(entry: str) -> str:
    """Strip path components and the .apk suffix so split names look clean
    in the UI / report ("config.arm64_v8a" not "splits/config.arm64_v8a.apk").
    """
    name = entry.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if name.lower().endswith(".apk"):
        name = name[:-4]
    return name


# ─── Factory: pick the right local source ────────────────────────────────


def local_source_for(
    path: Path,
    *,
    workspace: Path | None = None,
) -> LocalAPKSource | BundledAPKSource:
    """Return :class:`BundledAPKSource` for .apkm/.apks/.xapk-shaped
    bundles, :class:`LocalAPKSource` for a single APK.

    Detection runs against the file contents (a zip with nested .apk
    entries → bundle), not against the extension — users rename these
    all the time and a misnamed file shouldn't change the analysis.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    if _looks_like_bundle(p):
        return BundledAPKSource(p, workspace=workspace)
    return LocalAPKSource(p)


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
