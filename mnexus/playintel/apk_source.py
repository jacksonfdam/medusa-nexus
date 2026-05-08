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

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

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


# ─── Google Play (via Go reference binary) ────────────────────────────────


class PlayBinarySource:
    """Bridge to the existing Go reference scanner ``poc-firebase-google``.

    The Go binary already implements the full Play protocol — auth,
    device check-in, GetDownloadInfo, signed URLs. Re-implementing
    that in Python is a big-enough piece of work that a separate
    follow-up makes more sense than trying to fit it into this engine.
    Until then, when the Go binary is on the system this source acts
    as the production data path.

    Modes:

    * ``--resolve <package>`` (preferred when supported): the binary
      prints a JSON ``DownloadInfo`` we can parse and feed to a
      :class:`DirectURLSource` for streaming.
    * Fallback: the binary is invoked with ``-pk <package>`` to do its
      own scan + write the persisted ``secrets/<pkg>/`` directory; we
      then read those files as a :class:`LocalAPKSource`-style local
      source.

    The fallback mode produces no streaming benefit — the Go binary
    already streamed and saved the high-value entries. We just lift
    the saved files into the analyzer's pipeline so findings get into
    MedusaNexus's database alongside everything else.

    Set ``MNEXUS_PLAYBIN_PATH`` or pass ``binary_path`` to point at a
    specific build.
    """

    DEFAULT_BINARY_NAMES = ("poc-firebase-google", "go-google-login")

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
        config_path: Path | None = None,
        proxy: str | None = None,
        secrets_root: Path | None = None,
    ) -> None:
        self.binary_path = self._resolve_binary(binary_path)
        self.config_path = config_path
        self.proxy = proxy
        self.secrets_root = secrets_root or Path.cwd() / "secrets"

    @staticmethod
    def _resolve_binary(explicit: Path | None) -> Path:
        """Resolve the bridge binary in this order:

        1. ``explicit`` argument from the caller.
        2. ``MNEXUS_PLAYBIN_PATH`` env var.
        3. ``shutil.which()`` against the documented binary names.
        """
        if explicit:
            p = Path(explicit).expanduser()
            if not p.exists():
                raise FileNotFoundError(f"Play binary not found: {p}")
            return p
        env_path = os.environ.get("MNEXUS_PLAYBIN_PATH")
        if env_path:
            p = Path(env_path).expanduser()
            if not p.exists():
                raise FileNotFoundError(
                    f"MNEXUS_PLAYBIN_PATH points at missing file: {p}"
                )
            return p
        for name in PlayBinarySource.DEFAULT_BINARY_NAMES:
            found = shutil.which(name)
            if found:
                return Path(found)
        raise FileNotFoundError(
            "Play binary not found. Set MNEXUS_PLAYBIN_PATH=/path/to/poc-firebase-google, "
            "or symlink the binary into a directory on PATH "
            "(e.g. `ln -s ~/Downloads/Projects/go-google-login-master/poc-firebase-google /usr/local/bin/`)."
        )

    def get_download_info(self, package_name: str) -> DownloadInfo:
        """Try ``--resolve``; fall back to legacy ``-pk`` scan-and-import."""
        # Optimistic call — the Go binary may not implement --resolve yet,
        # in which case the fallback path takes over.
        try:
            return self._resolve_via_binary(package_name)
        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
            return self._scan_and_import(package_name)

    def _resolve_via_binary(self, package_name: str) -> DownloadInfo:
        argv = [str(self.binary_path), "-pk", package_name, "-resolve-only"]
        if self.config_path:
            argv += ["-config", str(self.config_path)]
        if self.proxy:
            argv += ["-proxy", self.proxy]
        proc = subprocess.run(  # noqa: S603 — argv assembled from typed inputs
            argv,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        payload = json.loads(proc.stdout)
        return DownloadInfo(
            package_name=package_name,
            base_url=payload["url"],
            base_size=int(payload["size"]),
            splits=[SplitInfo(**s) for s in payload.get("splits", [])],
            additional_files=[FileInfo(**f) for f in payload.get("additional_files", [])],
            headers=payload.get("headers"),
        )

    def _scan_and_import(self, package_name: str) -> DownloadInfo:
        """Run the Go scanner end-to-end and import its output dir.

        The Go binary writes ``secrets/<package>/`` containing the
        bearing files (resources.arsc, google-services.json, …).
        We treat that directory as the input to a synthetic
        :class:`LocalAPKSource`-shaped session.
        """
        argv = [str(self.binary_path), "-pk", package_name]
        if self.config_path:
            argv += ["-config", str(self.config_path)]
        if self.proxy:
            argv += ["-proxy", self.proxy]
        # Fire it; ignore non-zero exit (Go binary may exit non-zero on
        # auth issues but still produce useful output).
        try:
            subprocess.run(  # noqa: S603
                argv,
                cwd=str(self.secrets_root.parent if self.secrets_root.parent.exists() else "."),
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pass
        # The expected output dir is `<cwd>/secrets/<package>/`.
        out_dir = self.secrets_root / package_name
        if not out_dir.exists():
            raise FileNotFoundError(
                f"Go scanner produced no output at {out_dir}. "
                "Verify auth in ~/.config/apkeep/apkeep.ini and try again."
            )
        # Synthesize a "DownloadInfo" pointing at the saved
        # resources.arsc — the analyzer code path detects this and
        # uses a per-file scan instead of a zip scan.
        arsc = out_dir / "ROOT_resources.arsc"
        if not arsc.exists():
            raise FileNotFoundError(f"resources.arsc missing under {out_dir}")
        return DownloadInfo(
            package_name=package_name,
            base_url=str(arsc),
            base_size=arsc.stat().st_size,
            splits=[],
            additional_files=[],
            headers={"x-mnexus-source": "play-binary-import"},
        )

    @contextmanager
    def open_base(self, info: DownloadInfo) -> Iterator[LocalZip | RemoteZip]:
        # If the bridge produced a real CDN URL, stream it. Otherwise
        # the base_url points at a local file (the import path).
        path = Path(info.base_url)
        if path.exists():
            with LocalZip(path) as z:
                yield z
        else:
            with RemoteZip(info.base_url, info.base_size, headers=info.headers) as z:
                yield z

    @contextmanager
    def open_split(self, info: DownloadInfo, split: SplitInfo) -> Iterator[RemoteZip]:
        with RemoteZip(split.url, split.size, headers=info.headers) as z:
            yield z
