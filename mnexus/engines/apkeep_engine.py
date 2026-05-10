"""ApkeepEngine — multi-source APK fetcher backed by EFForg/apkeep.

Why a thin wrapper over the Rust CLI instead of a Python port:

* apkeep tracks Google Play protocol drift upstream — we don't have to.
* Aurora, F-Droid, APKPure and Huawei AppGallery come along for free,
  and they each need different auth flows we'd otherwise reimplement.
* `apkeep --print-url --download-source google-play` returns a signed
  CDN URL that our streaming `remote_zip` reader consumes without
  writing the APK to disk. Best of both worlds.

This engine is intentionally *not* part of the static-fanout pipeline.
It exposes ``fetch()`` for callers (the upload endpoint, the CLI, the
playintel streaming source) — it doesn't produce findings.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


SUPPORTED_SOURCES = {
    "google-play",
    "aurora",
    "f-droid",
    "apkpure",
    "huawei-appgallery",
}


@dataclass(slots=True)
class ApkeepResult:
    """One run of `apkeep` returns one or more files (split APKs etc)."""

    package: str
    source: str
    files: list[Path]
    primary_apk: Path | None  # base.apk when split, the only file otherwise


class ApkeepError(RuntimeError):
    """apkeep returned non-zero or didn't produce an APK we can load."""


class ApkeepEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "apkeep"

    @property
    def capabilities(self) -> list[str]:
        return ["fetch_apk", "print_url", "multi_source"]

    async def health_check(self) -> EngineStatus:
        path = shutil.which("apkeep")
        if not path:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="apkeep missing — `brew install apkeep` or `cargo install apkeep`",
            )
        out = await self._run([path, "--version"])
        version = out.strip().split()[-1] if out.strip() else "?"
        return EngineStatus(
            name=self.name,
            installed=True,
            version=version,
            path=path,
            message="ready · supports google-play / aurora / f-droid / apkpure / huawei-appgallery",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """ApkeepEngine never participates in the static fan-out — fetch only."""
        _ = context
        return []

    # ─── public helpers ─────────────────────────────────────────────────

    async def fetch(
        self,
        package: str,
        *,
        source: str = "google-play",
        out_dir: Path | None = None,
        timeout_s: int = 180,
    ) -> ApkeepResult:
        """Download `package` from `source` into `out_dir`.

        Returns the list of downloaded files. On Google Play this often
        includes a base APK plus split APKs and OBB additional files;
        the primary APK is the one with `base` in the name (or the only
        `.apk` if the source ships a single file).
        """
        if source not in SUPPORTED_SOURCES:
            raise ApkeepError(
                f"unsupported source '{source}' — pick one of: {sorted(SUPPORTED_SOURCES)}"
            )
        path = shutil.which("apkeep")
        if not path:
            raise ApkeepError("apkeep not installed; see scripts/setup-apkeep.sh")

        target = out_dir or (self.config.workspace / "apkeep" / package)
        target.mkdir(parents=True, exist_ok=True)

        # Snapshot dir contents before so we can pick out the new files.
        before = {p.name for p in target.iterdir()} if target.exists() else set()

        cmd = [path, "--app", package, "--download-source", source, "--output-dir", str(target)]
        # Google Play needs credentials. apkeep finds them automatically in
        # ~/.config/apkeep/apkeep.ini — same file the playintel client uses.
        try:
            await self._run(cmd, timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise ApkeepError(f"apkeep timed out after {timeout_s}s") from exc

        new_files = sorted(p for p in target.iterdir() if p.name not in before and p.is_file())
        if not new_files:
            raise ApkeepError(
                f"apkeep finished but produced no new files in {target} — check credentials / availability"
            )

        # Pick the base APK if there are splits.
        apks = [p for p in new_files if p.suffix.lower() in {".apk", ".xapk"}]
        primary: Path | None = None
        if apks:
            primary = next((p for p in apks if "base" in p.name.lower()), apks[0])

        return ApkeepResult(package=package, source=source, files=new_files, primary_apk=primary)

    async def print_url(self, package: str) -> str | None:
        """Return the signed CDN URL for the latest version on Google Play.

        Used by playintel's streaming reader to read partial bytes via
        HTTP Range without ever writing the APK to disk. Returns None
        when apkeep doesn't expose this flag (older builds) or when
        Google rejects the request.
        """
        path = shutil.which("apkeep")
        if not path:
            return None
        # apkeep ≥ 0.16 supports `--print-url`. On older builds the flag is
        # rejected and we fall back to nothing.
        cmd = [path, "--app", package, "--download-source", "google-play", "--print-url"]
        try:
            out = await self._run(cmd, timeout=30)
        except (ApkeepError, asyncio.TimeoutError):
            return None
        out = out.strip()
        if out.startswith("http"):
            return out.splitlines()[0].strip()
        return None

    # ─── plumbing ──────────────────────────────────────────────────────

    async def _run(self, cmd: list[str], timeout: float | None = None) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise
        if proc.returncode != 0:
            raise ApkeepError(
                f"apkeep exit={proc.returncode}: {stderr.decode('utf-8', errors='replace').strip()[:300]}"
            )
        return stdout.decode("utf-8", errors="replace")
