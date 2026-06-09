"""Chain correlator — turn N independent findings into one CRITICAL chain.

A single MEDIUM/HIGH bug is annoying. A specific *combination* of them
is an exploit. The chain correlator walks ``surface.findings`` looking
for documented attack-chain shapes and emits one CRITICAL finding per
matched chain, with the contributing findings linked as evidence.

The motivating example is the 1-click ATO chain from the canonical
write-up: a permissive deeplink router + an App Link bridge + a
dangerous WebView scheme allowlist + an intent redirector + an
authenticated WebView loading unchecked URLs. Each link is HIGH at
worst on its own. Together they're a one-click account takeover.

This file ships:

  * ``ChainLink``      — a predicate over ``Finding`` (matches by source
                         engine + title substring + optional severity
                         floor). Composable via ``any_of`` / ``all_of``.
  * ``ChainTemplate``  — name, severity, description, list of required
                         links, remediation template. Pure data.
  * ``ChainCorrelator``— runs a list of templates against a finding
                         set; emits one Finding per matched template.
  * Catalogued templates (currently 1; add more as new audits land).

Templates live alongside the correlator so adding a new chain is one
``ChainTemplate`` literal — no orchestrator changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from mnexus.models.finding import Finding, FindingCategory, Severity


# ─── primitives ────────────────────────────────────────────────────────


SEVERITY_ORDER = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


@dataclass(frozen=True)
class ChainLink:
    """A predicate that matches one finding.

    Combines source-engine + title-substring filters. Either both
    constraints apply (AND) or, if a field is empty, it's a wildcard.
    ``min_severity`` defaults to INFO so any matching finding qualifies;
    set it to filter low-quality evidence out of the chain.
    """

    title_contains: str = ""
    source_engine: str = ""
    min_severity: Severity = Severity.INFO

    def matches(self, finding: Finding) -> bool:
        if self.source_engine and finding.source_engine != self.source_engine:
            return False
        if self.title_contains and self.title_contains.lower() not in finding.title.lower():
            return False
        if SEVERITY_ORDER.index(finding.severity) < SEVERITY_ORDER.index(self.min_severity):
            return False
        return True


@dataclass(frozen=True)
class AnyOfLink:
    """OR-composition over multiple ChainLinks. Matches if any one matches."""

    options: tuple[ChainLink, ...]

    def matches(self, finding: Finding) -> bool:
        return any(opt.matches(finding) for opt in self.options)


def any_of(*links: ChainLink) -> AnyOfLink:
    return AnyOfLink(options=tuple(links))


Predicate = ChainLink | AnyOfLink


@dataclass(frozen=True)
class ChainTemplate:
    """A named attack-chain shape.

    A chain matches when *every* ``link`` predicate in ``requires`` has
    at least one matching finding in the input set. The correlator
    emits one Finding per template match, with evidence pointing at the
    matched finding ids.
    """

    name: str
    title: str
    description: str
    severity: Severity
    category: FindingCategory
    requires: tuple[Predicate, ...]
    remediation: str
    cwe_id: str = ""
    owasp_mobile: str = ""
    masvs: str = ""
    platform_hint: str = "android"


# ─── correlator ────────────────────────────────────────────────────────


class ChainCorrelator:
    """Stateless matcher — give it findings, get back chain findings."""

    def __init__(self, templates: Iterable[ChainTemplate]):
        self.templates = list(templates)

    def match(self, findings: list[Finding]) -> list[Finding]:
        """Run every template against the finding set; return new chain findings.

        Does NOT mutate the input list — caller decides whether to
        extend or replace. Typical use: extend, so individual links
        remain visible alongside the chain for drilldown.
        """
        out: list[Finding] = []
        for tmpl in self.templates:
            contributing = self._match_template(findings, tmpl)
            if contributing is None:
                continue
            out.append(self._build_chain_finding(tmpl, contributing))
        return out

    @staticmethod
    def _match_template(
        findings: list[Finding],
        tmpl: ChainTemplate,
    ) -> list[Finding] | None:
        """Return the list of contributing findings if the template matches.

        One finding per required link, in order. A template matches iff
        every link finds at least one supporting finding. Returns None
        on miss.
        """
        contributing: list[Finding] = []
        for link in tmpl.requires:
            matched = next((f for f in findings if link.matches(f)), None)
            if matched is None:
                return None
            contributing.append(matched)
        return contributing

    @staticmethod
    def _build_chain_finding(
        tmpl: ChainTemplate,
        contributing: list[Finding],
    ) -> Finding:
        evidence_lines = [f"Chain `{tmpl.name}` — {len(contributing)} link(s):"]
        for i, f in enumerate(contributing, 1):
            evidence_lines.append(f"  {i}. [{f.severity.value.upper():>8}] {f.id} · {f.title}")
        return Finding(
            title=tmpl.title,
            description=tmpl.description,
            severity=tmpl.severity,
            category=tmpl.category,
            source_engine="chain_correlator",
            evidence="\n".join(evidence_lines),
            location=contributing[0].location,
            cwe_id=tmpl.cwe_id or None,
            owasp_mobile=tmpl.owasp_mobile or None,
            masvs=tmpl.masvs or None,
            remediation=tmpl.remediation,
            platform_hint=tmpl.platform_hint,
        )


# ─── catalogued chain templates ────────────────────────────────────────


ATO_1CLICK_CHAIN = ChainTemplate(
    name="1-click_account_takeover_via_deeplink_chain",
    title="1-click account takeover via deeplink → WebView → intent-redirect chain",
    description=(
        "Five independently-MEDIUM/HIGH findings combine into a one-click "
        "account takeover. The chain: (1) an App Link bridge or permissive "
        "scheme router exposes internal deeplinks to the browser; (2) a "
        "handler forwards a URL parameter into a WebView without host "
        "validation; (3) the WebView's scheme allowlist accepts a "
        "dangerous scheme (typically `javascript`), enabling JS injection "
        "via the `javascript://anything%0a<payload>` comment-escape trick; "
        "(4) the WebViewClient's `shouldOverrideUrlLoading` calls "
        "`Intent.parseUri` and fires the result, letting the injected JS "
        "trigger any internal Activity; (5) an authenticated WebView "
        "Activity attaches auth headers to whatever URL it loads, "
        "exfiltrating the user's session token to the attacker's host."
    ),
    severity=Severity.CRITICAL,
    category=FindingCategory.WEBVIEW,
    cwe_id="CWE-940",
    owasp_mobile="M4",
    masvs="MSTG-PLATFORM-3",
    requires=(
        # Entry: anything that lets the browser reach the internal router.
        any_of(
            ChainLink(title_contains="App Link bridge", source_engine="deeplink_audit"),
            ChainLink(title_contains="Permissive deeplink router", source_engine="deeplink_audit", min_severity=Severity.MEDIUM),
        ),
        # Execution: dangerous scheme allowed in the WebView.
        ChainLink(title_contains="Dangerous scheme", source_engine="webview_audit"),
        # Redirection: Intent.parseUri sink.
        ChainLink(title_contains="Intent redirection", source_engine="webview_audit"),
        # Sink: authenticated WebView loads unchecked URLs.
        ChainLink(title_contains="auth headers", source_engine="webview_audit"),
    ),
    remediation=(
        "Break the chain at any one of these links — each break neutralises\n"
        "the entire attack:\n\n"
        "1. **Bridge / router** — validate every incoming inner-deeplink\n"
        "   against an allowlist of (scheme, host, path) tuples before\n"
        "   re-dispatching. Reject `javascript:`, `file:`, `intent:`,\n"
        "   `content:`, `data:` schemes outright.\n\n"
        "2. **WebView scheme allowlist** — drop everything except `http`\n"
        "   and `https`. If you genuinely need to execute JS, route through\n"
        "   `WebView.evaluateJavascript(...)` with a strict input check,\n"
        "   never through `loadUrl()`.\n\n"
        "3. **WebView intent redirect** — replace `Intent.parseUri()` with\n"
        "   an explicit `Map<String, Intent>` allowlist gated by host.\n"
        "   Always call `intent.setPackage(getPackageName())` to forbid\n"
        "   cross-app dispatch.\n\n"
        "4. **Authenticated WebView** — host-check before attaching headers.\n"
        "   `if (!isOurDomain(host)) webView.loadUrl(url);  // no headers`\n\n"
        "Break any *one* of these to kill the chain. Break all four for\n"
        "defence in depth. See the contributing findings (listed in\n"
        "evidence above) for the exact code-level fix per link.\n\n"
        "Reference: docs-site/content/workflows/chain-detection.mdx."
    ),
    platform_hint="android",
)


DEFAULT_CHAINS: tuple[ChainTemplate, ...] = (
    ATO_1CLICK_CHAIN,
    # Add more here as the audit catalogue grows:
    # TASK_HIJACKING_CHAIN, CLEARTEXT_TOKEN_LEAK_CHAIN, PROVIDER_TRAVERSAL_CHAIN, …
)


def correlate_chains(findings: list[Finding]) -> list[Finding]:
    """Convenience wrapper — runs the default chain catalogue.

    Returns new chain Findings; caller decides whether to extend or
    replace the originals. The orchestrator extends, so individual
    links remain visible in the findings list for drilldown.
    """
    return ChainCorrelator(DEFAULT_CHAINS).match(findings)
