"""Tests for the LibraryAttributionAudit module.

Verifies that:
  * known-SDK paths attribute to the right vendor + category
  * the app's own namespace wins over any vendor match (first-party)
  * paths under no known prefix fall back to 'third-party (unknown)'
  * the secret-shaped fingerprint extractor catches the common formats
  * the locator-driven path (``attribute_finding``) produces high-confidence
    results when all hits agree on an owner
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mnexus.intelligence.library_attribution import (
    KNOWN_SDK_PREFIXES,
    _attribute_path,
    _extract_fingerprints,
    attribute_finding,
    attribute_findings,
)
from mnexus.models.finding import Finding, FindingCategory, Severity


# ─── path → owner unit tests ───────────────────────────────────────────


def test_first_party_wins_over_sdk_match() -> None:
    """A key inside the app's namespace is first-party, no matter what."""
    owner, conf, _ = _attribute_path(
        "jadx/sources/com/mcdonalds/mobileapp/Config.java",
        app_package="com.mcdonalds.mobileapp",
    )
    assert owner == "first-party"
    assert conf == "high"


def test_google_places_sdk_attribution() -> None:
    owner, conf, cat = _attribute_path(
        "jadx/sources/com/google/android/libraries/places/internal/zzcg.java",
        app_package="com.mcdonalds.mobileapp",
    )
    assert owner == "Google Places SDK"
    assert conf == "high"
    assert cat == "maps"


def test_firebase_under_google_namespace() -> None:
    """The Firebase prefix must beat any 'com/google' catch-all."""
    owner, _, cat = _attribute_path(
        "apktool/smali_classes2/com/google/firebase/messaging/Foo.smali",
        app_package="com.example.app",
    )
    assert owner == "Firebase"
    assert cat == "analytics"


def test_unknown_third_party_fallback() -> None:
    owner, conf, _ = _attribute_path(
        "jadx/sources/com/totallyrandom/vendor/Util.java",
        app_package="com.example.app",
    )
    assert owner == "third-party (unknown)"
    assert conf == "medium"


def test_secrets_tree_normalises_to_package_path() -> None:
    """Locator emits paths like ``secrets/<pkg>/...``; we must strip that."""
    owner, _, _ = _attribute_path(
        "secrets/com.example.app/com/google/android/libraries/places/Foo.java",
        app_package="com.example.app",
    )
    assert owner == "Google Places SDK"


# ─── fingerprint extractor unit tests ──────────────────────────────────


@pytest.mark.parametrize("evidence,expected_prefix", [
    ("snippet: AIzaSyA1234567890abcdefghijklmnopqrstuv in DEX strings",  "AIza"),
    ("AWS_KEY=AKIAIOSFODNN7EXAMPLE",                                       "AKIA"),
    ("token=sk_live_abcdefghijklmnopqrstuvwx",                             "sk_live"),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "eyJ"),
])
def test_fingerprint_extractor_catches_known_formats(evidence: str, expected_prefix: str) -> None:
    out = _extract_fingerprints(evidence)
    assert out, f"expected at least one fingerprint for {evidence!r}"
    assert any(f.startswith(expected_prefix) for f in out)


def test_fingerprint_extractor_empty_on_clean_evidence() -> None:
    assert _extract_fingerprints("debuggable=true in AndroidManifest.xml") == []


# ─── locator-driven attribution (with fake workspace) ──────────────────


def _make_finding(evidence: str) -> Finding:
    return Finding(
        title="Hardcoded Google API key shipped in APK",
        description="An AIza-prefixed key was found in DEX strings.",
        severity=Severity.HIGH,
        category=FindingCategory.STORAGE,
        source_engine="jadx",
        evidence=evidence,
        remediation="Rotate the key. Restrict it by package + SHA-1. Audit Maps/Places usage.",
    )


def test_attribute_finding_high_confidence_when_all_hits_agree(tmp_path: Path) -> None:
    project_id = "p-test"
    pid_dir = tmp_path / project_id / "jadx" / "sources" / "com" / "google" / "android" / "libraries" / "places" / "internal"
    pid_dir.mkdir(parents=True)
    key = "AIzaSyA1234567890abcdefghijklmnopqrstuv"
    (pid_dir / "zzcg.java").write_text(f'String K = "{key}";\n', encoding="utf-8")
    (pid_dir / "zzch.java").write_text(f'final String OTHER = "{key}";\n', encoding="utf-8")

    finding = _make_finding(f"AIza key extracted from DEX: {key}")
    result = attribute_finding(
        finding,
        workspace_dir=tmp_path,
        project_id=project_id,
        app_package="com.example.app",
    )
    assert result is not None
    assert result.attributed_to == "Google Places SDK"
    assert result.confidence == "high"
    assert result.sdk_category == "maps"
    assert result.paths, "attribution paths must be populated when hits exist"
    assert all("places" in p for p in result.paths)


def test_attribute_finding_returns_none_for_non_secret_evidence(tmp_path: Path) -> None:
    finding = Finding(
        title="debuggable=true in manifest",
        description="The app ships with android:debuggable=true.",
        severity=Severity.HIGH,
        category=FindingCategory.CODE,
        source_engine="apktool",
        evidence='android:debuggable="true" found in AndroidManifest.xml',
        remediation="Set android:debuggable=false in the release flavour.",
    )
    result = attribute_finding(
        finding,
        workspace_dir=tmp_path,
        project_id="p-test",
        app_package="com.example.app",
    )
    assert result is None


def test_attribute_finding_unknown_when_evidence_not_on_disk(tmp_path: Path) -> None:
    """If the fingerprint exists in evidence but the workspace was wiped,
    we still flag it — low-confidence unknown — rather than dropping it."""
    project_id = "p-test"
    (tmp_path / project_id).mkdir(parents=True)
    finding = _make_finding("AIzaSyA1234567890abcdefghijklmnopqrstuv shipped")
    result = attribute_finding(
        finding,
        workspace_dir=tmp_path,
        project_id=project_id,
        app_package="com.example.app",
    )
    assert result is not None
    assert result.attributed_to == "third-party (unknown)"
    assert result.confidence == "low"


def test_attribute_findings_mutates_in_place(tmp_path: Path) -> None:
    project_id = "p-test"
    pid_dir = tmp_path / project_id / "jadx" / "sources" / "com" / "amplitude"
    pid_dir.mkdir(parents=True)
    key = "AIzaSyBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    (pid_dir / "Tracker.java").write_text(f'public static final String K = "{key}";\n', encoding="utf-8")

    f1 = _make_finding(f"hardcoded key {key}")
    f2 = Finding(
        title="weak crypto", description="MD5 in use.", severity=Severity.MEDIUM,
        category=FindingCategory.CRYPTO, source_engine="jadx",
        evidence="MessageDigest.getInstance(\"MD5\")",
    )
    findings = [f1, f2]
    attribute_findings(findings, workspace_dir=tmp_path, project_id=project_id, app_package="com.example.app")
    assert f1.attributed_to == "Amplitude"
    assert f1.attribution_confidence == "high"
    assert f1.sdk_category == "analytics"
    # f2 has no fingerprint → untouched
    assert f2.attributed_to is None


# ─── sanity: every registered SDK has a non-empty owner + category ─────


def test_registry_is_well_formed() -> None:
    for prefix, name, category in KNOWN_SDK_PREFIXES:
        assert prefix, f"empty prefix: {prefix!r}"
        assert name, f"empty name for prefix {prefix!r}"
        assert category, f"empty category for prefix {prefix!r}"
