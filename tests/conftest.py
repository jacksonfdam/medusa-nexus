"""Shared pytest fixtures — deliberately tiny."""

from __future__ import annotations

from pathlib import Path

import pytest

from mnexus.models.finding import Finding, FindingCategory, Severity
from mnexus.models.project import Project


@pytest.fixture
def sample_apk(tmp_path: Path) -> Path:
    """Fake APK — just bytes on disk so `Project.from_apk` has something to hash."""
    apk = tmp_path / "target.apk"
    apk.write_bytes(b"PK\x03\x04fake-apk-payload-for-tests")
    return apk


@pytest.fixture
def finding_critical_with_mitigation() -> Finding:
    return Finding(
        title="Hardcoded AES key",
        description="SecretKeySpec constructed from a hardcoded literal.",
        severity=Severity.CRITICAL,
        category=FindingCategory.CRYPTO,
        source_engine="jadx",
        evidence='byte[] key = "MedusaSays".getBytes();',
        location="com/target/crypto/KeyManager.java:42",
        cwe_id="CWE-798",
        owasp_mobile="M10",
        remediation="Move to Android Keystore; generate per-install; rotate DEKs.",
    )


@pytest.fixture
def finding_info_no_mitigation() -> Finding:
    return Finding(
        title="Debuggable flag noise",
        description="Release build wasn't debuggable. Informational.",
        severity=Severity.INFO,
        category=FindingCategory.CODE,
        source_engine="apktool",
        evidence="android:debuggable=false",
        location="AndroidManifest.xml",
    )


@pytest.fixture
def sample_project(sample_apk: Path, finding_critical_with_mitigation: Finding, finding_info_no_mitigation: Finding) -> Project:
    from mnexus.models.attack_surface import AttackSurface

    project = Project.from_apk(sample_apk, package_name="com.target.banking", version="4.12.0")
    project.attack_surface = AttackSurface(findings=[finding_critical_with_mitigation, finding_info_no_mitigation])
    return project
