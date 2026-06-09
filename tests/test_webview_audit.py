"""WebView audit suite — pattern detectors over decompiled .java files.

We fake the decompiled tree with tmp_path + a handful of .java fixtures
that mimic the canonical bug shapes from the 1-click ATO write-up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mnexus.intelligence.webview_audit import (
    audit_webviews,
    detect_authenticated_webview_load,
    detect_dangerous_scheme_allowlist,
    detect_intent_redirect_in_webview_client,
)
from mnexus.models.finding import Severity


# ─── fixtures ─────────────────────────────────────────────────────────


def _write(workspace: Path, rel: str, content: str) -> Path:
    """Drop a fake decompiled .java file under workspace/sources/<rel>."""
    p = workspace / "sources" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# Canonical shapes — close to what jadx would emit for the article's app.

_INTENT_REDIRECT_JAVA = """
package com.app.victim.webview;

import android.content.Intent;
import android.webkit.WebView;
import android.webkit.WebViewClient;

class ContentWebClient extends WebViewClient {
    @Override
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
        if (url.startsWith("intent:")) {
            try {
                Intent intent = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                view.getContext().startActivity(intent);
                return true;
            } catch (Exception e) { /* swallow */ }
        }
        return false;
    }
}
""".strip()


_SCHEME_ALLOWLIST_JAVA = """
package com.app.victim.webview;

import android.webkit.WebView;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

class ContentWebView extends WebView {
    private static final Set<String> ALLOWED =
        new HashSet<>(Arrays.asList("http", "https", "javascript", "file"));

    boolean isPermittedScheme(String scheme) {
        return scheme != null && ALLOWED.contains(scheme.toLowerCase());
    }

    boolean isJavascriptUrl(String url) {
        return url != null && url.toLowerCase().startsWith("javascript")
            && scheme.equalsIgnoreCase("javascript");
    }
}
""".strip()


_AUTHED_LOAD_JAVA = """
package com.app.victim.webview;

import android.webkit.WebView;
import java.util.HashMap;
import java.util.Map;

class AccountHubActivity {
    private WebView webView;
    private String token;

    void loadInternalUrl(String url) {
        Map<String, String> headers = new HashMap<>();
        headers.put("Authorization", "Bearer " + token);
        headers.put("X-Custom-Auth", "v1");
        webView.loadUrl(url, headers);
    }
}
""".strip()


_INNOCENT_JAVA = """
package com.app.victim.unrelated;

class Helper {
    String greet(String name) { return "hello " + name; }
}
""".strip()


# ─── detector: intent redirect ────────────────────────────────────────


def test_intent_redirect_detected_in_should_override(tmp_path: Path) -> None:
    _write(tmp_path, "com/app/victim/webview/ContentWebClient.java", _INTENT_REDIRECT_JAVA)
    findings = detect_intent_redirect_in_webview_client(tmp_path)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.HIGH
    assert "Intent redirection" in f.title
    assert f.category.value == "webview"
    assert "ContentWebClient.java" in f.evidence
    assert f.remediation, "HIGH findings must carry remediation"


def test_intent_redirect_not_flagged_when_separate_methods(tmp_path: Path) -> None:
    """The two tokens must appear within the same method window. A file
    that has shouldOverrideUrlLoading in one spot and Intent.parseUri
    thousands of lines later (in an unrelated helper) should NOT trip."""
    _write(tmp_path, "Big.java",
           "class Big {\n"
           "  public boolean shouldOverrideUrlLoading(Object v, String url) { return false; }\n"
           + ("  // padding\n" * 2000)
           + "  void helper() { Intent.parseUri(\"x\", 0); }\n"
           "}\n")
    assert detect_intent_redirect_in_webview_client(tmp_path) == []


def test_intent_redirect_silent_on_innocent_tree(tmp_path: Path) -> None:
    _write(tmp_path, "Helper.java", _INNOCENT_JAVA)
    assert detect_intent_redirect_in_webview_client(tmp_path) == []


# ─── detector: dangerous scheme allowlist ─────────────────────────────


def test_dangerous_scheme_allowlist_javascript_emits_high(tmp_path: Path) -> None:
    _write(tmp_path, "ContentWebView.java", _SCHEME_ALLOWLIST_JAVA)
    findings = detect_dangerous_scheme_allowlist(tmp_path)
    assert len(findings) == 1
    f = findings[0]
    # The fixture allows `javascript` AND `file` → HIGH per the rule.
    assert f.severity == Severity.HIGH
    assert "javascript" in f.title or "file" in f.title
    assert f.remediation


def test_dangerous_scheme_silent_on_safe_allowlist(tmp_path: Path) -> None:
    safe = (
        "class C {\n"
        "  java.util.Set<String> a = java.util.Arrays.asList(\"http\", \"https\");\n"
        "  boolean ok(String s) { return s.equalsIgnoreCase(\"http\") || s.equalsIgnoreCase(\"https\"); }\n"
        "}\n"
    )
    _write(tmp_path, "Safe.java", safe)
    assert detect_dangerous_scheme_allowlist(tmp_path) == []


# ─── detector: authenticated WebView load ─────────────────────────────


def test_authed_webview_load_detected(tmp_path: Path) -> None:
    _write(tmp_path, "AccountHubActivity.java", _AUTHED_LOAD_JAVA)
    findings = detect_authenticated_webview_load(tmp_path)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.HIGH
    assert "auth headers" in f.title.lower() or "WebView" in f.title
    assert f.category.value == "authentication"


def test_authed_webview_load_silent_without_authorization_header(tmp_path: Path) -> None:
    benign = (
        "class C {\n"
        "  void f() {\n"
        "    webView.loadUrl(\"https://api.com\");\n"  # single-arg, no headers
        "  }\n"
        "}\n"
    )
    _write(tmp_path, "Benign.java", benign)
    assert detect_authenticated_webview_load(tmp_path) == []


def test_authed_webview_load_silent_when_no_webview(tmp_path: Path) -> None:
    """An OkHttp client adding Authorization headers isn't a WebView
    finding — the rule requires 'WebView' to also appear in the file."""
    src = (
        "class ApiClient {\n"
        "  void post(String url) {\n"
        "    Map h = new HashMap();\n"
        "    h.put(\"Authorization\", \"Bearer abc\");\n"
        "    httpClient.send(url, h);\n"
        "  }\n"
        "}\n"
    )
    _write(tmp_path, "ApiClient.java", src)
    assert detect_authenticated_webview_load(tmp_path) == []


# ─── public audit_webviews() ──────────────────────────────────────────


def test_audit_webviews_runs_all_three_rules(tmp_path: Path) -> None:
    """Drop fixtures for all three patterns; expect three findings."""
    _write(tmp_path, "ContentWebClient.java", _INTENT_REDIRECT_JAVA)
    _write(tmp_path, "ContentWebView.java", _SCHEME_ALLOWLIST_JAVA)
    _write(tmp_path, "AccountHubActivity.java", _AUTHED_LOAD_JAVA)
    findings = audit_webviews(tmp_path)
    titles = sorted(f.title for f in findings)
    assert len(findings) == 3, [f.title for f in findings]


def test_audit_webviews_on_missing_workspace_is_silent(tmp_path: Path) -> None:
    assert audit_webviews(tmp_path / "does-not-exist") == []
