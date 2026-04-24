"""FastAPI smoke tests. Locks in that `GET /` serves the landing page so
visitors stop seeing FastAPI's stock 404 JSON at the root."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def client() -> TestClient:
    # Import here so the module-level lifespan doesn't try to touch a real
    # SQLite file during collection. `TestClient` drives the lifespan itself.
    from mnexus.api.main import app

    return TestClient(app)


def test_root_serves_dashboard_html(client: TestClient) -> None:
    """GET / mirrors the `01 // DASHBOARD` Pencil screen — pin the structural bits."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text

    # Brand + version
    assert "MEDUSA::NEXUS" in body
    assert "v0.1.0-alpha" in body

    # Header row signal (clock id + CONNECTED badge)
    assert 'id="clock"' in body
    assert "CONNECTED" in body

    # Sidebar nav — one entry per group in the Pencil design.
    for nav_item in ("DASHBOARD", "PROJECTS", "SCAN", "DYNAMIC", "NETWORK",
                     "REPORT", "TOOLS", "RECIPES", "SETTINGS"):
        assert f">{nav_item}<" in body, f"sidebar missing {nav_item}"

    # 4-up metric card labels
    for kicker in ("// AVG RISK", "// OPEN CRITICALS", "// DEVICES", "// ENGINES"):
        assert kicker in body, f"missing metric card {kicker}"

    # ASCII section header + gradient underline
    assert "02 // RECENT" in body
    assert "gradient-underline" in body

    # Engine status panel + footer
    assert "// ENGINE STATUS" in body
    assert "SYSTEM READY" in body


def test_favicon_is_svg(client: TestClient) -> None:
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")


def test_health_probe(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
