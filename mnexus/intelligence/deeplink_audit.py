"""Deeplink router auditing — two pure-Python detectors that run over
``AttackSurface`` data without needing bytecode access.

Both target the chain documented in the canonical 1-click ATO write-up
(see ``docs-site/content/workflows/chain-detection.mdx``):

  ``DeeplinkRouterAudit``      — A scheme router exposes many more hosts
                                  internally than the manifest declares.
                                  Smell: a 100+ handler ``Map<String,Handler>``
                                  keyed on ``uri.getHost()`` where the
                                  manifest's browsable intent-filters
                                  cover < 30% of the routes. Means a
                                  malicious app on the device (or a
                                  carefully-shaped intent) can reach
                                  handlers the developer assumed were
                                  internal-only.

  ``AppLinkBridgeDetector``    — An ``https://applink.foo.com/open?page=…``
                                  -style intent-filter that re-parses the
                                  ``page`` query into a URI and feeds it
                                  back into the scheme router. Turns
                                  every "internal" handler into a
                                  browser-triggerable one — the bridge
                                  that promotes a local exploit to a
                                  1-click attack.

The detectors are pure functions over the surface, so they're trivially
unit-testable and run in <1 ms on any reasonably-sized app.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from mnexus.models.attack_surface import AttackSurface, ExportedComponent
from mnexus.models.finding import Finding, FindingCategory, Severity


# ─── shared helpers ────────────────────────────────────────────────────


def _scheme_and_host(uri: str) -> tuple[str, str]:
    """Best-effort (scheme, host) extraction.

    Handles both proper URLs (``targetapp://popupPanel?url=…``) and
    intent-shaped strings (``intent://applink.foo.com/open#Intent;…``).
    Returns ``("", "")`` on parse failure.
    """
    try:
        u = urlparse(uri)
        scheme = u.scheme.lower() if u.scheme else ""
        # urlparse splits intent:// schemes weirdly; .netloc holds the host.
        host = u.netloc.lower() if u.netloc else ""
        # Intent URI with embedded scheme — recover real host from path[0]
        if not host and u.path:
            host = u.path.split("/", 2)[1] if u.path.startswith("/") and "/" in u.path[1:] else u.path
        return scheme, host
    except Exception:
        return "", ""


def _intent_filter_hosts(component: ExportedComponent) -> set[str]:
    """Pull every (scheme, host) pair declared on a component's intent-filters.

    Returns hosts only; schemes get tracked separately because Android lets
    you stack <data scheme="..."> and <data host="..."> independently.
    """
    hosts: set[str] = set()
    for f in component.intent_filters:
        for h in f.get("data_hosts") or []:
            if isinstance(h, str) and h:
                hosts.add(h.lower())
        # Some engines flatten the intent-filter to {"host": [...], "scheme": [...]}.
        for h in f.get("host") or f.get("hosts") or []:
            if isinstance(h, str) and h:
                hosts.add(h.lower())
    return hosts


def _intent_filter_schemes(component: ExportedComponent) -> set[str]:
    schemes: set[str] = set()
    for f in component.intent_filters:
        for s in (f.get("data_schemes") or f.get("scheme") or f.get("schemes") or []):
            if isinstance(s, str) and s:
                schemes.add(s.lower())
    return schemes


def _intent_filter_paths(component: ExportedComponent) -> set[str]:
    paths: set[str] = set()
    for f in component.intent_filters:
        for p in (f.get("data_paths") or f.get("path") or f.get("paths") or
                  f.get("path_prefixes") or f.get("path_patterns") or []):
            if isinstance(p, str) and p:
                paths.add(p)
    return paths


# ─── DeeplinkRouterAudit ───────────────────────────────────────────────


# Thresholds tuned against real-world apps. A router with < 5 internal
# handlers isn't a "router," it's just an activity. Above 50 with low
# manifest exposure is the textbook permissive-router pattern.
_ROUTER_MIN_INTERNAL = 5
_ROUTER_HIGH_INTERNAL = 50
_ROUTER_EXPOSURE_FLOOR = 0.3   # < 30% of internal hosts also in manifest = suspect


def detect_permissive_routers(surface: AttackSurface) -> list[Finding]:
    """Find scheme routers that handle more hosts than the manifest declares.

    Process:
      1. Group surface.deeplinks by scheme — each scheme is a candidate router.
      2. Collect manifest-declared hosts for that scheme from intent-filters.
      3. Flag when the internal host set is much larger than manifest-declared.

    Emits one finding per offending scheme.
    """
    by_scheme: dict[str, set[str]] = defaultdict(set)
    for uri in surface.deeplinks:
        scheme, host = _scheme_and_host(uri)
        if not scheme or scheme in ("http", "https"):
            # http/https belong in App Link analysis, not custom-router.
            continue
        if host:
            by_scheme[scheme].add(host)

    manifest_hosts_by_scheme: dict[str, set[str]] = defaultdict(set)
    for comp in surface.exported_components:
        schemes = _intent_filter_schemes(comp)
        hosts = _intent_filter_hosts(comp)
        for s in schemes:
            if s in ("http", "https"):
                continue
            manifest_hosts_by_scheme[s].update(hosts)

    findings: list[Finding] = []
    for scheme, internal in by_scheme.items():
        if len(internal) < _ROUTER_MIN_INTERNAL:
            continue
        manifest = manifest_hosts_by_scheme.get(scheme, set())
        hidden = internal - manifest
        exposure = (len(internal & manifest) / len(internal)) if internal else 1.0

        if not hidden:
            continue
        if exposure >= _ROUTER_EXPOSURE_FLOOR:
            continue

        is_critical_breadth = len(internal) >= _ROUTER_HIGH_INTERNAL
        severity = Severity.HIGH if is_critical_breadth else Severity.MEDIUM

        sample_hidden = sorted(hidden)[:8]
        evidence = (
            f"scheme `{scheme}://` routes to {len(internal)} internal host(s); "
            f"manifest declares only {len(manifest)}. "
            f"Hidden routes (sample): {', '.join(sample_hidden)}"
            + (" …" if len(hidden) > 8 else "")
        )
        remediation = (
            f"Audit every handler reachable via `{scheme}://`. For each one:\n"
            "  1. Decide if it ever needs to be reachable from outside the app.\n"
            "  2. If NO → remove it from the router dispatch table.\n"
            "  3. If YES → declare the host explicitly in `<intent-filter>` so\n"
            "     the surface matches the runtime behaviour, and treat the\n"
            "     handler as untrusted input (validate all query params).\n\n"
            "Pattern fix: replace the open `Map<String,Handler>` lookup with\n"
            "an allowlist of `(host, handler)` pairs gated by a single\n"
            "`getRoutableHosts()` source of truth shared with the manifest\n"
            "generator. Anything else is invisible API surface.\n\n"
            "See also: docs-site/content/workflows/chain-detection.mdx — link\n"
            "1 in the `1-click_account_takeover_via_deeplink_chain` template."
        )
        findings.append(Finding(
            title=f"Permissive deeplink router for scheme `{scheme}://`",
            description=(
                f"The app dispatches {len(internal)} distinct host(s) under the "
                f"custom `{scheme}://` scheme, but only {len(manifest)} are "
                f"declared in the manifest's intent-filters. "
                f"{len(hidden)} handler(s) are reachable from any process on the "
                "device but invisible at audit time — the foundational link in "
                "every 1-click deeplink-chain attack."
            ),
            severity=severity,
            category=FindingCategory.IPC,
            source_engine="deeplink_audit",
            evidence=evidence,
            location="AndroidManifest.xml + deeplink router class",
            cwe_id="CWE-940",  # Improper verification of source of communication
            owasp_mobile="M1",  # Improper Credential Usage / Platform Misuse
            masvs="MSTG-PLATFORM-3",
            remediation=remediation,
            platform_hint="android",
        ))
    return findings


# ─── AppLinkBridgeDetector ─────────────────────────────────────────────


# Path segments that historically mean "I'm a generic re-dispatcher".
_BRIDGE_PATHS = (
    "/open", "/deeplink", "/page", "/redirect", "/r", "/p",
    "/applink", "/link", "/route", "/launch", "/jump",
)

# Query param keys that hold inner deeplinks. Order matters for the report.
_BRIDGE_PARAMS = ("page", "url", "deeplink", "target", "redirect", "uri", "next", "to", "link")

_DEEPLINK_QUERY_RE = re.compile(
    r"[?&](" + "|".join(_BRIDGE_PARAMS) + r")=",
    re.IGNORECASE,
)


def detect_applink_bridges(surface: AttackSurface) -> list[Finding]:
    """Find http(s) entrypoints that re-parse a query param into another deeplink.

    Two-signal detection:
      A. An exported activity declares an http(s) intent-filter with a path
         like ``/open`` / ``/deeplink`` / ``/redirect``.
      B. The surface's deeplinks include URLs that carry one of the
         well-known bridge query params (``?page=…``, ``?url=…``, …).

    When BOTH are present, the app almost certainly turns its browser
    entrypoint into a router for internal deeplinks — the bridge that
    upgrades any local handler exploit to a 1-click attack.
    """
    # Signal A: bridge-shaped intent-filters.
    bridges: list[tuple[str, str, str]] = []   # (component_name, host, path)
    for comp in surface.exported_components:
        schemes = _intent_filter_schemes(comp)
        if not (schemes & {"http", "https"}):
            continue
        hosts = _intent_filter_hosts(comp)
        paths = _intent_filter_paths(comp)
        for path in paths:
            path_norm = path if path.startswith("/") else f"/{path}"
            # Exact match OR prefix followed by a slash — so `/p` matches
            # `/p` and `/p/123` but not `/product`.
            if any(path_norm == b or path_norm.startswith(b + "/") for b in _BRIDGE_PATHS):
                for host in hosts or {"(any)"}:
                    bridges.append((comp.name, host, path_norm))

    if not bridges:
        return []

    # Signal B: deeplinks that carry an embedded inner-deeplink param.
    bridge_examples: list[str] = []
    for uri in surface.deeplinks:
        if _DEEPLINK_QUERY_RE.search(uri):
            bridge_examples.append(uri)
            if len(bridge_examples) >= 4:
                break

    # Even without Signal B we still emit — having a bridge-shaped path
    # alone on an http(s) intent-filter is already a HIGH-severity smell.
    # Signal B just upgrades the evidence quality.
    severity = Severity.HIGH

    evidence_lines = ["bridge-shaped intent-filters:"]
    for name, host, path in bridges[:6]:
        evidence_lines.append(f"  · {name}  ←  https://{host}{path}")
    if bridge_examples:
        evidence_lines.append("")
        evidence_lines.append("deeplinks carrying inner-deeplink params:")
        for ex in bridge_examples:
            evidence_lines.append(f"  · {ex[:120]}")

    remediation = (
        "Treat the bridge handler as the most hostile entrypoint in the app:\n"
        "  1. Validate the inner deeplink against a strict allowlist of\n"
        "     (scheme, host, path) tuples BEFORE re-dispatching.\n"
        "  2. Refuse to re-dispatch anything containing `javascript:`,\n"
        "     `file:`, `intent:`, `content:`, or `data:` schemes.\n"
        "  3. Strip auth-bearing query params (`token=`, `code=`,\n"
        "     `id_token=`) before forwarding — even to internal routes.\n"
        "  4. Log every dispatch with the source intent's caller package\n"
        "     so abuse is visible in telemetry.\n\n"
        "Pattern fix: split the AppLink-entry activity from the scheme-\n"
        "router so the bridge can apply tighter validation than the\n"
        "internal handlers expect.\n\n"
        "See also: docs-site/content/workflows/chain-detection.mdx — link\n"
        "2 in the `1-click_account_takeover_via_deeplink_chain` template."
    )

    return [Finding(
        title="App Link bridge re-dispatches into internal deeplink router",
        description=(
            "An exported https intent-filter (used for App Link verification) "
            "forwards traffic into the custom-scheme router, turning every "
            "internal handler — including those not declared in the manifest — "
            "into a browser-reachable entrypoint. Required to upgrade any "
            "scheme-router exploit into a 1-click attack chain."
        ),
        severity=severity,
        category=FindingCategory.IPC,
        source_engine="deeplink_audit",
        evidence="\n".join(evidence_lines),
        location="AndroidManifest.xml + bridge activity",
        cwe_id="CWE-601",  # URL Redirection to Untrusted Site ('Open Redirect')
        owasp_mobile="M1",
        masvs="MSTG-PLATFORM-3",
        remediation=remediation,
        platform_hint="android",
    )]


# ─── public entrypoint ─────────────────────────────────────────────────


def audit_deeplinks(surface: AttackSurface) -> list[Finding]:
    """Run both detectors and return the union of findings.

    Called from the orchestrator's intelligence phase after the static
    fan-out finishes populating ``surface.deeplinks`` and
    ``surface.exported_components``.
    """
    out: list[Finding] = []
    out.extend(detect_permissive_routers(surface))
    out.extend(detect_applink_bridges(surface))
    return out
