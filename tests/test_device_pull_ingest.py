"""POST /v1/device/pull — pull + auto-ingest contract.

Pulling an APK off a device should land you with a Project, not just a
file on disk. These tests pin:

  * Pulling for the first time → project_id is set, dedup=False.
  * Pulling the same APK twice → second call short-circuits with
    dedup=True and reuses the existing project_id.
  * Multi-APK bundles (base.apk + config splits) ingest the base APK.
  * ingest=false escape hatch returns pulled files but no project.
  * No device connected → 503 with a clear message.

We monkeypatch ADBEngine.is_device_connected + pull_apk on the
orchestrator's live engine instance, so no real device or adb binary
is involved.
"""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_stub_apk_bytes(marker: bytes = b"") -> bytes:
    # Just enough to look like a zip; orchestrator's apktool falls back to
    # filename when the manifest decode fails. Marker bytes change the SHA.
    return b"PK\x03\x04stub-pull-fixture" + marker


@pytest.fixture
def pull_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with the ADBEngine's two relevant methods stubbed.

    pull_apk writes a deterministic stub APK to the workspace and returns
    the path list — same shape as the real engine.
    """
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    from mnexus.api import main as api_main
    importlib.reload(api_main)

    with TestClient(api_main.app) as c:
        nexus = api_main.app.state.nexus
        adb = nexus.engines["adb"]

        async def is_device_connected_yes() -> bool:
            return True

        async def pull_apk_one(package_name: str, output_dir: Path) -> list[Path]:
            output_dir.mkdir(parents=True, exist_ok=True)
            local = output_dir / "base.apk"
            local.write_bytes(_make_stub_apk_bytes(package_name.encode()))
            return [local]

        async def pull_apk_split(package_name: str, output_dir: Path) -> list[Path]:
            output_dir.mkdir(parents=True, exist_ok=True)
            base = output_dir / "base.apk"
            base.write_bytes(_make_stub_apk_bytes(package_name.encode() + b"-base") * 50)
            split = output_dir / "split_config.arm64_v8a.apk"
            split.write_bytes(b"PK\x03\x04tiny-split")
            return [base, split]

        # Attach helpers to the client so tests can swap pull behaviour.
        c.stub_yes = is_device_connected_yes
        c.stub_pull_one = pull_apk_one
        c.stub_pull_split = pull_apk_split
        c.adb = adb
        # Default: device present, single APK.
        adb.is_device_connected = is_device_connected_yes  # type: ignore[method-assign]
        adb.pull_apk = pull_apk_one  # type: ignore[method-assign]
        yield c


def test_pull_creates_project_on_first_call(pull_client) -> None:
    r = pull_client.post("/v1/device/pull", data={"package": "com.xiaoji.egggame"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"], body
    assert body["project_id"].startswith("PRJ-")
    assert body["dedup"] is False
    assert body["count"] == 1
    assert body["files"][0].endswith("/base.apk")

    # The project is visible in the list immediately.
    listing = pull_client.get("/v1/projects").json()
    assert body["project_id"] in [p["id"] for p in listing]


def test_pull_second_call_deduplicates(pull_client) -> None:
    """Two pulls of the same package land you back on the same Project."""
    first = pull_client.post("/v1/device/pull", data={"package": "com.xiaoji.egggame"}).json()
    second = pull_client.post("/v1/device/pull", data={"package": "com.xiaoji.egggame"}).json()

    assert second["project_id"] == first["project_id"]
    assert second["dedup"] is True
    # Same file count, same SHA — the orchestrator didn't re-run the pipeline.
    assert second["apk_sha256"] == first["apk_sha256"]


def test_pull_force_rescans_even_when_hash_collides(pull_client) -> None:
    """force=true reruns the pipeline and produces a fresh Project record
    (same SHA, different id) rather than short-circuiting."""
    first = pull_client.post("/v1/device/pull", data={"package": "com.xiaoji.egggame"}).json()
    forced = pull_client.post(
        "/v1/device/pull",
        data={"package": "com.xiaoji.egggame", "force": "true"},
    ).json()
    assert forced["project_id"] != first["project_id"]
    assert forced["apk_sha256"] == first["apk_sha256"]
    assert forced["dedup"] is False


def test_pull_ingest_false_returns_files_without_project(pull_client) -> None:
    r = pull_client.post(
        "/v1/device/pull",
        data={"package": "com.xiaoji.egggame", "ingest": "false"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] is None
    assert body["dedup"] is False
    assert body["count"] == 1


def test_pull_multi_apk_picks_base(pull_client) -> None:
    """Split-APK bundles: ingest the base.apk, ignore config splits."""
    pull_client.adb.pull_apk = pull_client.stub_pull_split  # type: ignore[method-assign]
    body = pull_client.post("/v1/device/pull", data={"package": "com.xiaoji.egggame"}).json()
    assert body["project_id"]
    assert body["count"] == 2          # two files pulled
    # The base APK won because it's bigger AND named base.apk.
    assert any("base.apk" in f for f in body["files"])


def test_pull_no_device_returns_503(pull_client) -> None:
    async def is_device_connected_no() -> bool:
        return False

    pull_client.adb.is_device_connected = is_device_connected_no  # type: ignore[method-assign]
    r = pull_client.post("/v1/device/pull", data={"package": "com.xiaoji.egggame"})
    assert r.status_code == 503
    assert "no device" in r.text.lower()
