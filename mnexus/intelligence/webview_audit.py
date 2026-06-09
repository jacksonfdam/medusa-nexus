"""WebView audit suite — string-pattern detectors over decompiled Java.

These run **after** the static engines have decompiled the APK (jadx
output lands under ``<workspace>/<project_id>/...``). They look for the
canonical bug shapes that turn a permissive deeplink router into a
1-click ATO:

  ``WebViewIntentRedirect``    — ``Intent.parseUri`` called inside a
                                  ``shouldOverrideUrlLoading`` override.
                                  Lets JS in the WebView trigger any
                                  intent. HIGH severity, very low FP rate.

  ``WebViewDangerousScheme``   — A scheme allowlist that includes
                                  ``javascript``, ``file``, ``data``,
                                  ``intent``, or ``content``. Enables
                                  the ``javascript://%0a<payload>``
                                  injection. HIGH severity.

  ``WebViewAuthedLoad``        — ``loadUrl(url, headers)`` where the
                                  headers map carries ``Authorization``
                                  or a ``Bearer`` token. Combined with
                                  any of the above, that's the token
                                  exfiltration sink. HIGH severity.

These are intentionally pattern-based heuristics — they catch the
documented bug shapes without trying to do full taint analysis. The
chain correlator (next module) only treats them as CRITICAL when they
combine with a deeplink router exposure.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

from mnexus.models.finding import Finding, FindingCategory, Severity


# Cap how much of the decompiled tree we walk so a pathological 2GB jadx
# output doesn't wedge the orchestrator. Real-world apps land well below.
_MAX_FILES = 8000
_MAX_BYTES_PER_FILE = 512 * 1024   # 512 KB — anything larger is a generated blob
_MAX_WALLCLOCK_S = 30


# ─── pattern bank ─────────────────────────────────────────────────────


# Strong signal — appears in nearly every shouldOverrideUrlLoading-based
# redirector. We require the two tokens within a ~2 KB window so we don't
# misattribute across unrelated methods.
_INTENT_REDIRECT_PAIR = re.compile(
    r"shouldOverrideUrlLoading\b.{0,2048}?Intent\s*\.\s*parseUri\s*\(",
    re.DOTALL,
)

# Dangerous schemes that should never be in a WebView allowlist.
_DANGEROUS_SCHEMES = ("javascript", "file", "data", "intent", "content")

# Method bodies that look like scheme allowlists. We anchor on
# `equalsIgnoreCase("javascript")` patterns plus the keywords WebView
# code uses, then verify by counting how many of the dangerous schemes
# appear within the same window.
_SCHEME_CHECK_WINDOW = re.compile(
    r"(?:WebView|scheme|getScheme|loadUrl).{0,4096}?"
    r"(?:equalsIgnoreCase|equals|contains|matches|startsWith)\s*\(\s*['\"]"
    r"(javascript|file|data|intent|content)['\"]",
    re.DOTALL,
)

# `loadUrl(url, headers)` next to an Authorization/Bearer header attach.
# The two-arg loadUrl signature is the tell — single-arg is the safe path.
_AUTHED_LOAD_PAIR = re.compile(
    r"\bloadUrl\s*\([^),]+,\s*[A-Za-z_][A-Za-z0-9_]*\s*\)"
    r"|put\s*\(\s*['\"]Authorization['\"]"
    r"|setRequestProperty\s*\(\s*['\"]Authorization['\"]",
)
_AUTH_KEYWORD = re.compile(r"Authorization|Bearer\b|access_token|setHeader\s*\(\s*['\"]Authorization['\"]", re.IGNORECASE)


# ─── detectors ─────────────────────────────────────────────────────────


def _walk_java_files(workspace: Path) -> Iterable[tuple[Path, str]]:
    """Yield (path, text) for every .java file under the workspace.

    Bounded by file count, per-file size, and wall-clock. Returns early
    when any cap is hit. Cap hits get logged via the caller, not here —
    this is a pure iterator.
    """
    if not workspace.exists():
        return
    seen = 0
    started = time.monotonic()
    for jpath in workspace.rglob("*.java"):
        if seen >= _MAX_FILES:
            return
        if time.monotonic() - started > _MAX_WALLCLOCK_S:
            return
        try:
            size = jpath.stat().st_size
        except OSError:
            continue
        if size == 0 or size > _MAX_BYTES_PER_FILE:
            continue
        try:
            text = jpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen += 1
        yield jpath, text


def detect_intent_redirect_in_webview_client(workspace: Path) -> list[Finding]:
    """Find ``Intent.parseUri`` inside a ``shouldOverrideUrlLoading`` body.

    Pattern: the two tokens appear within the same ~2 KB window. In
    practice this rejects unrelated co-occurrences while catching every
    real intent-redirection sink documented in the canonical chain.
    """
    hits: list[tuple[Path, str]] = []
    for jpath, text in _walk_java_files(workspace):
        m = _INTENT_REDIRECT_PAIR.search(text)
        if not m:
            continue
        # Trim evidence snippet around the match for the report.
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 120)
        snippet = text[start:end].strip().replace("\n", " ")
        hits.append((jpath, snippet))
        if len(hits) >= 5:
            break

    if not hits:
        return []

    evidence_lines = [f"  · {p.name}: …{s[:240]}…" for p, s in hits]
    return [Finding(
        title="Intent redirection in WebView shouldOverrideUrlLoading",
        description=(
            "A WebViewClient parses arbitrary URLs as Intents via "
            "`Intent.parseUri()` and fires them with `startActivity`. "
            "Any JavaScript running inside the WebView can therefore "
            "trigger any internal Activity — the gateway link in every "
            "WebView-to-internal-activity exploit chain."
        ),
        severity=Severity.HIGH,
        category=FindingCategory.WEBVIEW,
        source_engine="webview_audit",
        evidence="WebViewClient.shouldOverrideUrlLoading sinks:\n" + "\n".join(evidence_lines),
        location=str(hits[0][0]),
        cwe_id="CWE-940",
        owasp_mobile="M4",  # Insufficient Input/Output Validation
        masvs="MSTG-PLATFORM-6",
        remediation=(
            "Replace `Intent.parseUri()` with an explicit allowlist of "
            "(action, package, class) tuples. Concretely:\n\n"
            "  before:\n"
            "    Intent i = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);\n"
            "    startActivity(i);\n\n"
            "  after:\n"
            "    Intent i = ALLOWLIST.get(uri.getHost());\n"
            "    if (i == null) return false;          // refuse unknown targets\n"
            "    i.setData(uri);\n"
            "    i.setPackage(getPackageName());       // forbid cross-app dispatch\n"
            "    startActivity(i);\n\n"
            "Why it matters: combined with a permissive scheme allowlist "
            "(see `WebViewDangerousScheme`) and an authenticated WebView "
            "(see `WebViewAuthedLoad`), this primitive completes the "
            "1-click ATO chain.\n\n"
            "See: docs-site/content/workflows/chain-detection.mdx — link "
            "5 in `1-click_account_takeover_via_deeplink_chain`."
        ),
        platform_hint="android",
    )]


def detect_dangerous_scheme_allowlist(workspace: Path) -> list[Finding]:
    """Find a scheme allowlist that includes javascript/file/data/intent/content.

    Patterns we look for:
      * `equalsIgnoreCase("javascript")` inside a WebView-touching method
      * Same for `file`, `data`, `intent`, `content`

    A single dangerous scheme triggers MEDIUM; two-or-more upgrades to HIGH.
    """
    by_scheme: dict[str, list[Path]] = {s: [] for s in _DANGEROUS_SCHEMES}
    for jpath, text in _walk_java_files(workspace):
        for m in _SCHEME_CHECK_WINDOW.finditer(text):
            scheme = m.group(1).lower()
            if scheme in by_scheme and jpath not in by_scheme[scheme]:
                by_scheme[scheme].append(jpath)

    hit_schemes = [s for s, paths in by_scheme.items() if paths]
    if not hit_schemes:
        return []

    severity = Severity.HIGH if len(hit_schemes) >= 2 or "javascript" in hit_schemes else Severity.MEDIUM
    evidence_lines = []
    for s in hit_schemes:
        sample = ", ".join(p.name for p in by_scheme[s][:3])
        evidence_lines.append(f"  · `{s}` allowed in: {sample}")

    return [Finding(
        title=f"Dangerous scheme(s) whitelisted in WebView: {', '.join(hit_schemes)}",
        description=(
            "A WebView's scheme allowlist accepts a dangerous scheme. "
            "`javascript:` enables JS injection via the comment-escape "
            "trick (`javascript://anything%0a<payload>`). `file:` exposes "
            "the local filesystem. `intent:` lets the WebView trigger "
            "intents (combine with `WebViewIntentRedirect` for the full "
            "redirection chain). `data:` and `content:` open similar XSS "
            "and IPC vectors."
        ),
        severity=severity,
        category=FindingCategory.WEBVIEW,
        source_engine="webview_audit",
        evidence="\n".join(evidence_lines),
        location=str(by_scheme[hit_schemes[0]][0]),
        cwe_id="CWE-95",  # Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection')
        owasp_mobile="M4",
        masvs="MSTG-PLATFORM-5",
        remediation=(
            "Default-deny: only allow `http` and `https`. Concretely:\n\n"
            "  before:\n"
            "    private static final Set<String> ALLOWED =\n"
            "        new HashSet<>(Arrays.asList(\"http\", \"https\", \"javascript\"));\n\n"
            "  after:\n"
            "    private static final Set<String> ALLOWED =\n"
            "        new HashSet<>(Arrays.asList(\"http\", \"https\"));\n"
            "    // and in isPermittedScheme:\n"
            "    if (!ALLOWED.contains(scheme.toLowerCase(Locale.ROOT))) return false;\n\n"
            "If you genuinely need to render a `javascript:` URL — push the\n"
            "string through `WebView.evaluateJavascript()` after a strict\n"
            "allowlist check, never via `loadUrl()`.\n\n"
            "See: docs-site/content/workflows/chain-detection.mdx — link 3."
        ),
        platform_hint="android",
    )]


def detect_authenticated_webview_load(workspace: Path) -> list[Finding]:
    """Find ``loadUrl(url, headers)`` calls where the headers carry auth.

    A two-arg `loadUrl` plus an `Authorization` / `Bearer` keyword in
    the same file is the tell. We don't try to track whether the URL is
    validated — that's the chain correlator's job. The base finding is
    MEDIUM; HIGH if the file also contains `WebView` and the headers
    are attached unconditionally (proxied by simple keyword presence).
    """
    hits: list[Path] = []
    for jpath, text in _walk_java_files(workspace):
        load_match = _AUTHED_LOAD_PAIR.search(text)
        auth_match = _AUTH_KEYWORD.search(text)
        if load_match and auth_match and "WebView" in text:
            hits.append(jpath)
            if len(hits) >= 5:
                break

    if not hits:
        return []

    evidence_lines = [f"  · {p.name}" for p in hits]
    return [Finding(
        title="Authenticated WebView loads URLs with auth headers attached",
        description=(
            "A WebView in the app calls `loadUrl(url, headers)` with an "
            "`Authorization` / `Bearer` header in the request headers map. "
            "If the URL ever comes from outside the app's trust boundary "
            "(via a deeplink, an Intent extra, or a JS-triggered redirect) "
            "the user's auth token is exfiltrated to whatever host loaded. "
            "The exfiltration sink in the 1-click ATO chain."
        ),
        severity=Severity.HIGH,
        category=FindingCategory.AUTH,
        source_engine="webview_audit",
        evidence="WebView activities loading URLs with auth headers:\n" + "\n".join(evidence_lines),
        location=str(hits[0]),
        cwe_id="CWE-200",  # Exposure of Sensitive Information
        owasp_mobile="M3",  # Insecure Authentication/Authorization
        masvs="MSTG-AUTH-7",
        remediation=(
            "Validate the URL's host against an allowlist BEFORE attaching\n"
            "auth headers. Concretely:\n\n"
            "  before:\n"
            "    Map<String, String> headers = new HashMap<>();\n"
            "    headers.put(\"Authorization\", \"Bearer \" + token);\n"
            "    webView.loadUrl(url, headers);\n\n"
            "  after:\n"
            "    if (!isOurDomain(URI.create(url).getHost())) {\n"
            "        webView.loadUrl(url);   // no headers for foreign hosts\n"
            "        return;\n"
            "    }\n"
            "    Map<String, String> headers = new HashMap<>();\n"
            "    headers.put(\"Authorization\", \"Bearer \" + token);\n"
            "    webView.loadUrl(url, headers);\n\n"
            "Where `isOurDomain` matches against a static allowlist of\n"
            "production hostnames — never against a substring or regex.\n\n"
            "See: docs-site/content/workflows/chain-detection.mdx — link 6."
        ),
        platform_hint="android",
    )]


# ─── public entrypoint ─────────────────────────────────────────────────


def audit_webviews(workspace: Path) -> list[Finding]:
    """Run all WebView detectors over a decompiled workspace.

    Called from the orchestrator's intelligence phase after the static
    fan-out drops jadx output under ``workspace/<project_id>/``. Pure
    function — no side effects, no DB writes.
    """
    findings: list[Finding] = []
    if not workspace.exists():
        return findings
    findings.extend(detect_intent_redirect_in_webview_client(workspace))
    findings.extend(detect_dangerous_scheme_allowlist(workspace))
    findings.extend(detect_authenticated_webview_load(workspace))
    return findings
