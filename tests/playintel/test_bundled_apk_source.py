"""Bundled APK source tests — .apkm / .apks / .xapk handling.

The fixtures synthesise minimal bundles that exercise the three
shapes the source needs to handle:

  * APKMirror layout: ``base.apk`` + ``config.<abi>.apk`` at top level.
  * Bundletool layout: ``base/base.apk`` + ``splits/config.<abi>.apk``.
  * Mis-extension: an .apk file whose contents are actually a bundle.
  * Wrong-base: a bundle without ``base.apk`` — the source must fall
    back to the largest .apk inside.

The end-to-end test verifies the analyzer picks up credentials from
both the base APK and a split, proving the splits loop runs against
the bundled contents.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from mnexus.playintel.analyzer import analyze_package
from mnexus.playintel.apk_source import (
    BundledAPKSource,
    LocalAPKSource,
    _looks_like_bundle,
    local_source_for,
)


# ─── helpers ─────────────────────────────────────────────────────────────


def _build_inner_apk(
    path: Path,
    *,
    package: str,
    google_services: dict | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """A minimal valid .apk = a zip with a manifest + optional payload."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AndroidManifest.xml", f"<manifest package=\"{package}\"/>")
        if google_services is not None:
            zf.writestr("assets/google-services.json", json.dumps(google_services))
        for name, blob in (extra_files or {}).items():
            zf.writestr(name, blob)
    return path


def _build_bundle(
    path: Path,
    *,
    base_path_inside: str,
    base_apk: Path,
    splits: dict[str, Path] | None = None,
) -> Path:
    """Wrap inner APKs into an outer .apkm / .apks shaped zip."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(base_apk, base_path_inside)
        for inner_name, split_apk in (splits or {}).items():
            zf.write(split_apk, inner_name)
    return path


# ─── detection ───────────────────────────────────────────────────────────


def test_looks_like_bundle_recognises_nested_apk(tmp_path: Path) -> None:
    inner = _build_inner_apk(tmp_path / "inner.apk", package="com.x")
    bundle = _build_bundle(tmp_path / "out.apkm", base_path_inside="base.apk", base_apk=inner)
    assert _looks_like_bundle(bundle) is True


def test_looks_like_bundle_rejects_plain_apk(tmp_path: Path) -> None:
    apk = _build_inner_apk(tmp_path / "single.apk", package="com.x")
    assert _looks_like_bundle(apk) is False


def test_looks_like_bundle_rejects_non_zip(tmp_path: Path) -> None:
    p = tmp_path / "not-a-zip.apkm"
    p.write_bytes(b"this is not a zip file at all")
    assert _looks_like_bundle(p) is False


# ─── factory ─────────────────────────────────────────────────────────────


def test_local_source_for_returns_local_for_single_apk(tmp_path: Path) -> None:
    apk = _build_inner_apk(tmp_path / "single.apk", package="com.x")
    src = local_source_for(apk)
    assert isinstance(src, LocalAPKSource)


def test_local_source_for_returns_bundled_for_apkm(tmp_path: Path) -> None:
    inner = _build_inner_apk(tmp_path / "inner.apk", package="com.x")
    bundle = _build_bundle(tmp_path / "out.apkm", base_path_inside="base.apk", base_apk=inner)
    src = local_source_for(bundle, workspace=tmp_path / "ws")
    assert isinstance(src, BundledAPKSource)
    src.close()


def test_local_source_for_detects_misnamed_bundle(tmp_path: Path) -> None:
    """An .apk file whose CONTENT is a bundle is still detected."""
    inner = _build_inner_apk(tmp_path / "inner.apk", package="com.x")
    bundle_named_apk = _build_bundle(
        tmp_path / "lookslikeapk.apk", base_path_inside="base.apk", base_apk=inner
    )
    src = local_source_for(bundle_named_apk, workspace=tmp_path / "ws")
    assert isinstance(src, BundledAPKSource)
    src.close()


# ─── BundledAPKSource extraction ─────────────────────────────────────────


@pytest.fixture()
def apkm_bundle(tmp_path: Path) -> Iterator[Path]:
    """APKMirror-shaped: base.apk + config.arm64_v8a.apk at top level."""
    base = _build_inner_apk(
        tmp_path / "_base.apk",
        package="com.bundle.alpha",
        google_services={
            "project_info": {"project_id": "bundle-alpha", "project_number": "111"},
            "client": [{"api_key": [{"current_key": "AIzaSyBundleBaseKey0000000000000000000"}]}],
        },
    )
    split = _build_inner_apk(
        tmp_path / "_split.apk",
        package="com.bundle.alpha",
        # Stash a confirmed credential pattern in the SPLIT to prove
        # the splits loop is wired up.
        extra_files={"assets/secrets.pem": b"github_token=ghp_0123456789abcdefABCDEFghijklmnoPQRST\n"},
    )
    bundle = _build_bundle(
        tmp_path / "alpha.apkm",
        base_path_inside="base.apk",
        base_apk=base,
        splits={"config.arm64_v8a.apk": split},
    )
    yield bundle


def test_bundle_get_download_info_separates_base_from_splits(
    apkm_bundle: Path, tmp_path: Path
) -> None:
    src = BundledAPKSource(apkm_bundle, workspace=tmp_path / "ws")
    try:
        info = src.get_download_info("com.bundle.alpha")
        assert Path(info.base_url).name == "base.apk"
        assert info.base_size > 0
        assert len(info.splits) == 1
        assert info.splits[0].name == "config.arm64_v8a"
    finally:
        src.close()


def test_bundle_close_removes_temp_dir(apkm_bundle: Path, tmp_path: Path) -> None:
    src = BundledAPKSource(apkm_bundle, workspace=tmp_path / "ws")
    tmp_dir = src._tmp_dir  # noqa: SLF001 — verifying the cleanup contract
    assert tmp_dir is not None and tmp_dir.exists()
    src.close()
    assert not tmp_dir.exists()


def test_bundle_context_manager_cleans_up(apkm_bundle: Path, tmp_path: Path) -> None:
    with BundledAPKSource(apkm_bundle, workspace=tmp_path / "ws") as src:
        tmp_dir = src._tmp_dir  # noqa: SLF001
        assert tmp_dir.exists()
    assert not tmp_dir.exists()


def test_bundle_falls_back_to_largest_apk_when_no_base(tmp_path: Path) -> None:
    """When the bundle has no entry literally named base.apk, the
    largest .apk wins — that's the Bundletool guarantee."""
    big = _build_inner_apk(
        tmp_path / "_big.apk",
        package="com.x",
        extra_files={"padding.bin": b"\x00" * 4096},  # forces it to be larger
    )
    small = _build_inner_apk(tmp_path / "_small.apk", package="com.x")
    bundle = _build_bundle(
        tmp_path / "no_base.apkm",
        base_path_inside="config.armv7.apk",
        base_apk=big,
        splits={"config.x86.apk": small},
    )
    with BundledAPKSource(bundle, workspace=tmp_path / "ws") as src:
        info = src.get_download_info("com.x")
        # The "big" inner apk got picked as base.
        assert info.base_size >= 4096


