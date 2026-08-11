"""Attack planner — static surface → concrete exploitation attempts (offline)."""

from __future__ import annotations

from pathlib import Path

from mnexus.intelligence.attack_planner import plan_attacks
from mnexus.models.attack_surface import AttackSurface, ExportedComponent
from mnexus.models.exploit import ExploitAttempt, ExploitVerdict, PocKind
from mnexus.models.finding import Finding, FindingCategory, Severity
from mnexus.models.project import Project


def _project(surface: AttackSurface) -> Project:
    return Project(
        name="t", apk_path=Path("/tmp/t.apk"), apk_sha256="0" * 64,
        package_name="com.target.app", version_name="1.0", attack_surface=surface,
    )


def _finding(**kw) -> Finding:
    base = {
        "title": "x", "description": "d", "severity": Severity.HIGH,
        "category": FindingCategory.IPC, "source_engine": "jadx",
        "evidence": "e", "remediation": "fix it constant-time",
    }
    base.update(kw)
    return Finding(**base)  # type: ignore[arg-type]


def test_empty_surface_plans_nothing() -> None:
    assert plan_attacks(_project(AttackSurface())) == []


def test_unprotected_activity_yields_adb_poc() -> None:
    s = AttackSurface(exported_components=[
        ExportedComponent(name=".ui.Deep", component_type="activity", unprotected=True),
    ])
    plan = plan_attacks(_project(s))
    act = [a for a in plan if a.technique == "exported-activity"]
    assert len(act) == 1
    assert act[0].poc_kind is PocKind.ADB
    assert act[0].verdict is ExploitVerdict.PROVABLE
    assert "am start -n" in act[0].poc
    assert "com.target.app/.ui.Deep" in act[0].poc
    assert act[0].requires_device is True
    assert act[0].mitigation  # never empty


def test_protected_component_is_skipped() -> None:
    s = AttackSurface(exported_components=[
        ExportedComponent(name=".Safe", component_type="activity", unprotected=False),
    ])
    assert not [a for a in plan_attacks(_project(s)) if a.technique.startswith("exported")]


def test_service_and_receiver_use_right_verbs() -> None:
    s = AttackSurface(exported_components=[
        ExportedComponent(name=".Svc", component_type="service", unprotected=True),
        ExportedComponent(name=".Rcv", component_type="receiver", unprotected=True),
    ])
    plan = {a.technique: a for a in plan_attacks(_project(s))}
    assert "am startservice" in plan["exported-service"].poc
    assert "am broadcast" in plan["exported-receiver"].poc


def test_provider_degrades_to_manual() -> None:
    s = AttackSurface(exported_components=[
        ExportedComponent(name=".Cp", component_type="provider", unprotected=True),
    ])
    prov = [a for a in plan_attacks(_project(s)) if a.technique == "exported-provider"][0]
    assert prov.verdict is ExploitVerdict.MANUAL
    assert prov.poc_kind is PocKind.NONE


def test_deeplink_yields_am_view_poc() -> None:
    s = AttackSurface(deeplinks=["myapp://pay?to=x"])
    dl = [a for a in plan_attacks(_project(s)) if a.technique == "deeplink"][0]
    assert "am start -W -a android.intent.action.VIEW -d" in dl.poc
    assert "myapp://pay?to=x" in dl.poc


def test_ssl_pinning_yields_frida_bypass() -> None:
    s = AttackSurface(ssl_pinning_detected=True, ssl_pinning_library="okhttp")
    ssl = [a for a in plan_attacks(_project(s)) if a.technique == "ssl-pin-bypass"]
    assert len(ssl) == 1
    assert ssl[0].poc_kind is PocKind.FRIDA
    assert ssl[0].poc.strip()  # a real script, not empty


def test_firebase_finding_yields_curl_poc() -> None:
    f = _finding(
        title="Firebase RTDB world-readable",
        evidence="database_url=https://target-app.firebaseio.com",
        category=FindingCategory.NETWORK, severity=Severity.CRITICAL,
        remediation="Lock the rules to auth != null.",
    )
    s = AttackSurface(findings=[f])
    fb = [a for a in plan_attacks(_project(s)) if a.technique == "firebase-open-db"][0]
    assert fb.poc_kind is PocKind.CURL
    assert "target-app.firebaseio.com/.json" in fb.poc
    assert fb.finding_id == f.id


def test_uncovered_high_finding_becomes_manual() -> None:
    # STORAGE has no auto-template (unlike AUTH, which the hook synthesiser
    # turns into a method tracer) → it falls through to the MANUAL fallback.
    f = _finding(title="Insecure backup flag", category=FindingCategory.STORAGE, severity=Severity.HIGH)
    s = AttackSurface(findings=[f])
    manual = [a for a in plan_attacks(_project(s)) if a.verdict is ExploitVerdict.MANUAL]
    assert len(manual) == 1
    assert manual[0].finding_id == f.id
    assert manual[0].mitigation == "fix it constant-time"


def test_auth_finding_gets_a_tracer_not_manual() -> None:
    # AUTH findings map to a Frida method tracer, so they're "covered" and
    # never padded with a MANUAL entry.
    f = _finding(title="token String.equals", category=FindingCategory.AUTH, severity=Severity.HIGH)
    plan = plan_attacks(_project(AttackSurface(findings=[f])))
    assert any(a.technique == "method-tracer" and a.finding_id == f.id for a in plan)
    assert not any(a.verdict is ExploitVerdict.MANUAL for a in plan)


def test_low_severity_uncovered_finding_is_not_padded() -> None:
    f = _finding(title="minor", severity=Severity.LOW, category=FindingCategory.CODE, remediation=None)
    s = AttackSurface(findings=[f])
    assert plan_attacks(_project(s)) == []  # no template, not a blocker → skip


def test_manual_attempt_forces_none_poc_kind() -> None:
    a = ExploitAttempt(
        technique="x", title="t", verdict=ExploitVerdict.MANUAL, poc_kind=PocKind.ADB,
        poc="adb shell whoami", rationale="r", mitigation="m",
    )
    assert a.poc_kind is PocKind.NONE  # validator scrubs the runnable kind
