"""HookGenerator — auto-hook synthesis from static findings.

Focus: the method tracer that used to emit a placeholder now resolves a
class from ``finding.location`` and traces it for real, and degrades to an
honest scaffold when it can't.
"""

from __future__ import annotations

import pytest

from mnexus.intelligence.hook_generator import HookGenerator, _fqcn_from_location
from mnexus.models.finding import Finding, FindingCategory, Severity


def _auth(location: str | None) -> Finding:
    """An AUTH finding — the category HookGenerator wires to _method_tracer."""
    return Finding(
        title="Auth token compared with String.equals",
        description="test",
        severity=Severity.HIGH,
        category=FindingCategory.AUTH,
        source_engine="jadx",
        evidence="if (token.equals(expected)) { ... }",
        location=location,
        remediation="Use a constant-time comparison (MessageDigest.isEqual).",
    )


# ─── _fqcn_from_location ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("sources/com/target/auth/LoginManager.java:42", "com.target.auth.LoginManager"),
        ("sources/com/target/auth/LoginManager.java", "com.target.auth.LoginManager"),
        ("smali/com/target/Foo.smali", "com.target.Foo"),
        ("smali_classes3/com/target/Bar.smali", "com.target.Bar"),
        ("com/target/auth/Outer$Inner.java", "com.target.auth.Outer$Inner"),
        ("src/main/java/com/x/Y.kt:9", "com.x.Y"),
    ],
)
def test_fqcn_resolves_class_paths(location: str, expected: str) -> None:
    assert _fqcn_from_location(location) == expected


@pytest.mark.parametrize(
    "location",
    [
        None,
        "",
        "AndroidManifest.xml:12",       # not a source class
        "res/values/strings.xml",       # resource, no class suffix
        "some free-text location",      # no extension, has spaces
    ],
)
def test_fqcn_rejects_non_class_locations(location: str | None) -> None:
    assert _fqcn_from_location(location) is None


# ─── _method_tracer via the public surface ────────────────────────────


def test_tracer_emits_real_hook_when_class_resolves() -> None:
    gen = HookGenerator()
    hook = gen._method_tracer(_auth("sources/com/target/auth/LoginManager.java:42"))
    assert "com.target.auth.LoginManager" in hook.script
    assert "getDeclaredMethods" in hook.script      # actually enumerates methods
    assert "placeholder" not in hook.script         # the stub is gone
    assert hook.source_finding_id is not None
    assert "com.target.auth.LoginManager" in hook.description


def test_tracer_degrades_to_scaffold_without_class() -> None:
    gen = HookGenerator()
    hook = gen._method_tracer(_auth(None))
    assert "getDeclaredMethods" not in hook.script
    assert "edit me" in hook.script                 # honest scaffold, not a fake trace
    assert "not auto-resolved" in hook.description


def test_auth_findings_get_a_tracer_from_attack_surface() -> None:
    """End-to-end: an AUTH finding in the surface yields a tracer hook."""
    from mnexus.models.attack_surface import AttackSurface

    surface = AttackSurface(findings=[_auth("sources/com/target/auth/LoginManager.java:42")])
    hooks = HookGenerator().for_attack_surface(surface, platform="android")
    tracers = [h for h in hooks if h.name.startswith("tracer::")]
    assert len(tracers) == 1
    assert "com.target.auth.LoginManager" in tracers[0].script
