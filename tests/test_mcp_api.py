"""MCP control-plane API — config get/put, heartbeat, setup snippets."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    # `with` drives the lifespan so app.state.nexus is populated.
    with TestClient(api_main.app) as c:
        yield c


def test_config_defaults_open(client: TestClient) -> None:
    r = client.get("/v1/mcp/config")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["allowed_tools"] is None
    # Catalogue lists every shipped tool, each enabled by default.
    assert len(body["tools"]) >= 15
    assert all(t["enabled"] for t in body["tools"])
    groups = {t["group"] for t in body["tools"]}
    assert {"read", "nav", "write"} <= groups


def test_put_gates_to_allowlist(client: TestClient) -> None:
    r = client.put("/v1/mcp/config", json={"allowed_tools": ["list_findings", "get_finding"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed_tools"] == ["list_findings", "get_finding"]
    cat = {t["name"]: t["enabled"] for t in body["tools"]}
    assert cat["list_findings"] is True
    assert cat["scan_apk"] is False
    # Persisted — a fresh GET reflects it.
    assert client.get("/v1/mcp/config").json()["allowed_tools"] == ["list_findings", "get_finding"]


def test_put_drops_unknown_tool_names(client: TestClient) -> None:
    r = client.put("/v1/mcp/config", json={"allowed_tools": ["doctor", "ghost_tool"]})
    assert r.json()["allowed_tools"] == ["doctor"]


def test_put_null_restores_open_default(client: TestClient) -> None:
    client.put("/v1/mcp/config", json={"allowed_tools": ["doctor"]})
    r = client.put("/v1/mcp/config", json={"allowed_tools": None})
    assert r.json()["allowed_tools"] is None


def test_master_switch_off(client: TestClient) -> None:
    r = client.put("/v1/mcp/config", json={"enabled": False})
    body = r.json()
    assert body["enabled"] is False
    assert all(not t["enabled"] for t in body["tools"])


def test_put_rejects_non_list_allowlist(client: TestClient) -> None:
    r = client.put("/v1/mcp/config", json={"allowed_tools": "doctor"})
    assert r.status_code == 400


def test_heartbeat_updates_status(client: TestClient) -> None:
    assert client.get("/v1/mcp/config").json()["status"]["connected"] is False
    hb = client.post("/v1/mcp/heartbeat", json={"client": "claude-desktop"})
    assert hb.json()["ok"] is True
    status = client.get("/v1/mcp/config").json()["status"]
    assert status["connected"] is True
    assert status["client"] == "claude-desktop"
    assert status["last_seen_ago_s"] is not None


def test_setup_snippet_points_back_at_this_host(client: TestClient) -> None:
    r = client.get("/v1/mcp/setup/cursor")
    body = r.json()
    assert body["agent"] == "cursor"
    assert "mcp-serve" in body["snippet"]
    assert "MNEXUS_API_BASE" in body["snippet"]
    assert ".cursor/mcp.json" in body["config_file"]
