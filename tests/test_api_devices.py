"""Multi-device ADB endpoints — `/v1/devices` and friends.

CI / test boxes don't have a phone plugged in, so we mostly verify shapes
and graceful empty responses. The handlers shell out to `adb`; if `adb`
isn't installed at all, we still get a clean empty list.
"""

from __future__ import annotations

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


def test_devices_flavors_advertises_adb_server_default(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/devices/flavors")
    assert r.status_code == 200
    body = r.json()
    assert body["adb_server"] is True
    # The other two flavors are flagged as not-yet-implemented.
    assert body["webusb_yaadb"] is False
    assert body["webrtc_signaling"] is False


def test_devices_list_returns_array(isolated_client: TestClient) -> None:
    """No phone in CI ⇒ either an empty list or zero `device`-state rows."""
    r = isolated_client.get("/v1/devices")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # If `adb` is installed but no phone is plugged in, it's []. Either way valid.
    for d in body:
        assert "serial" in d and "state" in d


def test_devices_disconnect_returns_output_envelope(isolated_client: TestClient) -> None:
    """Disconnect on a non-existent serial — shape check only."""
    r = isolated_client.post("/v1/devices/totally-fake-serial/disconnect")
    assert r.status_code == 200
    body = r.json()
    assert body["serial"] == "totally-fake-serial"
    assert "output" in body


def test_devices_connect_form_required(isolated_client: TestClient) -> None:
    """`host` is mandatory."""
    r = isolated_client.post("/v1/devices/connect")
    assert r.status_code == 422  # missing form field


def test_devices_shell_form_required(isolated_client: TestClient) -> None:
    """`cmd` is mandatory."""
    r = isolated_client.post("/v1/devices/anything/shell")
    assert r.status_code == 422


def test_screencap_returns_503_with_diagnostics_when_no_device(isolated_client: TestClient) -> None:
    """Pin the diagnostic envelope so the SPA banner has the keys it expects."""
    r = isolated_client.get("/v1/devices/totally-fake-serial/screencap.png")
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["error"] == "screencap_failed"
    assert "exec_out" in body["detail"]
    assert "temp_file" in body["detail"]
    assert "hint" in body["detail"]


def test_screencap_debug_returns_both_path_attempts(isolated_client: TestClient) -> None:
    """The debug endpoint must report exec-out + temp-file diag, even on failure."""
    r = isolated_client.get("/v1/devices/totally-fake-serial/screencap-debug")
    assert r.status_code == 200
    body = r.json()
    for key in ("exec_out", "temp_file", "picked"):
        assert key in body
    assert body["exec_out"]["ok"] is False
    assert body["temp_file"]["ok"] is False
    assert body["picked"] == "none"


def test_install_project_404_when_project_unknown(isolated_client: TestClient) -> None:
    """install-project must reject a missing project_id with 404 (no silent install)."""
    r = isolated_client.post(
        "/v1/devices/fake-serial/install-project",
        data={"project_id": "PRJ-DOES-NOT-EXIST"},
    )
    assert r.status_code == 404


def test_install_project_404_when_apk_file_missing(
    isolated_client: TestClient, tmp_path: Path
) -> None:
    """If the project exists but the APK file was wiped, return a structured 404."""
    import io

    # Upload, then delete the APK behind its back.
    up = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("a.apk", io.BytesIO(b"PK\x03\x04"))},
        data={"package": "com.example", "version": "1.0"},
    )
    assert up.status_code == 200
    pid = up.json()["project_id"]
    detail = isolated_client.get(f"/v1/projects/{pid}").json()
    apk_disk_path = Path(detail["apk_path"])
    apk_disk_path.unlink()

    r = isolated_client.post(
        f"/v1/devices/fake-serial/install-project",
        data={"project_id": pid},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error"] == "apk_missing_on_disk"
    assert "expected_path" in body["detail"]


def test_install_project_form_required(isolated_client: TestClient) -> None:
    r = isolated_client.post("/v1/devices/fake/install-project")
    assert r.status_code == 422


def test_mjpeg_stream_advertises_multipart_content_type(isolated_client: TestClient) -> None:
    """The MJPEG endpoint streams multipart/x-mixed-replace.

    Headers are set immediately; the generator only yields once a frame is
    captured. With no real device, we expect no frames — but the response
    headers must announce the correct content type up front so the browser
    knows it's getting a multipart stream.
    """
    with isolated_client.stream("GET", "/v1/devices/fake-serial/screen.mjpeg?fps=2") as r:
        assert r.status_code == 200
        assert "multipart/x-mixed-replace" in r.headers["content-type"]
        assert r.headers.get("X-MNexus-Stream") == "mjpeg-png"
        # Don't drain the body — that'd block until adb finally fails enough times.
