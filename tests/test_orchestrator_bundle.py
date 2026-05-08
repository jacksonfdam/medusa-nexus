"""End-to-end test for the orchestrator's bundle-unpack path.

Pre-Phase-A, uploading an .apkm to ``/v1/apks/upload`` produced a
project whose ``apk_meta`` was empty (apktool engine parsed the OUTER
zip, found no ``AndroidManifest.xml`` at the top level, gave up). The
attack surface ended up with 0 components, 0 deeplinks, 0 native libs
even when the inner base APK was rich.

This test asserts that:

1. The orchestrator detects bundles and extracts the inner base APK.
2. Engines (here apktool) see the inner manifest and recover the real
   package id, exported components, deeplinks.
3. The Project's ``apk_path`` + ``apk_sha256`` stay pinned to the
   ORIGINAL bundle file — analyst expectation is "the file I uploaded
   is the artefact-of-record".
4. The temp dir created for the unpack gets cleaned up on success.
"""

from __future__ import annotations

import asyncio
import hashlib
import zipfile
from pathlib import Path

import pytest

from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus, _prepare_scan_path


# ─── helpers ─────────────────────────────────────────────────────────────


_INNER_APK_MANIFEST = (
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
    'package="com.example.bundle">'
    '<application android:label="x">'
    '<activity android:name=".Main" android:exported="true">'
    '<intent-filter>'
    '<data android:scheme="bundleapp" android:host="open" />'
    '</intent-filter>'
    '</activity>'
    '</application>'
    '</manifest>'
)


def _build_inner_apk(path: Path) -> Path:
    """Minimal .apk = a zip with a plain-XML AndroidManifest. Plain XML
    avoids depending on the AXML decoder for this test."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", _INNER_APK_MANIFEST)
        zf.writestr("classes.dex", b"")  # placeholder — JADX will skip empty dex
    return path


def _build_bundle(path: Path, *, base: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(base, "base.apk")
        zf.write(base, "splits/config.arm64_v8a.apk")
    return path


# ─── tests ───────────────────────────────────────────────────────────────


def test_prepare_scan_path_returns_bundle_unchanged_for_plain_apk(tmp_path: Path) -> None:
    apk = _build_inner_apk(tmp_path / "single.apk")
    scan_path, cleanup = _prepare_scan_path(apk, tmp_path / "ws")
    assert scan_path == apk
    assert cleanup is None


def test_prepare_scan_path_extracts_base_for_bundle(tmp_path: Path) -> None:
    inner = _build_inner_apk(tmp_path / "_inner.apk")
    bundle = _build_bundle(tmp_path / "app.apkm", base=inner)
    scan_path, cleanup = _prepare_scan_path(bundle, tmp_path / "ws")
    try:
        assert scan_path != bundle
        assert scan_path.name == "base.apk"
        assert scan_path.exists()
        # Sniff the extracted file: should be a zip with the inner manifest.
        with zipfile.ZipFile(scan_path) as zf:
            assert "AndroidManifest.xml" in zf.namelist()
    finally:
        if cleanup is not None:
            import shutil
            shutil.rmtree(cleanup, ignore_errors=True)


def test_orchestrator_ingest_bundle_recovers_inner_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end ingest_apk against an .apkm — the project should have
    the inner package id and the bundle's sha256, not the outer zip's
    package-stem fallback."""
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))

    inner = _build_inner_apk(tmp_path / "_inner.apk")
    bundle = _build_bundle(tmp_path / "app.apkm", base=inner)
    bundle_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()

    nexus = MedusaNexus(NexusConfig.from_env())
    try:
        project = asyncio.run(nexus.ingest_apk(
            bundle, package_name="", version="unknown",
        ))
    finally:
        nexus.db.close()

    # Project carries the inner package id (apktool parsed it from the
    # extracted base manifest) and the BUNDLE's hash (analyst-facing
    # artefact pinning).
    assert project.package_name == "com.example.bundle"
    assert project.apk_sha256 == bundle_sha
    assert Path(project.apk_path) == bundle.resolve()
    # Attack surface is non-empty — the deep-link from the inner manifest
    # came through, which was the regression we're guarding against.
    assert project.attack_surface is not None
    assert any(
        "bundleapp://" in dl for dl in (project.attack_surface.deeplinks or [])
    ), f"deeplinks should include bundleapp://, got {project.attack_surface.deeplinks}"


def test_orchestrator_cleans_up_bundle_temp_dir_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp dir under workspace/playintel-uploads/ that holds the
    extracted base APK must be removed once ingest_apk returns. Leaks
    here would balloon the disk on bulk-scan deployments."""
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))

    inner = _build_inner_apk(tmp_path / "_inner.apk")
    bundle = _build_bundle(tmp_path / "app.apkm", base=inner)

    nexus = MedusaNexus(NexusConfig.from_env())
    upload_dir = nexus.config.workspace / "playintel-uploads"
    try:
        asyncio.run(nexus.ingest_apk(bundle, package_name="", version="unknown"))
    finally:
        nexus.db.close()

    # No bundle-base-* tempdirs left behind.
    leftovers = (
        list(upload_dir.glob("bundle-base-*")) if upload_dir.exists() else []
    )
    assert leftovers == [], f"orchestrator left temp dirs behind: {leftovers}"
