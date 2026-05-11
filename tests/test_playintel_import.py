"""POST /v1/playintel/scans/{id}/import — promote a Play Scan APK into a regular Project.

Pins:
  * Upload-mode scans persist the APK at workspace/playintel-uploads/<sha>.apk;
    /import re-ingests it as a regular Project (dedup + force semantics
    match /v1/apks/upload).
  * Re-importing the same scan short-circuits with dedup=True.
  * force=true bypasses dedup and creates a fresh Project.
  * Play-stream scans → 410 Gone with an actionable message.
  * Missing scan id → 404.

Seeding goes through the real /v1/playintel/scan-upload endpoint with
PlayIntelEngine.analyze_package monkeypatched to a minimal Outcome —
that way the PlayScanRecord row is written on the same thread that
owns the SQLite connection (avoiding the cross-thread trap), and we
exercise the actual scan → import handoff.
"""

from __future__ import annotations

import hashlib
import importlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_apk_bytes(marker: bytes) -> bytes:
    # Stub-zip trick — apktool fails on it, the pipeline falls back to
    # filename-based metadata. Enough for the dedup + Project-creation
    # round-trip we care about here.
    return b"PK\x03\x04playintel-import-fixture" + marker


@pytest.fixture
def play_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    # Stub the heavy Firebase analyser so /scan-upload finishes instantly
    # without phoning home. The pipeline still writes a real PlayScanRecord
    # via the actual code path on the right thread.
    from mnexus.engines import play_intel_engine
    from mnexus.playintel.analyzer import AnalysisOutcome
    from mnexus.playintel.scan_report import ScanReport
    from mnexus.playintel.apk_source import DownloadInfo

    async def stub_analyze(self, package, *, source, workspace, run_active_probes=False):  # noqa: D401
        outcome = AnalysisOutcome(
            package_name=package,
            download_info=DownloadInfo(
                package_name=package,
                base_url="",
                base_size=0,
                splits=[],
                additional_files=[],
            ),
            report=ScanReport(),
            saved_files_dir=None,
        )
        return outcome, []

    monkeypatch.setattr(play_intel_engine.PlayIntelEngine, "analyze_package", stub_analyze)

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c, api_main.app


