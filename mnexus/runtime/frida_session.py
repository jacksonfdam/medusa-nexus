"""``FridaSession`` — the actual cable between Nexus and Frida.

Everything dynamic in this platform used to be decorative: the UI had
a console, the hook generator produced scripts, the SSL Map screen
polled for ``ssl_pin`` events that nobody emitted. The cable that
closes that loop lives here.

Design highlights
-----------------

* **Optional dep, no hard fail.** ``import frida`` succeeds only when
  the user opted into ``pip install frida``; we hide that behind
  ``FRIDA_AVAILABLE`` and raise ``FridaNotInstalled`` at start-time
  instead of import-time so the rest of the platform keeps working.

* **Sync → async bridge.** Frida's API is callback-based and runs
  message dispatch on its own thread. We translate that into an
  ``asyncio.Queue`` per session via
  ``loop.call_soon_threadsafe(queue.put_nowait, …)``, so the SSE
  endpoint can ``await queue.get()`` without polling.

* **Two consumers per event.** Every ``send({...})`` from the JS hook
  is fanned out to (a) the in-memory queue (SSE streams) and (b) the
  ``dynamic_events`` SQLite table (durable history → polling clients,
  SSL Map's 60-second window, future audit log).

* **Session lifecycle:** ``start()`` resolves the device, spawns OR
  attaches, loads N scripts, registers ``on_message`` for each, then
  resumes the PID if we spawned. ``stop()`` unloads scripts, detaches,
  kills the PID we own. ``state`` reflects current status for the UI.

* **Registry:** ``session_registry`` is a process-local dict — sessions
  don't survive uvicorn restarts. That's fine; the analyst restarts the
  session anyway after a crash + reload.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# Optional dep — frida ships as a C extension, not every install needs it.
try:
    import frida  # type: ignore[import-untyped]
    FRIDA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when the dep is missing
    frida = None  # type: ignore[assignment]
    FRIDA_AVAILABLE = False


class FridaSessionError(RuntimeError):
    """Base class for all session lifecycle failures."""


class FridaNotInstalled(FridaSessionError):
    """``import frida`` failed — caller should hint at ``pip install frida``."""


class NoDeviceError(FridaSessionError):
    """``frida.get_device_manager()`` returned no USB device."""


@dataclass
class LoadedScript:
    """One running Frida script + its frida.Script handle."""
    name: str
    source: str
    handle: Any = None  # frida.Script (kept loose because frida types aren't pep-561)


@dataclass
class FridaSession:
    """One Frida attach against one Android package, hosting N scripts.

    ``session_id`` is the short opaque token the UI uses. ``loop`` is
    captured at start time so the Frida message thread can hop back
    into the asyncio event loop safely.

    Instances are managed by ``session_registry``; don't construct
    them directly — call ``FridaSession.start(...)`` and let the
    classmethod handle the device resolution.
    """

    project_id: str
    package: str
    device_id: str | None = None
    spawn: bool = True

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    state: str = "init"  # init | attaching | attached | detached | crashed
    started_at: float = field(default_factory=time.time)
    pid: int | None = None
    error: str | None = None
    scripts: list[LoadedScript] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    # Subscribers — every event is fanned out to each callback. The
    # SSE endpoint registers one that puts onto an asyncio.Queue; the
    # persistence sink is registered separately by the API layer.
    _listeners: list[Callable[[dict[str, Any]], None]] = field(default_factory=list)

    _device: Any = None       # frida.Device — we hold this to detach cleanly
    _session: Any = None      # frida.Session
    _own_pid: bool = False    # True iff we spawned the process (must kill on stop)
    _loop: asyncio.AbstractEventLoop | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ─── public API ──────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        *,
        project_id: str,
        package: str,
        scripts: list[tuple[str, str]],
        device_id: str | None = None,
        spawn: bool = True,
    ) -> FridaSession:
        """Resolve the device, spawn/attach, load every script, resume.

        ``scripts`` is a list of ``(name, source)`` pairs. The names
        round-trip into the session log + the per-event ``source_script``
        field so the UI can attribute events to the recipe that emitted
        them.

        Raises:
          * ``FridaNotInstalled`` — ``import frida`` failed.
          * ``NoDeviceError``    — no USB device matched.
          * ``FridaSessionError`` for anything else (spawn refused,
            script syntax error, attach denied). The original Frida
            exception is chained.
        """
        if not FRIDA_AVAILABLE:
            raise FridaNotInstalled(
                "frida not installed — `pip install frida` (already shipped as a "
                "test dep; missing in prod means CI dropped it)."
            )

        session = cls(project_id=project_id, package=package, device_id=device_id, spawn=spawn)
        session._loop = asyncio.get_running_loop()
        session.state = "attaching"
        session._stamp(channel="nexus", line=f"[NEXUS] resolving device · spawn={spawn}")

        # Frida's API is sync + threading-friendly; offload to the default
        # executor so we don't block the event loop on USB enumeration.
        try:
            await asyncio.to_thread(session._attach_sync, scripts)
        except FridaSessionError:
            session.state = "crashed"
            raise
        except Exception as exc:  # noqa: BLE001 — frida exceptions aren't a single class
            session.state = "crashed"
            session.error = f"{exc.__class__.__name__}: {exc}"
            session._stamp(channel="nexus", line=f"[NEXUS][ERR] {session.error}")
            raise FridaSessionError(session.error) from exc

        session.state = "attached"
        session._stamp(
            channel="nexus",
            line=f"[NEXUS] session active · pid={session.pid} · {len(session.scripts)} script(s) loaded",
        )
        session_registry[session.session_id] = session
        return session

    async def stop(self) -> None:
        """Unload scripts, detach, kill the spawned PID if we own it.

        Safe to call multiple times; idempotent after the first call
        flips the state to ``detached``.
        """
        if self.state in ("detached", "crashed"):
            return
        try:
            await asyncio.to_thread(self._detach_sync)
        except Exception as exc:  # noqa: BLE001
            log.warning("frida detach failed: %s", exc)
            self.error = f"{exc.__class__.__name__}: {exc}"
        self.state = "detached"
        self._stamp(channel="nexus", line="[NEXUS] detached cleanly")

    def add_listener(self, fn: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to live events. Returns an unsubscribe callable.

        Listeners are called from the Frida message thread; if you need
        asyncio semantics, the listener should ``call_soon_threadsafe``
        onto the captured event loop itself.
        """
        with self._lock:
            self._listeners.append(fn)

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(fn)
                except ValueError:
                    pass

        return _unsubscribe

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe summary the API returns on start/stop + the
        polling /dynamic/events endpoint."""
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "package": self.package,
            "state": self.state,
            "status": self.state,  # legacy alias the SPA still reads
            "started_at": self.started_at,
            "pid": self.pid,
            "device": self.device_id,
            "scripts": [s.name for s in self.scripts],
            "error": self.error,
            "log": list(self.log[-100:]),  # cap so the response stays bounded
        }

    # ─── internals ───────────────────────────────────────────────────

    def _attach_sync(self, scripts: list[tuple[str, str]]) -> None:
        """Run on the asyncio executor thread — blocking Frida calls."""
        assert frida is not None  # FRIDA_AVAILABLE guard upstream
        manager = frida.get_device_manager()
        # Two ways to find the device: explicit serial, or first USB.
        if self.device_id:
            try:
                self._device = manager.get_device(self.device_id, timeout=2)
            except Exception as exc:  # noqa: BLE001
                raise NoDeviceError(f"frida device '{self.device_id}' not found: {exc}") from exc
        else:
            try:
                self._device = manager.get_usb_device(timeout=2)
            except Exception as exc:  # noqa: BLE001
                raise NoDeviceError(
                    "no USB device — plug a phone, authorise USB debugging, "
                    "and make sure frida-server is running."
                ) from exc
        self.device_id = self._device.id

        # Spawn or attach. Spawn is more reliable for early-injection hooks
        # (SSL pinning bypass needs to fire before the app loads OkHttp), so
        # it's the default; attach= for when the analyst wants to hook a
        # session that's already running.
        if self.spawn:
            try:
                self.pid = self._device.spawn([self.package])
                self._own_pid = True
            except Exception as exc:  # noqa: BLE001
                raise FridaSessionError(
                    f"spawn({self.package}) failed: {exc.__class__.__name__}: {exc}"
                ) from exc
            self._session = self._device.attach(self.pid)
        else:
            try:
                self.pid = self._device.get_process(self.package).pid
            except Exception as exc:  # noqa: BLE001
                raise FridaSessionError(
                    f"attach({self.package}) failed — is the app running? "
                    f"{exc.__class__.__name__}: {exc}"
                ) from exc
            self._session = self._device.attach(self.pid)

        # Load every script the caller asked for. Each one gets its own
        # on_message handler closure that tags events with the source name.
        for name, source in scripts:
            handle = self._session.create_script(source)
            handle.on("message", self._make_on_message(name))
            handle.load()
            self.scripts.append(LoadedScript(name=name, source=source, handle=handle))
            self._stamp(channel="nexus", line=f"[NEXUS] loaded script · {name}")

        if self._own_pid:
            self._device.resume(self.pid)

    def _detach_sync(self) -> None:
        """Run on the executor thread — Frida unload/detach calls."""
        for s in self.scripts:
            try:
                s.handle.unload()
            except Exception as exc:  # noqa: BLE001
                log.debug("script unload failed (%s): %s", s.name, exc)
        if self._session is not None:
            try:
                self._session.detach()
            except Exception as exc:  # noqa: BLE001
                log.debug("session detach failed: %s", exc)
        if self._own_pid and self.pid and self._device is not None:
            try:
                self._device.kill(self.pid)
            except Exception as exc:  # noqa: BLE001
                log.debug("device kill failed: %s", exc)

    def _make_on_message(self, source_script: str):
        """Closure that catches every ``send()`` from the named script.

        Frida calls this from its message thread; we never block. The
        registered listeners are responsible for thread-safe hand-off
        to their own consumer (the SSE listener calls
        ``call_soon_threadsafe`` onto the captured event loop).
        """
        def handler(message: dict[str, Any], data: bytes | None) -> None:  # noqa: ARG001
            try:
                payload = self._unpack_message(message)
                event = {
                    "ts": time.time(),
                    "channel": payload.get("channel") or message.get("type", "frida"),
                    "source_script": source_script,
                    "payload": payload,
                }
                # Append to in-memory log for the to_dict() snapshot.
                self.log.append({
                    "ts": event["ts"],
                    "channel": event["channel"],
                    "line": _stringify_line(event),
                })
                with self._lock:
                    listeners = list(self._listeners)
                for fn in listeners:
                    try:
                        fn(event)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("frida listener raised: %s", exc)
            except Exception as exc:  # noqa: BLE001 — never let a bad message kill the thread
                log.warning("on_message failed: %s", exc)

        return handler

    def _unpack_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Frida wraps ``send({...})`` payloads as ``{type:'send', payload:{...}}``.

        Errors arrive as ``{type:'error', description, stack, fileName, lineNumber}``;
        we surface those as ``channel='error'`` so the UI can paint them.
        """
        kind = message.get("type")
        if kind == "send":
            inner = message.get("payload")
            if isinstance(inner, dict):
                return inner
            return {"channel": "raw", "value": inner}
        if kind == "error":
            return {
                "channel": "error",
                "description": message.get("description"),
                "stack": message.get("stack"),
                "file": message.get("fileName"),
                "line": message.get("lineNumber"),
            }
        return {"channel": kind or "frida", "raw": message}

    def _stamp(self, *, channel: str, line: str) -> None:
        """Push a synthetic log line + fan out to listeners as a
        nexus-channel event so SSE consumers see the lifecycle too."""
        ts = time.time()
        self.log.append({"ts": ts, "channel": channel, "line": line})
        event = {"ts": ts, "channel": channel, "source_script": None, "payload": {"line": line}}
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception as exc:  # noqa: BLE001
                log.debug("nexus stamp listener raised: %s", exc)


def _stringify_line(event: dict[str, Any]) -> str:
    """Best-effort one-liner for the in-memory log shown in /dynamic/events.

    Stays terse so a flood of ssl_pin events doesn't blow up the response.
    """
    channel = (event.get("channel") or "?").upper()
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return f"[{channel}] {payload!r}"
    # Cherry-pick fields the UI cares about per channel.
    if channel == "SSL_PIN":
        return (
            f"[SSL_PIN] {payload.get('host', '?')} · {payload.get('lib', '?')} "
            f"→ {payload.get('outcome', '?')}"
        )
    if channel == "NEXUS":
        return str(payload.get("line", ""))
    if channel == "ERROR":
        return f"[ERROR] {payload.get('description', '?')}"
    # Generic — print the fields succinctly.
    parts = " ".join(f"{k}={v}" for k, v in payload.items() if k != "channel")
    return f"[{channel}] {parts}"


# Process-local registry. Sessions die with the uvicorn worker — the
# analyst restarts them via /dynamic/start after a reload. We don't try
# to persist live frida.Session handles across restarts; a stored
# 'session was alive at exit' record would be misleading.
session_registry: dict[str, FridaSession] = {}
