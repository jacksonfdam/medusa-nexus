"""Traffic-derived findings — turn captured HTTP flows into security alerts.

Burp / Caido / Moxy all give us request + response pairs. This module
chews them into ``Finding`` objects so the Network tab + findings
timeline reflect what the proxy actually saw, not just what the static
scanners guessed.

Detection rules (each rule is one function + one severity bucket):

  * ``cleartext_http``  HIGH    — host in the project's surface served
                                  over ``http://``; either the app
                                  ignores android:usesCleartextTraffic
                                  or the manifest sets it to true.
                                  CWE-319 · MSTG-NETWORK-1.

  * ``jwt_leak_body``   HIGH    — response body carries something that
                                  looks like a JWT. Could be the app's
                                  own session token, could be a
                                  third-party's — either way it shouldn't
                                  be readable from a MITM position. CWE-522.

  * ``insecure_cookie`` MEDIUM  — ``Set-Cookie`` header without
                                  ``Secure`` or ``HttpOnly``. CWE-614.

  * ``api_key_in_url``  HIGH    — Authorization-shaped tokens
                                  (``api_key=``, ``access_token=``,
                                  ``key=AIza…``) in the URL query
                                  string. Bookmark + log leaks. CWE-598.

  * ``discovered_host`` INFO    — host the proxy saw that the static
                                  api_endpoints list doesn't claim.
                                  Surface area the static engines missed.

  * ``5xx_run``         LOW     — same host + path returning >= 3 5xx
                                  during the window. Server-side
                                  fragility; reportable as an
                                  availability concern.

Every rule emits findings carrying a concrete ``remediation`` block —
the model layer rejects CRITICAL/HIGH without one.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from mnexus.models.finding import Finding, FindingCategory, Severity


_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_AIZA_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{30,}")
_QUERY_TOKEN_KEYS = ("api_key", "apikey", "access_token", "accesstoken", "token", "auth")


def findings_for_flows(
    flows: list[dict[str, Any]],
    *,
    surface_hosts: set[str] | None = None,
    source_engine: str = "moxy",
) -> list[Finding]:
    """Run every rule and return the union of findings.

    ``flows`` shape matches what ``MoxyEngine._normalise_flow`` emits:
    ``{method, host, path, url, status, size, ts, ...}`` plus optional
    ``raw_request``/``raw_response`` for header sniffing.

    ``surface_hosts`` is the set of hosts the static scan recovered.
    Used to dedupe ``discovered_host`` findings and to gate
    ``cleartext_http`` so we don't yell about ambient noise (gstatic,
    google analytics) that the app never claimed to talk to.
    """
    surface_hosts = surface_hosts or set()
    findings: list[Finding] = []
    findings.extend(_rule_cleartext_http(flows, surface_hosts, source_engine))
    findings.extend(_rule_jwt_leak_body(flows, surface_hosts, source_engine))
    findings.extend(_rule_insecure_cookie(flows, surface_hosts, source_engine))
    findings.extend(_rule_api_key_in_url(flows, surface_hosts, source_engine))
    findings.extend(_rule_discovered_host(flows, surface_hosts, source_engine))
    findings.extend(_rule_5xx_run(flows, surface_hosts, source_engine))
    return findings


# ─── rules ────────────────────────────────────────────────────────────


def _rule_cleartext_http(
    flows: list[dict[str, Any]],
    surface_hosts: set[str],
    source_engine: str,
) -> list[Finding]:
    """Plain HTTP to a host the app actually talks to."""
    seen_pairs: set[tuple[str, str]] = set()  # (host, path)
    out: list[Finding] = []
    for f in flows:
        url = str(f.get("url") or "")
        if not url.startswith("http://"):
            continue
        host = f.get("host") or urlparse(url).hostname or ""
        if not host or host not in surface_hosts:
            continue
        path = f.get("path") or "/"
        if (host, path) in seen_pairs:
            continue
        seen_pairs.add((host, path))
        out.append(Finding(
            title=f"Cleartext HTTP to {host}",
            description=(
                f"The app contacted {host} over plain HTTP at {path}. Any "
                "active attacker on the same network reads + tampers with "
                "the body in transit. The static surface lists this host, "
                "so this isn't ambient noise — it's the app's own traffic."
            ),
            severity=Severity.HIGH,
            category=FindingCategory.NETWORK,
            source_engine=source_engine,
            evidence=f"{f.get('method', 'GET')} {url}",
            location=host + path,
            cwe_id="CWE-319",
            owasp_mobile="M3",
            masvs="MSTG-NETWORK-1",
            platform_hint="android",
            remediation=(
                "Move the endpoint to HTTPS. In AndroidManifest.xml set "
                "`android:usesCleartextTraffic=\"false\"` on the "
                "application element, and add a network_security_config.xml "
                "that pins `cleartextTrafficPermitted=\"false\"` on the "
                "target domain. If the server doesn't support TLS yet, "
                "block the request client-side until it does — quietly "
                "downgrading is worse than failing loudly."
            ),
        ))
    return out


def _rule_jwt_leak_body(
    flows: list[dict[str, Any]],
    surface_hosts: set[str],
    source_engine: str,
) -> list[Finding]:
    """Response body carries something shaped like a JWT.

    We can't tell if it's the app's own token (legitimate, but should be
    HTTPS-only — handled by cleartext_http rule) or a third-party
    credential the app leaked. Either way, the analyst wants to know.
    """
    out: list[Finding] = []
    seen_hosts: set[str] = set()
    for f in flows:
        raw_response = f.get("raw_response") or ""
        if not raw_response:
            continue
        _, _, body = raw_response.partition("\r\n\r\n")
        match = _JWT_PATTERN.search(body)
        if not match:
            continue
        host = f.get("host") or ""
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        # Redact the middle segment — the signature reveals nothing,
        # but the header + payload may carry kid/issuer info worth
        # showing in the finding.
        token = match.group(0)
        header_b64, payload_b64, _ = token.split(".", 2)
        redacted = f"{header_b64}.{payload_b64}.<sig>"
        out.append(Finding(
            title=f"JWT visible in MITM response from {host}",
            description=(
                f"A token matching the JWT pattern was decoded in the "
                f"plaintext response body from {host}. Visible from a MITM "
                "position means the token isn't pinned, or the pinning "
                "bypass is active — verify which before treating this as "
                "an incident."
            ),
            severity=Severity.HIGH,
            category=FindingCategory.AUTH,
            source_engine=source_engine,
            evidence=redacted,
            location=host + str(f.get("path") or "/"),
            cwe_id="CWE-522",
            owasp_mobile="M5",
            masvs="MSTG-AUTH-1",
            platform_hint="android",
            remediation=(
                "If this is the app's own session token: confirm TLS + "
                "certificate pinning are active (this finding is the "
                "smoking gun otherwise). If it's a third-party token "
                "echoed back, audit the response — the server shouldn't "
                "be returning credentials at all. Rotate immediately if "
                "the analyst captured this on a network they don't own."
            ),
        ))
    return out


def _rule_insecure_cookie(
    flows: list[dict[str, Any]],
    surface_hosts: set[str],
    source_engine: str,
) -> list[Finding]:
    """``Set-Cookie`` without ``Secure`` or ``HttpOnly`` flags."""
    out: list[Finding] = []
    seen_pairs: set[tuple[str, str]] = set()
    for f in flows:
        raw_response = f.get("raw_response") or ""
        if not raw_response:
            continue
        head, _, _ = raw_response.partition("\r\n\r\n")
        for line in head.split("\r\n"):
            if not line.lower().startswith("set-cookie:"):
                continue
            value = line.split(":", 1)[1].strip()
            lower = value.lower()
            missing = []
            if "secure" not in lower:
                missing.append("Secure")
            if "httponly" not in lower:
                missing.append("HttpOnly")
            if not missing:
                continue
            host = f.get("host") or ""
            cookie_name = value.split("=", 1)[0]
            key = (host, cookie_name)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            out.append(Finding(
                title=f"Set-Cookie '{cookie_name}' missing {' + '.join(missing)} on {host}",
                description=(
                    f"The cookie '{cookie_name}' on {host} ships without "
                    f"the {', '.join(missing)} flag(s). Without Secure, it "
                    "rides over plain HTTP; without HttpOnly, any injected "
                    "WebView script reads it."
                ),
                severity=Severity.MEDIUM,
                category=FindingCategory.NETWORK,
                source_engine=source_engine,
                evidence=f"Set-Cookie: {value[:120]}",
                location=host,
                cwe_id="CWE-614",
                owasp_mobile="M5",
                masvs="MSTG-NETWORK-3",
                platform_hint="android",
            ))
    return out


def _rule_api_key_in_url(
    flows: list[dict[str, Any]],
    surface_hosts: set[str],
    source_engine: str,
) -> list[Finding]:
    """Query string carries credential-shaped values."""
    out: list[Finding] = []
    seen_hosts: set[str] = set()
    for f in flows:
        url = str(f.get("url") or "")
        if "?" not in url:
            continue
        parsed = urlparse(url)
        query_lower = parsed.query.lower()
        host = f.get("host") or parsed.hostname or ""
        if host in seen_hosts:
            continue
        # Check both shape-based (AIza...) and key-name patterns.
        if _AIZA_PATTERN.search(parsed.query) or any(
            k + "=" in query_lower for k in _QUERY_TOKEN_KEYS
        ):
            seen_hosts.add(host)
            # Redact the actual key from the evidence — query gets
            # logged into the report, no need to ship live secrets.
            redacted_query = re.sub(
                rf"({'|'.join(_QUERY_TOKEN_KEYS)}|api_key|key)=[^&]+",
                r"\1=<redacted>",
                parsed.query,
                flags=re.IGNORECASE,
            )
            redacted_query = _AIZA_PATTERN.sub("AIza<redacted>", redacted_query)
            out.append(Finding(
                title=f"Credential-shaped value in URL query on {host}",
                description=(
                    f"A request to {host}{parsed.path} carried a token in "
                    "the query string. URLs are persisted by proxies, "
                    "browser history, and server access logs — anything "
                    "sensitive belongs in the request body or an "
                    "Authorization header instead."
                ),
                severity=Severity.HIGH,
                category=FindingCategory.AUTH,
                source_engine=source_engine,
                evidence=f"{parsed.path}?{redacted_query}",
                location=host + parsed.path,
                cwe_id="CWE-598",
                owasp_mobile="M9",
                masvs="MSTG-AUTH-3",
                platform_hint="android",
                remediation=(
                    "Move the credential out of the query string. Send it "
                    "as an `Authorization: Bearer <token>` header (or "
                    "`X-API-Key:` for non-OAuth APIs). Verify the server "
                    "doesn't log full URLs by default — most do."
                ),
            ))
    return out


def _rule_discovered_host(
    flows: list[dict[str, Any]],
    surface_hosts: set[str],
    source_engine: str,
) -> list[Finding]:
    """Hosts the proxy saw that the static scan didn't claim."""
    hosts_seen: set[str] = set()
    for f in flows:
        host = (f.get("host") or "").strip()
        if not host:
            continue
        if host in surface_hosts:
            continue
        hosts_seen.add(host)
    out: list[Finding] = []
    for host in sorted(hosts_seen):
        out.append(Finding(
            title=f"Live host not in static surface: {host}",
            description=(
                f"The proxy captured at least one request to {host}, but "
                "the static api_endpoints list doesn't claim it. Either "
                "the static URL-extraction missed a string, or the host "
                "is loaded dynamically (remote config, Firebase Remote "
                "Config, native code)."
            ),
            severity=Severity.INFO,
            category=FindingCategory.NETWORK,
            source_engine=source_engine,
            evidence=host,
            location=host,
            masvs="MSTG-NETWORK-2",
            platform_hint="android",
        ))
    return out


def _rule_5xx_run(
    flows: list[dict[str, Any]],
    surface_hosts: set[str],  # noqa: ARG001 — kept for symmetry, unused for this rule
    source_engine: str,
) -> list[Finding]:
    """Same (host, path) returning >= 3 5xx during the window."""
    counter: Counter[tuple[str, str]] = Counter()
    for f in flows:
        status = f.get("status")
        if not isinstance(status, int) or status < 500:
            continue
        host = f.get("host") or ""
        path = f.get("path") or "/"
        if host:
            counter[(host, path)] += 1
    out: list[Finding] = []
    for (host, path), n in counter.items():
        if n < 3:
            continue
        out.append(Finding(
            title=f"5xx run on {host}{path} ({n} hits)",
            description=(
                f"The endpoint returned a 5xx {n} times during this "
                "capture window — server-side fragility that an attacker "
                "could weaponise into a DoS or rely on for state-corruption "
                "windows. Worth a note in the report."
            ),
            severity=Severity.LOW,
            category=FindingCategory.NETWORK,
            source_engine=source_engine,
            evidence=f"{host}{path} · {n} × 5xx",
            location=host + path,
            platform_hint="both",
        ))
    return out
