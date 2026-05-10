"""APK upload dedup — same SHA-256 must not double-ingest.

The contract: ``orchestrator.ingest_apk`` and the ``/v1/apks/upload``
endpoint short-circuit when an APK with the same hash already has a
Project. Pass ``force=True`` to rescan in place.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    import importlib

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def _upload(client: TestClient, payload: bytes, *, force: bool = False) -> dict:
    data = {"package": "com.dedup.demo", "version": "1.0.0"}
    if force:
        data["force"] = "true"
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("dedup.apk", io.BytesIO(payload))},
        data=data,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_same_apk_returns_same_project(isolated_client: TestClient) -> None:
    """Re-uploading byte-identical content reuses the original project."""
    payload = b"PK\x03\x04dedup-fixture-v1"

    first = _upload(isolated_client, payload)
    second = _upload(isolated_client, payload)
    third = _upload(isolated_client, payload)

    assert first["project_id"] == second["project_id"] == third["project_id"]
    assert first["apk_sha256"] == second["apk_sha256"]
    # First call ingests; the next two are dedup hits.
    assert first["dedup"] is False
    assert second["dedup"] is True
    assert third["dedup"] is True

    # The store should still report exactly one project.
    listing = isolated_client.get("/v1/projects").json()
    assert sum(1 for p in listing if p["id"] == first["project_id"]) == 1


def test_different_bytes_create_separate_projects(isolated_client: TestClient) -> None:
    a = _upload(isolated_client, b"PK\x03\x04alpha")
    b = _upload(isolated_client, b"PK\x03\x04beta")
    assert a["project_id"] != b["project_id"]
    assert a["apk_sha256"] != b["apk_sha256"]
    assert a["dedup"] is False and b["dedup"] is False


def test_force_flag_rescans_existing_hash(isolated_client: TestClient) -> None:
    """`force=true` re-runs the pipeline even when the hash is cached.

    The project_id can change because ingest mints a fresh id when no
    `existing_id` is plumbed through — that's expected; what matters is
    that the dedup short-circuit didn't fire.
    """
    payload = b"PK\x03\x04force-rescan"

    first = _upload(isolated_client, payload)
    assert first["dedup"] is False

    forced = _upload(isolated_client, payload, force=True)
    # When force=true the upload endpoint re-runs the pipeline; the orchestrator
    # mints a fresh Project, so we should NOT see a dedup short-circuit.
    assert forced["dedup"] is False
    # The hash matches but a new project_id is allowed.
    assert forced["apk_sha256"] == first["apk_sha256"]


def test_find_by_sha256_lookup(tmp_path: Path) -> None:
    """ArtifactStore.find_by_sha256 returns None for unknown, the matching
    project for a known hash."""
    from mnexus.core.artifact_store import ArtifactStore
    from mnexus.models.attack_surface import AttackSurface
    from mnexus.models.project import Project

    apk = tmp_path / "x.apk"
    apk.write_bytes(b"PK\x03\x04find-fixture")
    project = Project.from_apk(apk, package_name="com.find.me", version="0.1")
    project.attack_surface = AttackSurface()

    store = ArtifactStore(tmp_path / "db.sqlite3")
    try:
        assert store.find_by_sha256(project.apk_sha256) is None  # not yet saved
        store.save_project(project)
        hit = store.find_by_sha256(project.apk_sha256)
        assert hit is not None
        assert hit.id == project.id
        assert store.find_by_sha256("0" * 64) is None
    finally:
        store.close()
