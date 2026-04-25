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
