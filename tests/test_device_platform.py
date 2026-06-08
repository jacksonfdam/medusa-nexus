"""Auto-detect device platform — /v1/devices tags each entry as
android | ios so the UI can filter recipes correctly.

Tests mock both adb (via _run on the engine) and frida.get_device_manager
so the test runs without phones or frida-server.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


_ADB_OUTPUT_ONE_DEVICE = """List of devices attached
RZCXA15YFEJ           device usb:336592896X product:beyond1lteue model:SM_G973F device:beyond1lte
"""


@pytest.fixture
def device_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with adb + frida stubbed deterministically."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    # Pretend adb is on PATH.
    monkeypatch.setattr("mnexus.api.main.shutil.which", lambda name: "/usr/local/bin/adb" if name in ("adb", "/usr/local/bin/adb") else None)

    # No iOS device by default — individual tests override.
    monkeypatch.setattr("mnexus.runtime.FRIDA_AVAILABLE", True)

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        # Hand-stub the orchestrator's ADBEngine._run so adb invocations
        # return canned output instead of shelling out for real.
        adb = api_main.app.state.nexus.engines["adb"]
        adb._run = _make_fake_adb_run(_ADB_OUTPUT_ONE_DEVICE)  # type: ignore[method-assign]
        yield c, api_main, adb


def _make_fake_adb_run(devices_output: str):
    """Build an async _run replacement that returns canned strings."""

    async def _run(cmd):  # noqa: ANN001
        joined = " ".join(cmd)
        if "devices" in joined and "-l" in joined:
            return devices_output
        if "wm size" in joined:
            return "Physical size: 1080x2340\n"
        if "frida-server" in joined and "shell ls" in joined:
            return "/data/local/tmp/frida-server\n"
        if "pgrep" in joined:
            return ""
        # getprop calls — return a benign default.
        return "stub\n"

    return _run


def test_android_device_tagged_with_platform_android(device_client) -> None:
    client, _, _ = device_client
    rows = client.get("/v1/devices").json()
    assert rows, "no devices returned"
    assert all(d.get("platform") == "android" for d in rows if d.get("state") == "device")
    assert rows[0]["serial"] == "RZCXA15YFEJ"


def test_ios_device_appended_when_frida_sees_one(device_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Frida enumerates a USB device with a 24-char hex id (UDID shape)
    that adb doesn't see — should land in the response as platform=ios."""
    client, api_main, _ = device_client

    class _FakeDev:
        id = "00008030-001A28941A82802E"
        name = "Test iPhone"
        type = "usb"

        def query_system_parameters(self):
            return {"os": {"version": "17.4"}, "arch": "arm64", "udid": self.id}

    class _FakeMgr:
        def enumerate_devices(self):
            return [_FakeDev()]

    monkeypatch.setattr("frida.get_device_manager", lambda: _FakeMgr())

    rows = client.get("/v1/devices").json()
    ios = [d for d in rows if d.get("platform") == "ios"]
    assert len(ios) == 1
    assert ios[0]["serial"] == "00008030-001A28941A82802E"
    assert ios[0]["model"] == "Test iPhone"
    assert ios[0]["ios_version"] == "17.4"
    assert ios[0]["arch"] == "arm64"
    assert ios[0]["frida_visible"] is True


def test_ios_enumeration_silent_when_frida_missing(device_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """No frida → only Android devices, no exception."""
    client, _, _ = device_client
    monkeypatch.setattr("mnexus.runtime.FRIDA_AVAILABLE", False)
    rows = client.get("/v1/devices").json()
    assert all(d.get("platform") == "android" for d in rows if d.get("state") == "device")


def test_ios_enumeration_silent_when_frida_raises(device_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """If get_device_manager / enumerate_devices throws, the endpoint
    still returns the Android half without 500ing."""
    client, _, _ = device_client

    class _Boom:
        def enumerate_devices(self):
            raise RuntimeError("usb stack went sideways")

    monkeypatch.setattr("frida.get_device_manager", lambda: _Boom())
    rows = client.get("/v1/devices").json()
    # Android entries survive.
    assert any(d.get("platform") == "android" for d in rows)
    # No iOS rows because the enumeration raised.
    assert not any(d.get("platform") == "ios" for d in rows)


def test_device_in_both_adb_and_frida_marked_visible_not_duplicated(device_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A device that shows up in both adb AND frida (rare passthrough
    setups) appears once in the response, with frida_visible=True."""
    client, _, _ = device_client

    class _FakeDev:
        id = "RZCXA15YFEJ"  # same as the adb-stubbed serial
        name = "Galaxy S10"
        type = "usb"

        def query_system_parameters(self):
            return {}

    class _FakeMgr:
        def enumerate_devices(self):
            return [_FakeDev()]

    monkeypatch.setattr("frida.get_device_manager", lambda: _FakeMgr())

    rows = client.get("/v1/devices").json()
    assert len(rows) == 1
    assert rows[0]["platform"] == "android"
    assert rows[0]["frida_visible"] is True
