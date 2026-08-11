"""Attack-engine API — plan (offline), dry-run, and gated execute."""

from __future__ import annotations

import importlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _minimal_apk() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", b"")
        zf.writestr("assets/config.json", json.dumps({"k": "v"}))
        zf.writestr("classes.dex", b"dex\n035\x00")
        zf.writestr("resources.arsc", b"")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "nexus.sqlite3"
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(db_path))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post("/v1/apks/upload",
                   files={"file": ("t.apk", io.BytesIO(_minimal_apk()),
                                   "application/vnd.android.package-archive")},
                   data={"package": "com.target.app", "version": "1.0"})
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        _inject_exported_activity(db_path, pid)
        yield c, pid


def _inject_exported_activity(db_path: Path, pid: str) -> None:
    """Give the surface something exploitable so the planner has a job.

    Uses a fresh ArtifactStore connection in the *test* thread — the app's own
    connection lives in the TestClient's worker thread and SQLite refuses
    cross-thread reuse.
    """
    from mnexus.core.artifact_store import ArtifactStore
    from mnexus.models.attack_surface import ExportedComponent
    store = ArtifactStore(db_path)
    p = store.load_project(pid)
    p.attack_surface.exported_components.append(
        ExportedComponent(name=".ui.Deep", component_type="activity", unprotected=True)
    )
    store.save_project(p)


def test_get_attack_is_empty_before_plan(client) -> None:
    c, pid = client
    r = c.get(f"/v1/projects/{pid}/attack")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_plan_persists_attempts(client) -> None:
    c, pid = client
    r = c.post(f"/v1/projects/{pid}/attack/plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    act = [a for a in body["attempts"] if a["technique"] == "exported-activity"]
    assert act
    assert act[0]["verdict"] == "provable"
    assert "am start -n" in act[0]["poc"]
    # Persisted — a plain GET now returns it.
    assert c.get(f"/v1/projects/{pid}/attack").json()["count"] == body["count"]


def test_execute_dry_run_fires_nothing(client, monkeypatch) -> None:
    c, pid = client
    c.post(f"/v1/projects/{pid}/attack/plan")
    # Even if a device were connected, execute=false must not fire.
    r = c.post(f"/v1/projects/{pid}/attack/execute")
    body = r.json()
    assert body["dry_run"] is True
    assert len(body["would_run"]) >= 1
    # Nothing executed → still provable.
    assert all(a["verdict"] != "confirmed" for a in body["attempts"])


def test_execute_true_without_device_is_503(client, monkeypatch) -> None:
    c, pid = client

    async def _no_device() -> bool:
        return False
    monkeypatch.setattr(c.app.state.nexus.engines["adb"], "is_device_connected", _no_device)
    r = c.post(f"/v1/projects/{pid}/attack/execute", params={"execute": "true"})
    assert r.status_code == 503


def test_execute_true_confirms_against_fake_device(client, monkeypatch) -> None:
    c, pid = client
    adb = c.app.state.nexus.engines["adb"]

    async def _yes() -> bool:
        return True

    async def _run(argv):
        return "Starting: Intent { }\nStatus: ok\nActivity: com.target.app/.ui.Deep"

    monkeypatch.setattr(adb, "is_device_connected", _yes)
    monkeypatch.setattr(adb, "_run", _run)
    r = c.post(f"/v1/projects/{pid}/attack/execute", params={"execute": "true"})
    body = r.json()
    assert body["dry_run"] is False
    assert len(body["fired"]) >= 1
    act = [a for a in body["attempts"] if a["technique"] == "exported-activity"][0]
    assert act["verdict"] == "confirmed"
    assert act["executed"] is True