def test_bundle_handles_bundletool_nested_layout(tmp_path: Path) -> None:
    """`bundletool build-apks` puts files at ``base/base.apk`` +
    ``splits/config.<abi>.apk``. The path-tail fallback must recognise
    this without depending on the exact prefix."""
    base = _build_inner_apk(tmp_path / "_b.apk", package="com.x")
    split = _build_inner_apk(tmp_path / "_s.apk", package="com.x")
    bundle = _build_bundle(
        tmp_path / "out.apks",
        base_path_inside="base/base.apk",
        base_apk=base,
        splits={"splits/config.arm64_v8a.apk": split},
    )
    with BundledAPKSource(bundle, workspace=tmp_path / "ws") as src:
        info = src.get_download_info("com.x")
        # base.apk is identified even though it's nested under base/.
        # The flattened temp filename keeps the path components joined
        # (so "base/base.apk" → "base_base.apk") to avoid collisions
        # with same-named entries elsewhere; what matters here is that
        # the right entry was picked as the base.
        assert Path(info.base_url).name.endswith("base.apk")
        # Splits get a clean human-readable name (no path prefix, no .apk).
        assert info.splits[0].name == "config.arm64_v8a"


def test_bundle_rejects_zip_with_no_apks(tmp_path: Path) -> None:
    bundle = tmp_path / "empty.apkm"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("README.txt", "no apks here")
    # _looks_like_bundle should refuse it (no .apk entries).
    assert _looks_like_bundle(bundle) is False


# ─── analyzer end-to-end ─────────────────────────────────────────────────


def test_analyzer_picks_up_credentials_from_base_and_splits(
    apkm_bundle: Path, tmp_path: Path
) -> None:
    """Smoke-test the whole pipeline: the analyzer should recover the
    Firebase config from the base APK AND the github_token from the
    split, proving the splits loop is wired up against bundled contents.
    """
    with BundledAPKSource(apkm_bundle, workspace=tmp_path / "ws") as src:
        outcome = analyze_package(
            src,
            "com.bundle.alpha",
            workspace=tmp_path / "ws",
            run_active_probes=False,
        )

    fb = [c for c in outcome.report.firebase_configs if c.project_id]
    assert any(c.project_id == "bundle-alpha" for c in fb), (
        "Firebase project from base.apk should be recovered"
    )
    confirmed = outcome.report.confirmed_secrets()
    assert any(s.type == "GitHub Token" for s in confirmed), (
        "credential from the SPLIT apk should be recovered (proves splits loop ran)"
    )
