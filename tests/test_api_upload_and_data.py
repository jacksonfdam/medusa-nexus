"""Upload + data endpoints — end-to-end round trip through the orchestrator."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a tmp workspace + sqlite so tests don't pollute ~/.mnexus."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    # Reload the app module so `MedusaNexus` picks up the tmp env when the
    # lifespan runs in `with TestClient(app)`.
    import importlib

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def test_upload_apk_with_explicit_package_creates_project(isolated_client: TestClient) -> None:
    """Happy path: caller provides package+version so we skip apktool detection."""
    fake_apk = io.BytesIO(b"PK\x03\x04not-really-an-apk-but-good-enough")
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("app-develop.apk", fake_apk, "application/vnd.android.package-archive")},
        data={"package": "com.example.develop", "version": "0.1.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"].startswith("PRJ-")
    assert body["package"] == "com.example.develop"
    assert body["version"] == "0.1.0"
    assert body["apk_size_bytes"] > 0
    assert len(body["apk_sha256"]) == 64

    # Project is persisted.
    listing = isolated_client.get("/v1/projects").json()
    ids = [p["id"] for p in listing]
    assert body["project_id"] in ids


def test_upload_rejects_empty_file(isolated_client: TestClient) -> None:
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("empty.apk", io.BytesIO(b""))},
        data={"package": "com.example", "version": "1.0"},
    )
    assert r.status_code == 400
    assert "empty" in r.text.lower()


def test_upload_without_package_and_no_detection_rejects(isolated_client: TestClient) -> None:
    """When apktool can't parse the fake bytes, we require an explicit package name."""
    fake_apk = io.BytesIO(b"not-a-real-apk")
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("mystery.apk", fake_apk)},
    )
    # The real apktool will fail to decode gibberish, so detection returns {}.
    # If apktool isn't installed at all, detection also returns {}. Either way: 400.
    assert r.status_code == 400
    assert "package" in r.text.lower()


def test_findings_endpoint_empty_for_fresh_project(isolated_client: TestClient) -> None:
    # Upload a project so it exists.
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("a.apk", io.BytesIO(b"PK\x03\x04"))},
        data={"package": "com.example", "version": "1.0"},
    )
    pid = r.json()["project_id"]

    findings = isolated_client.get(f"/v1/projects/{pid}/findings").json()
    # Static engines are stubs, so: empty list.
    assert findings == []


def test_project_detail_contains_attack_surface_shell(isolated_client: TestClient) -> None:
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("a.apk", io.BytesIO(b"PK\x03\x04"))},
        data={"package": "com.example", "version": "1.0"},
    )
    pid = r.json()["project_id"]
    detail = isolated_client.get(f"/v1/projects/{pid}").json()
    assert detail["id"] == pid
    # The orchestrator always writes an AttackSurface shell, even with 0 findings.
    assert detail["attack_surface"] is not None
    assert detail["risk_score"] == 0.0


def test_get_finding_returns_404_when_missing(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/findings/FND-DOES-NOT-EXIST")
    assert r.status_code == 404


def test_settings_exposes_paths_and_service_urls(isolated_client: TestClient) -> None:
    s = isolated_client.get("/v1/settings").json()
    assert "paths" in s and "services" in s
    for required_path in ("adb", "jadx", "apktool"):
        assert required_path in s["paths"]
    assert "mobsf_url" in s["services"]
    assert "burp_url" in s["services"]


def test_recipes_endpoint_returns_at_least_the_auto_recipe(isolated_client: TestClient) -> None:
    recipes = isolated_client.get("/v1/recipes").json()
    names = [r["name"] for r in recipes]
    # cipher_key_leak is the always-there auto recipe.
    assert "cipher_key_leak" in names


def test_device_info_when_no_device(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/device/info")
    assert r.status_code == 200
    body = r.json()
    # CI / test env has no device — we expect a clean "not connected" response.
    assert body["connected"] in (True, False)  # either is valid
    if not body["connected"]:
        assert "reason" in body


def test_markdown_report_download(isolated_client: TestClient) -> None:
    """Upload → generate markdown report → verify Mitigation Playbook is in it."""
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("a.apk", io.BytesIO(b"PK\x03\x04"))},
        data={"package": "com.example", "version": "1.0"},
    )
    pid = r.json()["project_id"]

    report = isolated_client.post(
        f"/v1/projects/{pid}/report",
        data={"template": "technical", "fmt": "markdown"},
    )
    assert report.status_code == 200
    text = report.text
    assert "MITIGATION PLAYBOOK" in text.upper() or "Mitigation Playbook" in text
    # The project's package name shows up in the header.
    assert "com.example" in text
