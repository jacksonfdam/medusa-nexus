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


def test_root_serves_spa_shell(client: TestClient) -> None:
    """GET / now returns the SPA shell: topbar + sidebar + #view + loads app.js/css."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text

    # Brand + version
    assert "MEDUSA::NEXUS" in body
    assert "v0.1.0-alpha" in body
    assert 'id="clock"' in body

    # Sidebar: 9 primary routes + 3 secondary at the bottom.
    for nav_item in ("DASHBOARD", "PROJECTS", "SCAN", "DYNAMIC", "NETWORK",
                     "REPORT", "TOOLS", "RECIPES", "SETTINGS",
                     "BOOT", "CREDITS", "TERMINAL"):
        assert f">{nav_item}<" in body, f"sidebar missing {nav_item}"

    # Static asset references wired
    assert '/static/app.css' in body
    assert '/static/app.js' in body

    # The main pane is empty until the router renders on the client.
    assert 'id="view"' in body
    assert "SYSTEM READY" in body


def test_spa_static_assets_served(client: TestClient) -> None:
    """app.css and app.js are reachable — otherwise the SPA is a brick."""
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "--cyan: #00FFFF" in css.text  # design token present

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith(("application/javascript", "text/javascript"))
    assert "renderRoute" in js.text  # router entrypoint present


def test_every_sidebar_route_has_a_handler(client: TestClient) -> None:
    """Pin that every primary sidebar label corresponds to an entry in the JS route table."""
    js = client.get("/static/app.js").text
    for route in ("dashboard", "projects", "scan", "dynamic", "network",
                  "report", "tools", "recipes", "settings",
                  "about", "boot", "terminal"):
        # Each route shows up as a path entry in the ROUTES list.
        assert f'path: "{route}"' in js, f"route '{route}' not in ROUTES table"


def test_mitigation_is_pinned_in_spa(client: TestClient) -> None:
    """The Mitigation block is a first-class UI element; don't let anyone quietly drop it."""
    js = client.get("/static/app.js").text
    assert "MITIGATION PLAYBOOK" in js
    assert "mitigation" in js  # CSS class
    assert "Android Keystore" in js  # sample mitigation content from Finding Detail


def test_favicon_is_svg(client: TestClient) -> None:
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")


def test_health_probe(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
