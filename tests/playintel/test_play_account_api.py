"""HTTP layer tests for the Play account manager.

Each test runs against an isolated SQLite (env override
``MNEXUS_DB_PATH``) so the user's real ``~/.mnexus/nexus.sqlite3`` is
never touched. The TestClient drives FastAPI's lifespan so the
``MedusaNexus`` orchestrator picks up the fresh DB cleanly.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    # Force a clean import so the lifespan reads our env vars.
    import importlib

    import mnexus.api.main as api_main

    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def test_list_starts_empty(client: TestClient) -> None:
    r = client.get("/v1/playintel/accounts")
    assert r.status_code == 200
    body = r.json()
    assert body["accounts"] == []
    assert body["default"] is None


def test_create_with_aas_token_persists_redacted(client: TestClient) -> None:
    r = client.post(
        "/v1/playintel/accounts",
        json={
            "name": "alpha",
            "email": "alice@example.com",
            "aas_token": "aas_et/SECRET",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Token must NEVER appear in the response.
    assert "aas_et/SECRET" not in r.text
    assert body["account"]["name"] == "alpha"
    assert body["account"]["email_local"] == "alice"
    assert body["account"]["email_domain"] == "example.com"
    # First account auto-promotes to default.
    assert body["account"]["is_default"] is True


def test_create_requires_exactly_one_secret(client: TestClient) -> None:
    """Both aas_token and password is rejected; neither is rejected."""
    r = client.post(
        "/v1/playintel/accounts",
        json={"name": "x", "email": "x@y.com"},
    )
    assert r.status_code == 400
    assert "one of" in r.json()["detail"]

    r = client.post(
        "/v1/playintel/accounts",
        json={
            "name": "x",
            "email": "x@y.com",
            "aas_token": "aas_et/T",
            "password": "p",
        },
    )
    assert r.status_code == 400


def test_create_rejects_invalid_name(client: TestClient) -> None:
    r = client.post(
        "/v1/playintel/accounts",
        json={"name": "bad name!", "email": "x@y.com", "aas_token": "aas_et/T"},
    )
    assert r.status_code == 400


def test_create_second_account_does_not_clobber_default(client: TestClient) -> None:
    """Adding a second account without is_default keeps the original default."""
    client.post(
        "/v1/playintel/accounts",
        json={"name": "alpha", "email": "a@b.com", "aas_token": "aas_et/A"},
    )
    client.post(
        "/v1/playintel/accounts",
        json={"name": "beta", "email": "b@b.com", "aas_token": "aas_et/B"},
    )
    body = client.get("/v1/playintel/accounts").json()
    assert body["default"] == "alpha"
    assert {a["name"] for a in body["accounts"]} == {"alpha", "beta"}


def test_set_default_endpoint(client: TestClient) -> None:
    client.post(
        "/v1/playintel/accounts",
        json={"name": "alpha", "email": "a@b.com", "aas_token": "aas_et/A"},
    )
    client.post(
        "/v1/playintel/accounts",
        json={"name": "beta", "email": "b@b.com", "aas_token": "aas_et/B"},
    )
    r = client.post("/v1/playintel/accounts/beta/default")
    assert r.status_code == 200
    assert r.json()["default"] == "beta"
    assert client.get("/v1/playintel/accounts").json()["default"] == "beta"


def test_set_default_for_missing_returns_404(client: TestClient) -> None:
    r = client.post("/v1/playintel/accounts/ghost/default")
    assert r.status_code == 404


def test_delete_endpoint(client: TestClient) -> None:
    client.post(
        "/v1/playintel/accounts",
        json={"name": "alpha", "email": "a@b.com", "aas_token": "aas_et/A"},
    )
    r = client.delete("/v1/playintel/accounts/alpha")
    assert r.status_code == 200
    assert r.json()["deleted"] == "alpha"
    assert client.get("/v1/playintel/accounts").json()["accounts"] == []


def test_delete_missing_returns_404(client: TestClient) -> None:
    r = client.delete("/v1/playintel/accounts/ghost")
    assert r.status_code == 404


def test_scan_with_no_accounts_returns_503(client: TestClient) -> None:
    """No accounts stored → 503 with the documented setup hint."""
    r = client.post(
        "/v1/playintel/scan",
        json={"package": "com.test"},
    )
    assert r.status_code == 503
    assert "/v1/playintel/accounts" in r.json()["detail"]
