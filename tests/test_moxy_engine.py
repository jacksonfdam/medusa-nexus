"""MoxyEngine — flow parsing + project-pick heuristic + Network tab endpoint.

The engine talks to Moxy's REST API (`/api/projects`, `/api/projects/{id}/requests`).
We don't spin up an actual Moxy container in CI; instead we monkeypatch
``httpx.AsyncClient`` with a tiny fake that returns canned JSON. That's enough
to pin every code path the Network tab depends on:

  * raw → normalised flow shape (method / host / path / status / size / ms)
  * Content-Length vs body-length size derivation
  * status code → severity bucket
  * pick_project name-matching heuristic + freshest fallback
  * /v1/projects/{id}/moxy-traffic round-trip (project picker + host filter)
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mnexus.config import NexusConfig
from mnexus.engines.moxy_engine import (
    MoxyEngine,
    _normalise_flow,
    _severity_for,
    _size_from_raw_response,
)


# ─── pure-function pins ────────────────────────────────────────────────


def test_normalise_flow_splits_host_and_path() -> None:
    flow = {
        "id": 1,
        "flow_id": "abc-123",
        "method": "post",
        "url": "https://api.example.com/v1/login?next=/dash",
        "status_code": 201,
        "duration_ms": 42,
        "timestamp": "2026-05-11T17:00:00",
        "raw_response": "HTTP/1.1 201 Created\r\nContent-Length: 7\r\n\r\npayload",
    }
    row = _normalise_flow(flow)
    assert row["method"] == "POST"
    assert row["host"] == "api.example.com"
    # Query string is preserved so the table line matches what the engineer sees.
    assert row["path"] == "/v1/login?next=/dash"
    assert row["status"] == 201
    assert row["size"] == 7
    assert row["ms"] == 42
    assert row["origin"] == "moxy"
    assert row["flow_id"] == "abc-123"


def test_normalise_flow_tolerates_missing_url_and_body() -> None:
    row = _normalise_flow({"id": 2, "method": "GET"})
    assert row["host"] == ""
    assert row["path"] == "/"
    assert row["size"] == 0
    assert row["status"] is None
    assert row["origin"] == "moxy"


def test_size_falls_back_to_body_length_when_no_content_length() -> None:
    raw = "HTTP/1.1 200 OK\r\nServer: x\r\n\r\nhello world"
    assert _size_from_raw_response(raw) == len("hello world")


def test_size_zero_for_empty_or_malformed_response() -> None:
    assert _size_from_raw_response("") == 0
    assert _size_from_raw_response("not http") == 0


def test_severity_buckets() -> None:
    assert _severity_for(204) == "info"
    assert _severity_for(301) == "medium"
    assert _severity_for(404) == "high"
    assert _severity_for(503) == "crit"
    assert _severity_for(None) == "info"
    assert _severity_for("not-a-number") == "info"


# ─── httpx mocking helper ─────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeAsyncClient:
    """Minimal stand-in for httpx.AsyncClient — returns canned routes."""

    def __init__(self, routes: dict[str, _FakeResponse]) -> None:
        self._routes = routes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, Any] | None = None, **_: Any) -> _FakeResponse:
        # Normalise: strip query string for lookup, record params separately.
        key = url.split("?")[0]
        self.calls.append((key, params or {}))
        if key not in self._routes:
            raise httpx.HTTPError(f"no mock for {url}")
        return self._routes[key]


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    """Return a function the test calls with its route table."""
    holder: dict[str, _FakeAsyncClient] = {}

    def install(routes: dict[str, _FakeResponse]) -> _FakeAsyncClient:
        client = _FakeAsyncClient(routes)
        monkeypatch.setattr("mnexus.engines.moxy_engine.httpx.AsyncClient", lambda *a, **kw: client)
        holder["c"] = client
        return client

    return install


# ─── engine-level pins ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_online_reports_workspace_count(fake_httpx) -> None:
    fake_httpx({
        "http://localhost:5000/api/projects": _FakeResponse(200, [
            {"id": 1, "name": "Default Project", "updated_at": "2026-05-01"},
            {"id": 2, "name": "se.swedbank.mobil", "updated_at": "2026-05-11"},
        ]),
    })
    cfg = NexusConfig(moxy_url="http://localhost:5000", moxy_proxy_host="192.168.0.8", moxy_proxy_port=8081)
    eng = MoxyEngine(cfg)
    status = await eng.health_check()
    assert status.installed is True
    assert "2 project(s)" in status.message
    # Proxy hint should reflect the configured LAN host/port.
    assert "192.168.0.8:8081" in status.message


@pytest.mark.asyncio
async def test_health_check_unreachable_returns_actionable_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dead:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            raise httpx.ConnectError("nope")

    monkeypatch.setattr("mnexus.engines.moxy_engine.httpx.AsyncClient", lambda *a, **kw: _Dead())
    cfg = NexusConfig(moxy_url="http://localhost:5000")
    status = await MoxyEngine(cfg).health_check()
    assert status.installed is False
    assert "scripts/setup.sh --moxy" in status.message


@pytest.mark.asyncio
async def test_pick_project_prefers_package_name_match(fake_httpx) -> None:
    fake_httpx({
        "http://localhost:5000/api/projects": _FakeResponse(200, [
            {"id": 1, "name": "Default Project", "updated_at": "2026-05-01"},
            {"id": 2, "name": "se.swedbank.mobil", "updated_at": "2026-05-05"},
            {"id": 3, "name": "com.example.other", "updated_at": "2026-05-11"},
        ]),
    })
    eng = MoxyEngine(NexusConfig(moxy_url="http://localhost:5000"))
    picked = await eng.pick_project("se.swedbank.mobil")
    assert picked is not None
    assert picked["id"] == 2


@pytest.mark.asyncio
async def test_pick_project_falls_back_to_freshest_workspace(fake_httpx) -> None:
    fake_httpx({
        "http://localhost:5000/api/projects": _FakeResponse(200, [
            {"id": 1, "name": "Default Project", "updated_at": "2026-05-01"},
            {"id": 2, "name": "unrelated",        "updated_at": "2026-05-11"},
        ]),
    })
    eng = MoxyEngine(NexusConfig(moxy_url="http://localhost:5000"))
    picked = await eng.pick_project("com.totally.different")
    # No name match → freshest by updated_at wins.
    assert picked is not None
    assert picked["id"] == 2


@pytest.mark.asyncio
async def test_pick_project_returns_none_when_moxy_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dead:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            raise httpx.ConnectError("nope")

    monkeypatch.setattr("mnexus.engines.moxy_engine.httpx.AsyncClient", lambda *a, **kw: _Dead())
    eng = MoxyEngine(NexusConfig(moxy_url="http://localhost:5000"))
    assert await eng.pick_project("anything") is None


@pytest.mark.asyncio
async def test_fetch_flows_normalises_and_marks_off_project_hosts(fake_httpx) -> None:
    fake_httpx({
        "http://localhost:5000/api/projects/7/requests": _FakeResponse(200, {
            "pagination": {"total": 2},
            "requests": [
                {
                    "id": 1, "flow_id": "f1", "method": "GET", "status_code": 200,
                    "url": "https://api.example.com/v1/me",
                    "duration_ms": 12, "timestamp": "2026-05-11T17:00:00",
                    "raw_response": "HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nok!",
                },
                {
                    "id": 2, "flow_id": "f2", "method": "POST", "status_code": 500,
                    "url": "https://leak.example.org/track",
                    "duration_ms": 99, "timestamp": "2026-05-11T17:00:01",
                    "raw_response": "HTTP/1.1 500 ...\r\n\r\n",
                },
            ],
        }),
    })
    eng = MoxyEngine(NexusConfig(moxy_url="http://localhost:5000"))
    flows = await eng.fetch_flows(7, hosts={"api.example.com"})
    assert len(flows) == 2
    by_id = {f["flow_id"]: f for f in flows}
    assert by_id["f1"]["matches_project"] is True
    assert by_id["f2"]["matches_project"] is False
    # Severity flows through from status code.
    assert by_id["f2"]["severity"] == "crit"


# ─── /v1/projects/{id}/moxy-traffic round-trip ────────────────────────


@pytest.fixture
def network_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a clean workspace. Avoids the SQLite cross-thread trap
    by going through the upload endpoint to create a project (handler runs in
    the same thread that owns the connection)."""
    import importlib
    import io
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_MOXY_URL", "http://localhost:5000")
    monkeypatch.setenv("MNEXUS_MOXY_PROXY_HOST", "192.168.0.8")
    monkeypatch.setenv("MNEXUS_MOXY_PROXY_PORT", "8081")

    from mnexus.api import main as api_main
    importlib.reload(api_main)

    with TestClient(api_main.app) as c:
        # Upload a stub APK so we have a real project to attach Moxy traffic to.
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("se.swedbank.mobil.apk", io.BytesIO(b"PK\x03\x04stub"))},
            data={"package": "se.swedbank.mobil", "version": "1.0.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid


def test_moxy_traffic_endpoint_resolves_workspace_by_package_name(
    network_client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, pid = network_client

    fake = _FakeAsyncClient({
        "http://localhost:5000/api/projects": _FakeResponse(200, [
            {"id": 1, "name": "Default Project", "updated_at": "2026-05-01"},
            {"id": 5, "name": "se.swedbank.mobil", "updated_at": "2026-05-11"},
        ]),
        "http://localhost:5000/api/projects/5/requests": _FakeResponse(200, {
            "pagination": {"total": 2},
            "requests": [
                {
                    "id": 1, "flow_id": "f1", "method": "GET", "status_code": 200,
                    "url": "https://api.swedbank.com/v1/me",
                    "duration_ms": 12, "timestamp": "2026-05-11T17:00:00",
                    "raw_response": "HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nok!",
                },
                {
                    "id": 2, "flow_id": "f2", "method": "POST", "status_code": 500,
                    "url": "https://leak.example.org/track",
                    "duration_ms": 99, "timestamp": "2026-05-11T17:00:01",
                    "raw_response": "HTTP/1.1 500 ...\r\n\r\n",
                },
            ],
        }),
    })
    monkeypatch.setattr("mnexus.engines.moxy_engine.httpx.AsyncClient", lambda *a, **kw: fake)

    r = client.get(f"/v1/projects/{pid}/moxy-traffic")
    assert r.status_code == 200, r.text
    body = r.json()
    # Workspace picked by name match against the project's package.
    assert body["moxy_project"]["id"] == 5
    assert body["moxy_project"]["name"] == "se.swedbank.mobil"
    assert body["count"] == 2
    # Available projects list round-trips so the UI dropdown can render.
    assert {p["id"] for p in body["available_projects"]} == {1, 5}


def test_moxy_traffic_endpoint_accepts_explicit_workspace_override(
    network_client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, pid = network_client

    fake = _FakeAsyncClient({
        "http://localhost:5000/api/projects": _FakeResponse(200, [
            {"id": 7, "name": "other", "updated_at": "2026-05-11"},
        ]),
        "http://localhost:5000/api/projects/7/requests": _FakeResponse(200, {
            "pagination": {"total": 1},
            "requests": [
                {"id": 1, "flow_id": "only", "method": "GET", "status_code": 200,
                 "url": "https://api.swedbank.com/v1/me", "duration_ms": 1,
                 "timestamp": "t1", "raw_response": "HTTP/1.1 200\r\n\r\n"},
            ],
        }),
    })
    monkeypatch.setattr("mnexus.engines.moxy_engine.httpx.AsyncClient", lambda *a, **kw: fake)

    # Explicit ?moxy_project=7 bypasses the pick heuristic entirely.
    r = client.get(f"/v1/projects/{pid}/moxy-traffic?moxy_project=7")
    assert r.status_code == 200
    body = r.json()
    assert body["moxy_project"]["id"] == 7
    assert {f["flow_id"] for f in body["captured"]} == {"only"}
