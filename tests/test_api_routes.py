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
    """GET / now returns the SPA shell: topbar + sidebar + #view + loads the
    ES-module entrypoint + css."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text

    # Brand + version
    assert "MEDUSA::NEXUS" in body
    assert "v0.1.0-alpha" in body
    assert 'id="clock"' in body

    # Sidebar primary routes (DYNAMIC and NETWORK now reachable only via the
    # project workspace tabs) + 3 secondary entries at the bottom.
    for nav_item in ("DASHBOARD", "PROJECTS", "SCAN", "DEVICES", "ADB",
                     "REPORT", "TOOLS", "RECIPES", "SETTINGS", "MCP",
                     "BOOT", "CREDITS", "TERMINAL"):
        assert f">{nav_item}<" in body, f"sidebar missing {nav_item}"
    # Belt-and-suspenders: pin that we did NOT regrow the removed entries.
    assert ">DYNAMIC<" not in body, "DYNAMIC should be reached via project tabs, not the sidebar"
    assert ">NETWORK<" not in body, "NETWORK should be reached via project tabs, not the sidebar"

    # Static asset references wired. The SPA is now an ES-module graph rooted
    # at 13-bootstrap.js (which imports the router + every view); the old
    # monolithic app.js is gone.
    assert '/static/app.css' in body
    assert '/static/js/13-bootstrap.js' in body
    assert '/static/app.js' not in body

    # The main pane is empty until the router renders on the client.
    assert 'id="view"' in body
    assert "SYSTEM READY" in body


def test_spa_static_assets_served(client: TestClient) -> None:
    """app.css and the JS module graph are reachable — otherwise the SPA is a brick."""
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "--cyan: #00FFFF" in css.text  # design token present

    # The module entrypoint the shell loads, plus the router it pulls in.
    boot = client.get("/static/js/13-bootstrap.js")
    assert boot.status_code == 200
    assert boot.headers["content-type"].startswith(("application/javascript", "text/javascript"))
    assert "renderRoute" in boot.text          # wires the router on hashchange
    assert "./11-router.js" in boot.text        # module graph resolves from here

    router = client.get("/static/js/11-router.js")
    assert router.status_code == 200
    assert "function renderRoute" in router.text


def test_every_sidebar_route_has_a_handler(client: TestClient) -> None:
    """Pin that every primary sidebar label corresponds to an entry in the JS
    route table — which now lives in 11-router.js."""
    js = client.get("/static/js/11-router.js").text
    for route in ("dashboard", "projects", "scan", "dynamic", "network",
                  "report", "tools", "recipes", "settings", "mcp",
                  "about", "boot", "terminal"):
        # Each route shows up as a path entry in the ROUTES list.
        assert f'path: "{route}"' in js, f"route '{route}' not in ROUTES table"


def test_mitigation_is_pinned_in_spa(client: TestClient) -> None:
    """The Mitigation block is a first-class UI element; don't let anyone quietly drop it.

    Demo content was removed when the SPA went fully data-driven, so we pin
    the structural anchors instead — the slot ids the mount hooks fill, the
    CSS class, and the playbook header. All live in the finding-detail module
    (09-mounts-rest.js) after the app.js split.
    """
    js = client.get("/static/js/09-mounts-rest.js").text
    assert "MITIGATION PLAYBOOK" in js
    assert "mitigation" in js                  # CSS class on the highlighted block
    assert "finding-mitigation" in js          # finding-detail slot id
    assert "mit.innerHTML" in js or "mitEl.innerHTML" in js  # the mount hook fills it


def test_favicon_is_svg(client: TestClient) -> None:
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")


def test_health_probe(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
