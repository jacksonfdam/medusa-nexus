"""Scan history — model, store CRUD, and the three /v1/playintel/scans
endpoints. Wired to assert that every successful /scan persists a row
and that the history listing respects the package filter + limit.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mnexus.core.artifact_store import ArtifactStore
from mnexus.models.play_scan import PlayScanRecord


# ─── store-level CRUD ─────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[ArtifactStore]:
    s = ArtifactStore(tmp_path / "nexus.sqlite3")
    yield s
    s.close()


def test_save_round_trip_preserves_payload_and_counts(store: ArtifactStore) -> None:
    record = PlayScanRecord(
        package="com.alpha",
        version_name="1.0.0",
        version_code=42,
        source="upload",
        source_label="upload:alpha.apk",
        apk_sha256="abc123",
        firebase_project_count=2,
        confirmed_secrets_count=1,
        suspected_secrets_count=3,
        vulnerability_count=0,
        findings_count=4,
        saved_files_count=1,
        payload={"package": "com.alpha", "findings": [{"id": "F1"}, {"id": "F2"}]},
    )
    store.save_play_scan(record)
    got = store.get_play_scan(record.id)
    assert got is not None
    assert got.package == "com.alpha"
    assert got.version_code == 42
    assert got.firebase_project_count == 2
    assert got.payload["findings"][1]["id"] == "F2"


def test_list_orders_recent_first(store: ArtifactStore) -> None:
    """Even when scanned_at is set out of order, the listing returns
    most-recent first — that's the contract the UI relies on."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(3):
        store.save_play_scan(PlayScanRecord(
            package="com.alpha",
            source="play",
            source_label="play:test",
            scanned_at=base.replace(hour=i),
            payload={},
        ))
    rows = store.list_play_scans()
    timestamps = [r.scanned_at.hour for r in rows]
    assert timestamps == [2, 1, 0]


def test_list_filters_by_package(store: ArtifactStore) -> None:
    store.save_play_scan(PlayScanRecord(package="com.alpha", source="play", source_label="play", payload={}))
    store.save_play_scan(PlayScanRecord(package="com.beta", source="play", source_label="play", payload={}))
    store.save_play_scan(PlayScanRecord(package="com.alpha", source="play", source_label="play", payload={}))
    alpha = store.list_play_scans(package="com.alpha")
    assert len(alpha) == 2
    assert all(r.package == "com.alpha" for r in alpha)


def test_list_clamps_limit_into_safe_range(store: ArtifactStore) -> None:
    """Limit is clamped to [1, 1000] — a misclick can't drag a huge
    listing, and zero/negative is treated as 1."""
    for i in range(5):
        store.save_play_scan(PlayScanRecord(package=f"com.app{i}", source="play", source_label="play", payload={}))
    assert len(store.list_play_scans(limit=0)) == 1
    assert len(store.list_play_scans(limit=-100)) == 1
    assert len(store.list_play_scans(limit=10_000)) == 5  # clamp → 1000, but only 5 rows exist


def test_delete_returns_false_for_missing(store: ArtifactStore) -> None:
    assert store.delete_play_scan("never-existed") is False


def test_summary_redacts_payload(store: ArtifactStore) -> None:
    """summary() is what the listing endpoint serialises; it must not
    leak the payload (which can be many KB and contains AAS-adjacent
    things like signed CDN URLs)."""
    record = PlayScanRecord(
        package="com.alpha",
        source="play",
        source_label="play:test",
        payload={"deeply": {"nested": "secret"}},
    )
    summary = record.summary()
    assert "payload" not in summary
    # But the structured fields the listing UI depends on must be present.
    for key in ("id", "package", "source", "source_label", "scanned_at",
                "firebase_project_count", "findings_count"):
        assert key in summary


def test_corrupted_payload_does_not_break_get(store: ArtifactStore) -> None:
    """A row with invalid-JSON in the payload column comes back with
    payload={} rather than crashing the listing endpoint."""
    record = PlayScanRecord(package="com.x", source="play", source_label="play", payload={})
    store.save_play_scan(record)
    # Hand-corrupt the JSON.
    store._conn.execute("UPDATE playintel_scans SET payload='not json' WHERE id = ?", (record.id,))  # noqa: SLF001
    store._conn.commit()  # noqa: SLF001
    got = store.get_play_scan(record.id)
    assert got is not None
    assert got.payload == {}


