"""Chain correlator — matches templates over finding sets, emits chain findings."""

from __future__ import annotations

import pytest

from mnexus.intelligence.chain_correlator import (
    ATO_1CLICK_CHAIN,
    ChainCorrelator,
    ChainLink,
    ChainTemplate,
    any_of,
    correlate_chains,
)
from mnexus.models.finding import Finding, FindingCategory, Severity


def _f(title: str, *, source_engine: str = "x", severity: Severity = Severity.HIGH) -> Finding:
    """Build a Finding for tests. Always carries remediation so the model invariant passes."""
    return Finding(
        title=title,
        description="test",
        severity=severity,
        category=FindingCategory.WEBVIEW,
        source_engine=source_engine,
        evidence="snippet",
        remediation="test remediation",
    )


# ─── ChainLink ────────────────────────────────────────────────────────


def test_chainlink_matches_by_source_engine_and_title() -> None:
    link = ChainLink(title_contains="permissive", source_engine="deeplink_audit")
    assert link.matches(_f("Permissive deeplink router", source_engine="deeplink_audit"))
    assert not link.matches(_f("Permissive deeplink router", source_engine="other_engine"))
    assert not link.matches(_f("Unrelated finding", source_engine="deeplink_audit"))


def test_chainlink_min_severity_floor() -> None:
    link = ChainLink(title_contains="x", min_severity=Severity.HIGH)
    assert link.matches(_f("x", severity=Severity.HIGH))
    assert link.matches(_f("x", severity=Severity.CRITICAL))
    assert not link.matches(_f("x", severity=Severity.MEDIUM))


def test_any_of_matches_when_any_option_matches() -> None:
    bundle = any_of(
        ChainLink(title_contains="bridge"),
        ChainLink(title_contains="router"),
    )
    assert bundle.matches(_f("App Link bridge"))
    assert bundle.matches(_f("Permissive deeplink router"))
    assert not bundle.matches(_f("Unrelated"))


# ─── ChainCorrelator ──────────────────────────────────────────────────


def test_correlator_emits_chain_finding_when_all_links_present() -> None:
    """The canonical 1-click ATO chain: 4 contributing findings → 1 CRITICAL."""
    findings = [
        _f("Permissive deeplink router for scheme `targetapp://`", source_engine="deeplink_audit"),
        _f("Dangerous scheme(s) whitelisted in WebView: javascript", source_engine="webview_audit"),
        _f("Intent redirection in WebView shouldOverrideUrlLoading", source_engine="webview_audit"),
        _f("Authenticated WebView loads URLs with auth headers attached", source_engine="webview_audit"),
    ]
    chain_findings = ChainCorrelator([ATO_1CLICK_CHAIN]).match(findings)
    assert len(chain_findings) == 1
    chain = chain_findings[0]
    assert chain.severity == Severity.CRITICAL
    assert "1-click account takeover" in chain.title
    assert chain.source_engine == "chain_correlator"
    # Evidence references each contributing finding id.
    for f in findings:
        assert f.id in chain.evidence
    # Remediation lists all four break-points.
    assert "Bridge / router" in chain.remediation
    assert "scheme allowlist" in chain.remediation


def test_correlator_does_not_emit_when_one_link_missing() -> None:
    """Drop the WebView intent-redirect finding → chain shouldn't match.
    Three other links present but the chain requires all four."""
    findings = [
        _f("Permissive deeplink router for scheme `targetapp://`", source_engine="deeplink_audit"),
        _f("Dangerous scheme(s) whitelisted in WebView: javascript", source_engine="webview_audit"),
        # missing intent redirection
        _f("Authenticated WebView loads URLs with auth headers attached", source_engine="webview_audit"),
    ]
    assert ChainCorrelator([ATO_1CLICK_CHAIN]).match(findings) == []


def test_correlator_accepts_either_bridge_or_router_as_entry() -> None:
    """The entry link is `any_of(App Link bridge, Permissive router)`.
    Either is sufficient — both don't need to be present."""
    findings_with_router = [
        _f("Permissive deeplink router for scheme `x://`", source_engine="deeplink_audit"),
        _f("Dangerous scheme(s) whitelisted in WebView: javascript", source_engine="webview_audit"),
        _f("Intent redirection in WebView shouldOverrideUrlLoading", source_engine="webview_audit"),
        _f("Authenticated WebView loads URLs with auth headers attached", source_engine="webview_audit"),
    ]
    findings_with_bridge = [
        _f("App Link bridge re-dispatches into internal deeplink router", source_engine="deeplink_audit"),
        _f("Dangerous scheme(s) whitelisted in WebView: javascript", source_engine="webview_audit"),
        _f("Intent redirection in WebView shouldOverrideUrlLoading", source_engine="webview_audit"),
        _f("Authenticated WebView loads URLs with auth headers attached", source_engine="webview_audit"),
    ]
    assert ChainCorrelator([ATO_1CLICK_CHAIN]).match(findings_with_router)
    assert ChainCorrelator([ATO_1CLICK_CHAIN]).match(findings_with_bridge)


def test_correlator_does_not_mutate_input() -> None:
    findings = [_f("anything")]
    before = list(findings)
    ChainCorrelator([ATO_1CLICK_CHAIN]).match(findings)
    assert findings == before


def test_correlate_chains_convenience_runs_default_catalogue() -> None:
    """The module-level helper uses DEFAULT_CHAINS — should match the
    1-click ATO when all four ingredients are present."""
    findings = [
        _f("Permissive deeplink router for scheme `targetapp://`", source_engine="deeplink_audit"),
        _f("Dangerous scheme(s) whitelisted in WebView: javascript", source_engine="webview_audit"),
        _f("Intent redirection in WebView shouldOverrideUrlLoading", source_engine="webview_audit"),
        _f("Authenticated WebView loads URLs with auth headers attached", source_engine="webview_audit"),
    ]
    chains = correlate_chains(findings)
    assert len(chains) == 1
    assert chains[0].severity == Severity.CRITICAL


def test_correlator_silent_on_empty_input() -> None:
    assert ChainCorrelator([ATO_1CLICK_CHAIN]).match([]) == []
    assert correlate_chains([]) == []


# ─── extensibility — custom templates ─────────────────────────────────


def test_custom_chain_template_works() -> None:
    """Future chains will be added as data; verify the harness supports
    arbitrary templates."""
    tmpl = ChainTemplate(
        name="custom_test_chain",
        title="Test chain",
        description="for test",
        severity=Severity.HIGH,
        category=FindingCategory.IPC,
        requires=(
            ChainLink(title_contains="alpha"),
            ChainLink(title_contains="beta"),
        ),
        remediation="break either link",
    )
    findings = [_f("alpha condition"), _f("beta condition")]
    chains = ChainCorrelator([tmpl]).match(findings)
    assert len(chains) == 1
    assert chains[0].title == "Test chain"
    assert chains[0].severity == Severity.HIGH
