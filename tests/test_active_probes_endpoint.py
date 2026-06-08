"""Active Firebase probe orchestration — endpoints that fire RTDB /
Firestore / Storage probes against either an explicit config (no
project context) or the project's stored configs from a prior scan.

Tests mock the three probe functions so no live network is hit.
"""

from __future__ import annotations

import importlib
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def _fake_rtdb(db_url, *args, **kwargs):
    """Return a fake RealtimeDBResult-shaped object."""
    return SimpleNamespace(
        db_url=db_url, public_read=True, public_write=False,
        vulnerable=True, error=None,
    )


def _fake_firestore(project_id, api_key=None, *args, **kwargs):
    return SimpleNamespace(
        project_id=project_id, public_read=False,
        sample_document_count=0, vulnerable=False, error=None,
    )


def _fake_storage(bucket, *args, **kwargs):
    return SimpleNamespace(
        bucket=bucket, public_listing=False,
        object_count=0, vulnerable=False, error=None,
    )


@pytest.fixture
def probe_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with the three probe functions stubbed to canned returns."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    monkeypatch.setattr("mnexus.playintel.firebase_probes.check_realtime_db", _fake_rtdb)
    monkeypatch.setattr("mnexus.playintel.firebase_probes.check_firestore", _fake_firestore)
    monkeypatch.setattr("mnexus.playintel.firebase_probes.check_storage_bucket", _fake_storage)

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c, api_main


# ─── /v1/firebase/probe — standalone, no project context ──────────────


def test_standalone_probe_runs_all_three_when_full_config(probe_client) -> None:
    client, _ = probe_client
    body = {
        "project_id": "myapp-prod",
        "api_key": "AIzaSy_fake",
        "storage_bucket": "myapp-prod.appspot.com",
        "database_url": "https://myapp-prod-default-rtdb.firebaseio.com",
    }
    r = client.post("/v1/firebase/probe", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["project_id"] == "myapp-prod"
    assert j["rtdb"]["public_read"] is True
    assert j["firestore"]["project_id"] == "myapp-prod"
    assert j["storage"]["bucket"] == "myapp-prod.appspot.com"
    # Headline 'vulnerable' bool wraps the per-service flags.
    assert j["vulnerable"] is True   # RTDB stub returned vulnerable=True


def test_standalone_probe_skips_missing_inputs(probe_client) -> None:
    """Only RTDB info present → only RTDB block populated; others null."""
    client, _ = probe_client
    r = client.post("/v1/firebase/probe", json={"database_url": "https://x.firebaseio.com"})
    assert r.status_code == 200
    j = r.json()
    assert j["rtdb"] is not None
    assert j["firestore"] is None
    assert j["storage"] is None


def test_standalone_probe_400_when_nothing_provided(probe_client) -> None:
    client, _ = probe_client
    r = client.post("/v1/firebase/probe", json={})
    assert r.status_code == 400
    assert "required" in r.text.lower()


def test_standalone_probe_400_on_non_json(probe_client) -> None:
    client, _ = probe_client
    r = client.post("/v1/firebase/probe", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


# ─── /v1/projects/{id}/firebase/probe — uses prior play-scan configs ─────


def test_project_probe_404_when_no_prior_play_scan(probe_client) -> None:
    """A fresh project that's never been play-scanned → 404 with a hint."""
    client, _ = probe_client
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub"), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0"},
    )
    pid = r.json()["project_id"]
    rr = client.post(f"/v1/projects/{pid}/firebase/probe")
    assert rr.status_code == 404
    assert "play-scan" in rr.text.lower()


def test_project_probe_uses_stored_firebase_configs(probe_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run /v1/projects/{id}/play-scan with a stub analyser that injects
    a Firebase config into the report, then trigger /firebase/probe —
    it should walk the stored firebase_configs and call the probe stubs.
    """
    from mnexus.engines import play_intel_engine
    from mnexus.playintel.analyzer import AnalysisOutcome
    from mnexus.playintel.apk_source import DownloadInfo
    from mnexus.playintel.firebase_config import FirebaseConfig
    from mnexus.playintel.scan_report import ScanReport

    client, _ = probe_client

    async def stub_analyze_with_config(self, package, *, source, workspace, run_active_probes=False):  # noqa: ANN001
        report = ScanReport()
        report.add_firebase_config(FirebaseConfig(
            project_id="myapp-prod",
            api_key="AIza_x",
            storage_bucket="myapp-prod.appspot.com",
            database_url="https://myapp-prod-default-rtdb.firebaseio.com",
            location="test_fixture",
        ))
        return AnalysisOutcome(
            package_name=package,
            download_info=DownloadInfo(package_name=package, base_url="", base_size=0, splits=[], additional_files=[]),
            report=report,
            saved_files_dir=None,
        ), []

    monkeypatch.setattr(play_intel_engine.PlayIntelEngine, "analyze_package", stub_analyze_with_config)

    apk_bytes = b"PK\x03\x04stub-probe-fixture"
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0"},
    )
    pid = r.json()["project_id"]
    ps = client.post(f"/v1/projects/{pid}/play-scan")
    assert ps.status_code == 200, ps.text
    scan_id = ps.json()["scan_id"]

    rr = client.post(f"/v1/projects/{pid}/firebase/probe")
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert body["scan_id"] == scan_id
    configs = body["configs"]
    assert len(configs) == 1
    assert configs[0]["project_id"] == "myapp-prod"
    assert configs[0]["rtdb"]["public_read"] is True
    assert body["any_vulnerable"] is True
