"""``mnexus.runtime.FridaSession`` + ``/dynamic/{start,stop,stream}`` round-trip.

We don't want CI to need a phone — Frida is monkeypatched with a tiny
fake that mirrors the real API surface: ``get_device_manager``,
``Device.spawn``, ``Device.attach``, ``Session.create_script``,
``Script.on`` / ``load`` / ``unload``, ``Device.resume`` / ``kill``.

The fake records every call so the tests can assert lifecycle order
(spawn → attach → load → resume → unload → detach → kill), and the
``send({...})`` channel is exercised by manually invoking the captured
``on_message`` handler — same shape Frida uses when a real device fires
an event.
"""

from __future__ import annotations

import importlib
import io
import json
import time
from typing import Any

import pytest


# ─── fake frida ───────────────────────────────────────────────────────


class _FakeScript:
    def __init__(self, source: str) -> None:
        self.source = source
        self.handlers: dict[str, Any] = {}
        self.loaded = False
        self.unloaded = False

    def on(self, event: str, handler) -> None:  # type: ignore[no-untyped-def]
        self.handlers[event] = handler

    def load(self) -> None:
        self.loaded = True

    def unload(self) -> None:
        self.unloaded = True


class _FakeSession:
    def __init__(self) -> None:
        self.scripts: list[_FakeScript] = []
        self.detached = False

    def create_script(self, source: str) -> _FakeScript:
        s = _FakeScript(source)
        self.scripts.append(s)
        return s

    def detach(self) -> None:
        self.detached = True


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _FakeDevice:
    def __init__(self, *, id: str = "usb-A1B2C3", processes: dict[str, int] | None = None) -> None:
        self.id = id
        self.spawned: list[str] = []
        self.attached: list[int] = []
        self.resumed: list[int] = []
        self.killed: list[int] = []
        self._processes = processes or {}

    def spawn(self, args: list[str]) -> int:
        self.spawned.append(args[0])
        return 12345

    def attach(self, pid: int) -> _FakeSession:
        self.attached.append(pid)
        return _FakeSession()

    def resume(self, pid: int) -> None:
        self.resumed.append(pid)

    def kill(self, pid: int) -> None:
        self.killed.append(pid)

    def get_process(self, package: str) -> _FakeProcess:
        if package not in self._processes:
            raise RuntimeError(f"process not found: {package}")
        return _FakeProcess(self._processes[package])


class _FakeDeviceManager:
    def __init__(self, device: _FakeDevice | None = None) -> None:
        self._device = device

    def get_usb_device(self, timeout: float = 2) -> _FakeDevice:  # noqa: ARG002
        if self._device is None:
            raise RuntimeError("no device")
        return self._device

    def get_device(self, device_id: str, timeout: float = 2) -> _FakeDevice:  # noqa: ARG002
        if self._device is None or self._device.id != device_id:
            raise RuntimeError(f"no device {device_id}")
        return self._device


@pytest.fixture
def fake_frida(monkeypatch: pytest.MonkeyPatch):
    """Install a fake `frida` module + flip FRIDA_AVAILABLE on.

    Returns the FakeDeviceManager so the test can inspect / swap the
    device after the session starts.
    """
    device = _FakeDevice(processes={"com.target.app": 4321})
    manager = _FakeDeviceManager(device=device)

    class _FakeFrida:
        @staticmethod
        def get_device_manager():
            return manager

    # Reload runtime so module-level FRIDA_AVAILABLE / `frida` binding
    # picks up our fake on import.
    from mnexus.runtime import frida_session as fs
    monkeypatch.setattr(fs, "frida", _FakeFrida)
    monkeypatch.setattr(fs, "FRIDA_AVAILABLE", True)
    fs.session_registry.clear()

    return {"device": device, "manager": manager, "module": fs}


# ─── unit: FridaSession lifecycle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_session_start_spawns_attaches_loads_and_resumes(fake_frida) -> None:
    fs = fake_frida["module"]
    sess = await fs.FridaSession.start(
        project_id="PRJ-X",
        package="com.target.app",
        scripts=[("ssl_pinning_bypass", "// js")],
        spawn=True,
    )
    device = fake_frida["device"]
    assert sess.state == "attached"
    assert sess.pid == 12345
    assert device.spawned == ["com.target.app"]
    assert device.attached == [12345]
    assert device.resumed == [12345]
    # The single script was loaded.
    assert len(sess.scripts) == 1
    assert sess.scripts[0].handle.loaded is True
    # And the session is in the registry.
    assert fs.session_registry[sess.session_id] is sess