# ─── HTTP layer ──────────────────────────────────────────────────────────


def _make_minimal_apk(path: Path, *, package: str = "com.test.fixture") -> Path:
    """A zero-feature .apk that's just enough to satisfy LocalAPKSource —
    a zip with a token AndroidManifest.xml. The playintel scanner's
    whitelist will skip it (no resources.arsc, no google-services), so
    the run produces an empty report; that's fine for the test."""
    with zipfile.ZipFile(path, "w") as zf:
        # Zero-content "manifest" — the scanner's manifest matcher
        # tolerates non-AXML for tests since extract_manifest is best-effort.
        zf.writestr("AndroidManifest.xml", f"<manifest package=\"{package}\"/>")
    return path


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    import importlib

    import mnexus.api.main as api_main

    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def test_list_starts_empty(client: TestClient) -> None:
    r = client.get("/v1/playintel/scans")
    assert r.status_code == 200
    body = r.json()
    assert body == {"scans": [], "count": 0}


def test_get_missing_returns_404(client: TestClient) -> None:
    r = client.get("/v1/playintel/scans/PSC-DEADBEEF")
    assert r.status_code == 404


def test_delete_missing_returns_404(client: TestClient) -> None:
    r = client.delete("/v1/playintel/scans/PSC-DEADBEEF")
    assert r.status_code == 404


def test_scan_upload_persists_history_row(client: TestClient, tmp_path: Path) -> None:
    """End-to-end: a successful /scan-upload writes one row that the
    listing endpoint picks up. Asserts the denormalised counts and
    that scan_id round-trips back through /scans/{id}."""
    apk = _make_minimal_apk(tmp_path / "fixture.apk")
    with apk.open("rb") as fh:
        r = client.post(
            "/v1/playintel/scan-upload",
            files={"file": ("fixture.apk", fh, "application/octet-stream")},
            data={"package": "com.test.fixture", "run_active_probes": "false"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "scan_id" in data and data["scan_id"].startswith("PSC-")
    assert data["package"] == "com.test.fixture"
    assert data["apk_sha256"]  # streaming upload computed it

    # Listing surfaces the row with denormalised counts.
    listing = client.get("/v1/playintel/scans").json()
    assert listing["count"] == 1
    row = listing["scans"][0]
    assert row["id"] == data["scan_id"]
    assert row["package"] == "com.test.fixture"
    assert row["source"] == "upload"
    assert row["source_label"].startswith("upload:")

    # Detail rehydrates the full payload.
    detail = client.get(f"/v1/playintel/scans/{data['scan_id']}").json()
    assert detail["payload"]["package"] == "com.test.fixture"
    assert detail["payload"]["scan_id"] == data["scan_id"]


def test_listing_filters_by_package_and_clamps_limit(client: TestClient, tmp_path: Path) -> None:
    """Two uploads under different packages — the package filter
    narrows correctly, and limit=10000 doesn't overrun the database."""
    apk_a = _make_minimal_apk(tmp_path / "alpha.apk", package="com.alpha")
    apk_b = _make_minimal_apk(tmp_path / "beta.apk", package="com.beta")
    for path, package in [(apk_a, "com.alpha"), (apk_b, "com.beta"), (apk_a, "com.alpha")]:
        with path.open("rb") as fh:
            client.post(
                "/v1/playintel/scan-upload",
                files={"file": (path.name, fh, "application/octet-stream")},
                data={"package": package},
            )
    listing = client.get("/v1/playintel/scans").json()
    assert listing["count"] == 3
    alpha_only = client.get("/v1/playintel/scans?package=com.alpha").json()
    assert alpha_only["count"] == 2
    assert all(s["package"] == "com.alpha" for s in alpha_only["scans"])
    big = client.get("/v1/playintel/scans?limit=10000").json()
    assert big["count"] == 3  # clamp doesn't invent rows


def test_delete_endpoint_removes_row(client: TestClient, tmp_path: Path) -> None:
    apk = _make_minimal_apk(tmp_path / "fixture.apk")
    with apk.open("rb") as fh:
        r = client.post(
            "/v1/playintel/scan-upload",
            files={"file": ("fixture.apk", fh, "application/octet-stream")},
            data={"package": "com.test.fixture"},
        )
    scan_id = r.json()["scan_id"]
    delete_resp = client.delete(f"/v1/playintel/scans/{scan_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": scan_id}
    assert client.get("/v1/playintel/scans").json()["count"] == 0
