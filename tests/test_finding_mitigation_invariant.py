"""Finding invariant: CRITICAL/HIGH must ship with remediation."""

from __future__ import annotations

import pytest

from mnexus.models.finding import Finding, FindingCategory, Severity


def test_critical_without_remediation_is_rejected() -> None:
    with pytest.raises(ValueError, match="remediation"):
        Finding(
            title="Hardcoded AES key",
            description="oops",
            severity=Severity.CRITICAL,
            category=FindingCategory.CRYPTO,
            source_engine="jadx",
            evidence="byte[] key = ...",
        )


def test_high_without_remediation_is_rejected() -> None:
    with pytest.raises(ValueError, match="remediation"):
        Finding(
            title="Legacy TrustManager pinning",
            description="bypassable",
            severity=Severity.HIGH,
            category=FindingCategory.NETWORK,
            source_engine="ghidra",
            evidence="new X509TrustManager() { ... }",
        )


def test_info_without_remediation_is_fine() -> None:
    f = Finding(
        title="Non-debuggable build",
        description="nothing to see",
        severity=Severity.INFO,
        category=FindingCategory.CODE,
        source_engine="apktool",
        evidence="android:debuggable=false",
    )
    assert f.severity is Severity.INFO
    assert f.remediation is None


def test_critical_with_remediation_is_accepted() -> None:
    f = Finding(
        title="Hardcoded key",
        description="x",
        severity=Severity.CRITICAL,
        category=FindingCategory.CRYPTO,
        source_engine="jadx",
        evidence="byte[] key = ...",
        remediation="Use Android Keystore instead. Rotate DEKs. Switch to AES/GCM.",
    )
    assert f.remediation is not None
    assert f.severity_weight == 10.0
