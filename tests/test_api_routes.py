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


def test_root_serves_landing_page_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "MEDUSA::NEXUS" in body
    assert "/v1/doctor" in body  # link to doctor endpoint is present
    assert "SYSTEM READY" in body


def test_favicon_is_svg(client: TestClient) -> None:
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")


def test_health_probe(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