def _seed_scan_via_upload(client, *, marker: bytes = b"") -> tuple[str, str]:
    """Run /v1/playintel/scan-upload with a fixture APK and return (scan_id, sha)."""
    apk = _make_apk_bytes(marker)
    sha = hashlib.sha256(apk).hexdigest()
    r = client.post(
        "/v1/playintel/scan-upload",
        files={"file": ("fixture.apk", io.BytesIO(apk), "application/vnd.android.package-archive")},
        data={"package": "com.target.app"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["scan_id"], sha




# ─── happy paths ──────────────────────────────────────────────────────


def test_import_upload_scan_creates_project(play_client) -> None:
    client, _ = play_client
    scan_id, _sha = _seed_scan_via_upload(client)

    r = client.post(f"/v1/playintel/scans/{scan_id}/import")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"].startswith("PRJ-")
    assert body["scan_id"] == scan_id
    assert body["package"] == "com.target.app"
    assert body["dedup"] is False

    # The Project is now in /v1/projects, addressable by the SPA.
    listing = client.get("/v1/projects").json()
    assert body["project_id"] in [p["id"] for p in listing]


def test_import_response_exposes_apk_local_path_on_record(play_client) -> None:
    """The /scans/{id} detail endpoint surfaces apk_local_path so the UI
    can decide whether the import button is even worth showing."""
    client, _ = play_client
    scan_id, _ = _seed_scan_via_upload(client)
    detail = client.get(f"/v1/playintel/scans/{scan_id}").json()
    assert detail.get("apk_local_path", "").endswith(".apk")
    assert Path(detail["apk_local_path"]).exists()


def test_import_twice_returns_dedup(play_client) -> None:
    client, _ = play_client
    scan_id, _ = _seed_scan_via_upload(client)
    first = client.post(f"/v1/playintel/scans/{scan_id}/import").json()
    second = client.post(f"/v1/playintel/scans/{scan_id}/import").json()
    assert second["project_id"] == first["project_id"]
    assert second["dedup"] is True


def test_import_force_rescans(play_client) -> None:
    client, _ = play_client
    scan_id, _ = _seed_scan_via_upload(client)
    first = client.post(f"/v1/playintel/scans/{scan_id}/import").json()
    forced = client.post(f"/v1/playintel/scans/{scan_id}/import", data={"force": "true"}).json()
    assert forced["project_id"] != first["project_id"]
    assert forced["apk_sha256"] == first["apk_sha256"]
    assert forced["dedup"] is False


# ─── failure modes ────────────────────────────────────────────────────


def test_import_returns_410_when_apk_is_truly_gone(play_client) -> None:
    """Wipe both the apk_local_path file AND the sha-keyed cache copy →
    import has nothing to ingest and must surface 410, not 500."""
    client, app = play_client
    scan_id, sha = _seed_scan_via_upload(client)
    detail = client.get(f"/v1/playintel/scans/{scan_id}").json()
    Path(detail["apk_local_path"]).unlink(missing_ok=True)
    cache = app.state.nexus.config.workspace / "playintel-uploads" / f"{sha}.apk"
    cache.unlink(missing_ok=True)

    r = client.post(f"/v1/playintel/scans/{scan_id}/import")
    assert r.status_code == 410
    assert "no on-disk APK" in r.text or "no on-disk" in r.text


def test_import_unknown_scan_returns_404(play_client) -> None:
    client, _ = play_client
    r = client.post("/v1/playintel/scans/PSC-NOPE/import")
    assert r.status_code == 404
    assert "PSC-NOPE" in r.text


# ─── reverse direction: from a Project, run a Play Scan ───────────────


def test_project_play_scan_runs_on_existing_apk(play_client) -> None:
    """An existing Project has the APK on disk — /play-scan must reuse it
    instead of forcing the analyst to re-upload."""
    client, _ = play_client
    # Step 1: upload an APK as a regular Project.
    apk_bytes = _make_apk_bytes(b"project-replay")
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0"},
    )
    assert r.status_code == 200, r.text
    project_id = r.json()["project_id"]

    # Step 2: trigger a PlayIntel scan against that Project.
    scan_resp = client.post(f"/v1/projects/{project_id}/play-scan")
    assert scan_resp.status_code == 200, scan_resp.text
    scan = scan_resp.json()
    assert scan["package"] == "com.target.app"
    assert scan["source"].startswith("project:")
    assert scan["scan_id"].startswith("PSC-")


def test_project_play_scan_410_when_apk_missing_from_workspace(play_client) -> None:
    """If the Project's stored APK got deleted out from under us, the
    endpoint surfaces 410 instead of crashing on the analyser."""
    client, app = play_client
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(_make_apk_bytes(b"will-delete")), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0"},
    )
    project_id = r.json()["project_id"]

    # Wipe the on-disk artefact.
    detail = client.get(f"/v1/projects/{project_id}").json()
    Path(detail["apk_path"]).unlink(missing_ok=True)

    scan_resp = client.post(f"/v1/projects/{project_id}/play-scan")
    assert scan_resp.status_code == 410
    assert "APK no longer present" in scan_resp.text or "no longer present" in scan_resp.text


def test_scans_list_filters_by_apk_sha256(play_client) -> None:
    """The Overview panel asks /scans?apk_sha256=… to decide whether the
    APK has any history — pinning that filter here."""
    client, _ = play_client

    # Two distinct uploads → two scans, two distinct shas.
    sid_a, sha_a = _seed_scan_via_upload(client, marker=b"a")
    sid_b, sha_b = _seed_scan_via_upload(client, marker=b"b")
    assert sha_a != sha_b

    only_a = client.get(f"/v1/playintel/scans?apk_sha256={sha_a}").json()
    assert only_a["count"] == 1
    assert only_a["scans"][0]["id"] == sid_a

    only_b = client.get(f"/v1/playintel/scans?apk_sha256={sha_b}").json()
    assert {s["id"] for s in only_b["scans"]} == {sid_b}

    # Unknown sha → empty list, not 404.
    none = client.get("/v1/playintel/scans?apk_sha256=00deadbeef").json()
    assert none["count"] == 0


def test_project_play_scan_then_overview_finds_it_by_sha(play_client) -> None:
    """Round-trip the contract the UI relies on: scan a Project, then
    query /scans?apk_sha256=<project's sha> and find the same scan."""
    client, _ = play_client
    apk_bytes = _make_apk_bytes(b"roundtrip")
    sha = hashlib.sha256(apk_bytes).hexdigest()
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0"},
    )
    project_id = r.json()["project_id"]

    scan_resp = client.post(f"/v1/projects/{project_id}/play-scan").json()
    scan_id = scan_resp["scan_id"]

    history = client.get(f"/v1/playintel/scans?apk_sha256={sha}").json()
    assert scan_id in {s["id"] for s in history["scans"]}
