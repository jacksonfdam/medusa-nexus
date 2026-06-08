"""traffic_findings — promote captured proxy flows to Finding objects.

Six rules; each has a fixture flow that triggers it and a fixture that
shouldn't (so the test pins both directions).
"""

from __future__ import annotations

from typing import Any

import pytest

from mnexus.intelligence.traffic_findings import findings_for_flows
from mnexus.models.finding import FindingCategory, Severity


def _flow(**kw: Any) -> dict[str, Any]:
    """Default flow with override-everything kwargs."""
    base = {
        "method": "GET",
        "url": "https://api.example.com/v1/me",
        "host": "api.example.com",
        "path": "/v1/me",
        "status": 200,
        "raw_request": "GET /v1/me HTTP/1.1\r\nHost: api.example.com\r\n\r\n",
        "raw_response": "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
        "ts": "2026-05-13T12:00:00Z",
    }
    base.update(kw)
    return base


# ─── cleartext_http ───────────────────────────────────────────────────


def test_cleartext_http_flags_known_host() -> None:
    flows = [_flow(url="http://api.example.com/v1/me", host="api.example.com")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert any(f.title.startswith("Cleartext HTTP") for f in out)
    finding = next(f for f in out if f.title.startswith("Cleartext HTTP"))
    assert finding.severity == Severity.HIGH
    assert finding.cwe_id == "CWE-319"
    assert finding.remediation  # HIGH requires it


def test_cleartext_http_ignores_ambient_hosts() -> None:
    """Cleartext to gstatic / google analytics shouldn't yell — only
    hosts the app actually claims in its surface."""
    flows = [_flow(url="http://connectivitycheck.gstatic.com/generate_204", host="connectivitycheck.gstatic.com")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert not any(f.title.startswith("Cleartext HTTP") for f in out)


def test_cleartext_http_dedups_repeated_pairs() -> None:
    """Same (host, path) hit 50 times → one finding, not 50."""
    flows = [_flow(url="http://api.example.com/v1/me", host="api.example.com") for _ in range(50)]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    cleartext = [f for f in out if f.title.startswith("Cleartext HTTP")]
    assert len(cleartext) == 1


# ─── jwt_leak_body ────────────────────────────────────────────────────


def test_jwt_leak_in_response_body_triggers_high() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqYWNrc29uIn0.abc-signature-bytes-XX"
    flows = [_flow(raw_response=f"HTTP/1.1 200 OK\r\nContent-Length: 200\r\n\r\n{{\"token\":\"{jwt}\"}}")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    jwt_findings = [f for f in out if "JWT" in f.title]
    assert len(jwt_findings) == 1
    assert jwt_findings[0].severity == Severity.HIGH
    # The signature segment must be redacted from the evidence — we
    # never want live signatures in reports.
    assert "<sig>" in jwt_findings[0].evidence
    assert "abc-signature-bytes" not in jwt_findings[0].evidence


def test_jwt_pattern_doesnt_match_random_base64() -> None:
    flows = [_flow(raw_response="HTTP/1.1 200 OK\r\n\r\nbm90IGEgand0\n")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert not any("JWT" in f.title for f in out)


# ─── insecure_cookie ──────────────────────────────────────────────────


def test_insecure_cookie_flags_missing_secure_httponly() -> None:
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Set-Cookie: sessionid=abc; Path=/\r\n"
        "\r\n"
    )
    flows = [_flow(raw_response=response)]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    cookie = next((f for f in out if "Set-Cookie" in f.title), None)
    assert cookie is not None
    assert cookie.severity == Severity.MEDIUM
    assert "Secure" in cookie.title
    assert "HttpOnly" in cookie.title


def test_insecure_cookie_passes_when_flags_present() -> None:
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Set-Cookie: sessionid=abc; Secure; HttpOnly; Path=/\r\n"
        "\r\n"
    )
    flows = [_flow(raw_response=response)]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert not any("Set-Cookie" in f.title for f in out)


# ─── api_key_in_url ───────────────────────────────────────────────────


def test_api_key_in_query_string_flags_high() -> None:
    flows = [_flow(url="https://api.example.com/v1/me?api_key=AIzaSyABCDEFG12345abcdefg12345abcdefg12")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    api = next((f for f in out if "Credential-shaped" in f.title), None)
    assert api is not None
    assert api.severity == Severity.HIGH
    # Evidence must redact the actual key — no live secrets in reports.
    assert "<redacted>" in api.evidence
    assert "AIzaSyABCDEFG" not in api.evidence


def test_access_token_named_param_also_flags() -> None:
    flows = [_flow(url="https://api.example.com/v1/login?access_token=eyJhb-deadbeef")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert any("Credential-shaped" in f.title for f in out)


def test_url_without_credentials_doesnt_flag() -> None:
    flows = [_flow(url="https://api.example.com/v1/me?page=2&sort=name")]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert not any("Credential-shaped" in f.title for f in out)


# ─── discovered_host ──────────────────────────────────────────────────


def test_discovered_host_flags_hosts_outside_static_surface() -> None:
    flows = [
        _flow(host="leak.example.org", url="https://leak.example.org/track"),
        _flow(host="api.example.com",   url="https://api.example.com/v1/me"),
    ]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    disc = next((f for f in out if f.title.startswith("Live host not in static surface")), None)
    assert disc is not None
    assert "leak.example.org" in disc.title
    assert disc.severity == Severity.INFO


# ─── 5xx_run ──────────────────────────────────────────────────────────


def test_5xx_run_needs_three_to_fire() -> None:
    flows = [_flow(status=500), _flow(status=500)]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    assert not any("5xx" in f.title for f in out)


def test_5xx_run_fires_at_three() -> None:
    flows = [_flow(status=500), _flow(status=502), _flow(status=503)]
    out = findings_for_flows(flows, surface_hosts={"api.example.com"})
    run = next((f for f in out if "5xx" in f.title), None)
    assert run is not None
    assert run.severity == Severity.LOW
    assert "3" in run.title  # count surfaced


# ─── endpoint integration ─────────────────────────────────────────────


@pytest.fixture
def traffic_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Stub Moxy with two flows that fire two rules + the upload pipeline
    so /moxy-traffic returns derived findings inline."""
    import importlib
    import io
    import httpx
    from fastapi.testclient import TestClient

    class _FakeResponse:
        def __init__(self, status: int, payload: Any) -> None:
            self.status_code = status
            self._payload = payload
        def json(self) -> Any:
            return self._payload

    class _FakeClient:
        def __init__(self, routes: dict[str, _FakeResponse]) -> None:
            self._routes = routes
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return None
        async def get(self, url: str, params=None, **kwargs):  # noqa: ARG002
            key = url.split("?")[0]
            if key not in self._routes:
                raise httpx.HTTPError(f"no mock for {url}")
            return self._routes[key]

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_MOXY_URL", "http://localhost:5000")
    monkeypatch.setenv("MNEXUS_MOXY_PROXY_HOST", "192.168.0.8")
    monkeypatch.setenv("MNEXUS_MOXY_PROXY_PORT", "8081")

    from mnexus.api import main as api_main
    importlib.reload(api_main)

    fake = _FakeClient({
        "http://localhost:5000/api/projects": _FakeResponse(200, [
            {"id": 7, "name": "com.target.app", "updated_at": "2026-05-13"},
        ]),
        "http://localhost:5000/api/projects/7/requests": _FakeResponse(200, {
            "requests": [
                # Cleartext to a host the project surface will claim.
                {"id": 1, "flow_id": "a", "method": "GET", "status_code": 200,
                 "url": "http://api.target.com/v1/me", "duration_ms": 1,
                 "timestamp": "2026-05-13T12:00:00Z",
                 "raw_response": "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"},
                # JWT-in-body on a different host.
                {"id": 2, "flow_id": "b", "method": "GET", "status_code": 200,
                 "url": "https://other.target.com/x", "duration_ms": 1,
                 "timestamp": "2026-05-13T12:00:01Z",
                 "raw_response": "HTTP/1.1 200 OK\r\n\r\n{\"t\":\"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.signature-bytes-redacted-XX\"}"},
            ],
        }),
    })
    monkeypatch.setattr("mnexus.engines.moxy_engine.httpx.AsyncClient", lambda *a, **kw: fake)

    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub"), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid


def test_moxy_traffic_endpoint_returns_derived_findings(traffic_client) -> None:
    client, pid = traffic_client
    body = client.get(f"/v1/projects/{pid}/moxy-traffic").json()
    findings = body.get("findings") or []
    # The fixture project has no static surface (stub APK), so we don't
    # expect cleartext_http (it requires the host to be in the surface).
    # We DO expect JWT-leak + discovered_host because both fire on any
    # host. Pin those two.
    titles = " ".join(f["title"] for f in findings)
    assert "JWT" in titles
    assert "Live host" in titles