@pytest.mark.asyncio
async def test_session_attach_mode_finds_existing_pid(fake_frida) -> None:
    fs = fake_frida["module"]
    sess = await fs.FridaSession.start(
        project_id="PRJ-X",
        package="com.target.app",
        scripts=[],
        spawn=False,
    )
    assert sess.pid == 4321
    # No spawn happened; no resume needed.
    assert fake_frida["device"].spawned == []
    assert fake_frida["device"].resumed == []


@pytest.mark.asyncio
async def test_session_stop_unloads_detaches_kills(fake_frida) -> None:
    fs = fake_frida["module"]
    sess = await fs.FridaSession.start(
        project_id="PRJ-X",
        package="com.target.app",
        scripts=[("noop", "// js")],
        spawn=True,
    )
    await sess.stop()
    assert sess.state == "detached"
    # Script was unloaded, session detached, owned PID killed.
    assert sess.scripts[0].handle.unloaded is True
    assert fake_frida["device"].killed == [12345]


@pytest.mark.asyncio
async def test_session_stop_is_idempotent(fake_frida) -> None:
    """Double-stop must not blow up — common when the UI sends a stop
    right after detecting the end-of-stream event."""
    fs = fake_frida["module"]
    sess = await fs.FridaSession.start(project_id="PRJ-X", package="com.target.app", scripts=[])
    await sess.stop()
    await sess.stop()
    assert sess.state == "detached"


@pytest.mark.asyncio
async def test_no_usb_device_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare ``no device`` raise must lift to NoDeviceError so the API
    layer can answer 503 with the right message."""
    class _Empty:
        @staticmethod
        def get_device_manager():
            class _M:
                def get_usb_device(self, timeout: float = 2):  # noqa: ARG002
                    raise RuntimeError("nothing connected")
            return _M()

    from mnexus.runtime import frida_session as fs
    monkeypatch.setattr(fs, "frida", _Empty)
    monkeypatch.setattr(fs, "FRIDA_AVAILABLE", True)
    fs.session_registry.clear()

    with pytest.raises(fs.NoDeviceError):
        await fs.FridaSession.start(project_id="PRJ-X", package="com.target.app", scripts=[])


@pytest.mark.asyncio
async def test_frida_not_installed_raises_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from mnexus.runtime import frida_session as fs
    monkeypatch.setattr(fs, "FRIDA_AVAILABLE", False)
    monkeypatch.setattr(fs, "frida", None)
    with pytest.raises(fs.FridaNotInstalled):
        await fs.FridaSession.start(project_id="PRJ-X", package="com.target.app", scripts=[])


@pytest.mark.asyncio
async def test_message_handler_fans_out_to_listeners(fake_frida) -> None:
    """Every ``send({...})`` from JS lands on every registered listener
    and shows up in the session's in-memory log."""
    fs = fake_frida["module"]
    sess = await fs.FridaSession.start(
        project_id="PRJ-X",
        package="com.target.app",
        scripts=[("ssl_pinning_bypass", "// js")],
    )
    captured: list[dict] = []
    sess.add_listener(captured.append)

    # Fish the on_message handler out of the script (Frida would call this
    # from its own thread when send() fires inside the JS).
    on_msg = sess.scripts[0].handle.handlers["message"]
    on_msg({"type": "send", "payload": {"channel": "ssl_pin", "host": "api.x.com", "lib": "okhttp", "outcome": "bypassed"}}, None)
    on_msg({"type": "send", "payload": {"channel": "ssl_pin", "host": "api.x.com", "lib": "okhttp", "outcome": "bypassed"}}, None)

    assert len(captured) == 2
    assert captured[0]["channel"] == "ssl_pin"
    assert captured[0]["payload"]["host"] == "api.x.com"
    # And the in-memory log carries a one-liner per event.
    log_lines = [entry for entry in sess.log if entry["channel"] == "ssl_pin"]
    assert len(log_lines) == 2
    assert "api.x.com" in log_lines[0]["line"]


@pytest.mark.asyncio
async def test_message_handler_translates_frida_errors(fake_frida) -> None:
    """Frida emits ``{type:'error',description,...}`` when the JS throws —
    we surface those as channel='error' so the UI can paint them red."""
    fs = fake_frida["module"]
    sess = await fs.FridaSession.start(project_id="PRJ-X", package="com.target.app", scripts=[("x", "// js")])
    captured: list[dict] = []
    sess.add_listener(captured.append)
    on_msg = sess.scripts[0].handle.handlers["message"]
    on_msg({"type": "error", "description": "ReferenceError: foo is not defined", "lineNumber": 12}, None)
    assert captured[-1]["channel"] == "error"
    assert "ReferenceError" in captured[-1]["payload"]["description"]


# ─── /dynamic/start + /dynamic/stop + SSE round-trip ──────────────────


