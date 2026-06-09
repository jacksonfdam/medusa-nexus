"""Pure-function tests for the deeplink detectors.

No file IO, no orchestrator — just synthesise an ``AttackSurface`` and
assert on the findings each rule produces. These are the foundation of
the chain-detection pipeline; if they regress, the chain correlator
goes blind.
"""

from __future__ import annotations

import pytest

from mnexus.intelligence.deeplink_audit import (
    audit_deeplinks,
    detect_applink_bridges,
    detect_permissive_routers,
)
from mnexus.models.attack_surface import AttackSurface, ExportedComponent
from mnexus.models.finding import Severity


def _exported(name: str, *, schemes=(), hosts=(), paths=(), unprotected=True) -> ExportedComponent:
    return ExportedComponent(
        name=name,
        component_type="activity",
        permission=None,
        intent_filters=[{
            "data_schemes": list(schemes),
            "data_hosts": list(hosts),
            "data_paths": list(paths),
        }],
        unprotected=unprotected,
    )


# ─── DeeplinkRouterAudit ───────────────────────────────────────────────


def test_router_with_many_internal_handlers_and_few_manifest_hosts_emits_high() -> None:
    """The textbook case from the 1-click ATO write-up: a `targetapp://`
    scheme that dispatches 100+ hosts but only declares ~10 in the
    manifest."""
    internal_hosts = [f"host{i}" for i in range(120)]
    surface = AttackSurface(
        exported_components=[_exported(
            "MainActivity",
            schemes=["targetapp"],
            hosts=internal_hosts[:8],  # 8 declared
        )],
        deeplinks=[f"targetapp://{h}/foo?x=1" for h in internal_hosts],
    )
    findings = detect_permissive_routers(surface)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.HIGH
    assert "targetapp://" in f.title
    assert "120" in f.evidence
    assert f.category.value == "inter-process-communication"
    assert f.remediation, "every HIGH finding must ship remediation"


def test_router_with_modest_breadth_emits_medium() -> None:
    """Below the HIGH threshold (50 hosts) the same exposure pattern
    still emits — just at MEDIUM. Catches early-stage permissive routers
    before they grow into the 100+ case."""
    internal_hosts = [f"host{i}" for i in range(15)]
    surface = AttackSurface(
        exported_components=[_exported("MainActivity", schemes=["targetapp"], hosts=internal_hosts[:2])],
        deeplinks=[f"targetapp://{h}/foo" for h in internal_hosts],
    )
    findings = detect_permissive_routers(surface)
    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM


def test_router_with_full_manifest_coverage_does_not_emit() -> None:
    """If every internal host is also declared in the manifest, the
    router is doing its job — no smell, no finding."""
    hosts = ["a", "b", "c", "d", "e", "f"]
    surface = AttackSurface(
        exported_components=[_exported("MainActivity", schemes=["targetapp"], hosts=hosts)],
        deeplinks=[f"targetapp://{h}/foo" for h in hosts],
    )
    assert detect_permissive_routers(surface) == []


def test_router_below_minimum_handler_count_does_not_emit() -> None:
    """An activity with < 5 internal handlers isn't a router — it's just
    an activity that takes a deeplink. No finding."""
    surface = AttackSurface(
        exported_components=[_exported("MainActivity", schemes=["targetapp"], hosts=["a"])],
        deeplinks=["targetapp://a/x", "targetapp://b/x", "targetapp://c/x"],
    )
    assert detect_permissive_routers(surface) == []


def test_router_ignores_http_and_https_schemes() -> None:
    """http(s) belong in the AppLink bridge detector, not the custom-
    router one. They should never trigger this rule even if the surface
    has many."""
    surface = AttackSurface(
        deeplinks=[f"https://host{i}.foo.com/page" for i in range(60)],
    )
    assert detect_permissive_routers(surface) == []


# ─── AppLinkBridgeDetector ─────────────────────────────────────────────


def test_applink_bridge_detector_fires_on_open_path() -> None:
    """The `/open?page=…` shape from the canonical write-up — exact match."""
    surface = AttackSurface(
        exported_components=[_exported(
            "MainActivity",
            schemes=["https"],
            hosts=["applink.victim.com"],
            paths=["/open"],
        )],
        deeplinks=[
            "https://applink.victim.com/open?page=targetapp://popupPanel?url=https://x",
        ],
    )
    findings = detect_applink_bridges(surface)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.HIGH
    assert "App Link bridge" in f.title
    assert "popupPanel" in f.evidence  # the inner deeplink shows up
    assert f.remediation
    assert "javascript:" in f.remediation  # the canonical mitigation mentions it


def test_applink_bridge_detector_fires_on_alternate_path_names() -> None:
    """`/deeplink`, `/redirect`, `/route` — all bridge-shaped."""
    for path in ("/deeplink", "/redirect", "/route", "/p", "/launch"):
        surface = AttackSurface(
            exported_components=[_exported(
                "Router",
                schemes=["https"],
                hosts=["x.foo.com"],
                paths=[path],
            )],
            deeplinks=[f"https://x.foo.com{path}?url=targetapp://internal"],
        )
        assert detect_applink_bridges(surface), f"{path} should trigger bridge detector"


def test_applink_bridge_detector_does_not_fire_on_normal_https_filter() -> None:
    """A regular https intent-filter for a marketing page (e.g.
    `/product/123`) shouldn't trigger the bridge detector."""
    surface = AttackSurface(
        exported_components=[_exported(
            "ProductActivity",
            schemes=["https"],
            hosts=["shop.foo.com"],
            paths=["/product"],
        )],
        deeplinks=["https://shop.foo.com/product/123"],
    )
    assert detect_applink_bridges(surface) == []


def test_applink_bridge_emits_even_without_inner_deeplink_examples() -> None:
    """Signal A (bridge-shaped path) alone is enough. Signal B (inner
    deeplink query params) just enriches the evidence."""
    surface = AttackSurface(
        exported_components=[_exported(
            "MainActivity",
            schemes=["https"],
            hosts=["applink.x.com"],
            paths=["/open"],
        )],
        deeplinks=[],  # no examples in surface yet — bridge intent-filter alone
    )
    findings = detect_applink_bridges(surface)
    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


# ─── public audit_deeplinks() ──────────────────────────────────────────


def test_audit_deeplinks_runs_both_rules_and_unions_results() -> None:
    """The orchestrator's entry point should produce findings from both
    detectors when both signals are present."""
    surface = AttackSurface(
        exported_components=[
            _exported("MainActivity",
                      schemes=["targetapp", "https"],
                      hosts=["applink.foo.com"],
                      paths=["/open"]),
        ],
        deeplinks=[f"targetapp://{h}/x" for h in (f"h{i}" for i in range(60))]
                  + ["https://applink.foo.com/open?page=targetapp://popup"],
    )
    findings = audit_deeplinks(surface)
    # One permissive-router (HIGH) + one applink-bridge (HIGH) = 2.
    titles = sorted(f.title for f in findings)
    assert len(findings) == 2, [f.title for f in findings]
    assert any("Permissive deeplink router" in t for t in titles)
    assert any("App Link bridge" in t for t in titles)


def test_audit_deeplinks_on_empty_surface_is_silent() -> None:
    """A clean surface produces no findings — empty list, not None or crash."""
    assert audit_deeplinks(AttackSurface()) == []