@pytest.fixture
def dyn_client(tmp_path, monkeypatch: pytest.MonkeyPatch, fake_frida):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub"), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid, api_main.app


def test_dynamic_start_returns_attached_session_with_stream_url(dyn_client) -> None:
    client, pid, _ = dyn_client
    r = client.post(
        f"/v1/projects/{pid}/dynamic/start",
        data={"hooks": "", "spawn": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "attached"
    assert body["pid"] == 12345
    assert body["stream_url"].endswith(f"session_id={body['session_id']}")


def test_dynamic_start_503_when_no_device(monkeypatch: pytest.MonkeyPatch, dyn_client) -> None:
    """Swap the fake device manager mid-session to simulate the phone
    going away between requests."""
    client, pid, app = dyn_client

    from mnexus.runtime import frida_session as fs

    class _Empty:
        @staticmethod
        def get_device_manager():
            class _M:
                def get_usb_device(self, timeout: float = 2):  # noqa: ARG002
                    raise RuntimeError("unplugged")
            return _M()

    monkeypatch.setattr(fs, "frida", _Empty)

    r = client.post(f"/v1/projects/{pid}/dynamic/start", data={"hooks": ""})
    assert r.status_code == 503


def test_dynamic_start_503_when_frida_not_installed(monkeypatch: pytest.MonkeyPatch, dyn_client) -> None:
    client, pid, _ = dyn_client
    from mnexus.runtime import frida_session as fs
    monkeypatch.setattr(fs, "FRIDA_AVAILABLE", False)
    r = client.post(f"/v1/projects/{pid}/dynamic/start", data={"hooks": ""})
    assert r.status_code == 503
    assert "frida not installed" in r.text.lower()


def test_dynamic_start_400_on_unknown_hook(dyn_client) -> None:
    client, pid, _ = dyn_client
    r = client.post(f"/v1/projects/{pid}/dynamic/start", data={"hooks": "does_not_exist"})
    # Empty surface → no hooks generated → unknown name → 400.
    assert r.status_code in (400, 404), r.text


def test_dynamic_stop_detaches_and_kills_pid(dyn_client) -> None:
    client, pid, _ = dyn_client
    start = client.post(f"/v1/projects/{pid}/dynamic/start", data={"hooks": ""}).json()
    sid = start["session_id"]
    r = client.post(f"/v1/projects/{pid}/dynamic/stop", data={"session_id": sid})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "detached"


def test_dynamic_stop_404_for_unknown_session(dyn_client) -> None:
    client, pid, _ = dyn_client
    r = client.post(f"/v1/projects/{pid}/dynamic/stop", data={"session_id": "ghost"})
    assert r.status_code == 404


def test_dynamic_events_polling_endpoint_reflects_real_session(dyn_client) -> None:
    """The legacy GET /dynamic/events keeps working — it now reads from
    the registry instead of the old _SESSIONS dict."""
    client, pid, _ = dyn_client
    start = client.post(f"/v1/projects/{pid}/dynamic/start", data={"hooks": ""}).json()
    sid = start["session_id"]
    body = client.get(f"/v1/projects/{pid}/dynamic/events?session_id={sid}").json()
    assert body["session_id"] == sid
    assert body["state"] == "attached"
    assert any("[NEXUS]" in entry["line"] for entry in body["log"])


def test_dynamic_stream_replays_log_then_ends_after_detach(dyn_client) -> None:
    """SSE smoke test.

    To avoid blocking the test on the 15s heartbeat, we detach the
    session BEFORE opening the stream. The generator then:
      1. Yields one ``event: log`` frame per replayed log entry.
      2. Awaits ``queue.get`` with timeout=15s.
      3. Sees state == 'detached' on the post-wait branch and yields
         an ``event: end`` frame, then returns.

    Since the detached check is reached before any live event, the
    generator returns inside the first heartbeat window — and in
    practice instantly, because there's nothing on the queue to wait
    for past the replay.
    """
    client, pid, _ = dyn_client
    start = client.post(f"/v1/projects/{pid}/dynamic/start", data={"hooks": ""}).json()
    sid = start["session_id"]
    # Detach so the stream's state check fires on the first iteration.
    stop = client.post(f"/v1/projects/{pid}/dynamic/stop", data={"session_id": sid})
    assert stop.status_code == 200

    with client.stream("GET", f"/v1/projects/{pid}/dynamic/stream?session_id={sid}") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.read()  # Generator returns after end-of-stream → reads to EOF.

    text = body.decode("utf-8", errors="replace")
    # Replay carried at least the 'session active' marker.
    assert "event: log" in text
    assert "[NEXUS]" in text
    # And the end-of-stream frame fired with reason=detached.
    assert "event: end" in text
    assert "detached" in text
