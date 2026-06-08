"""Memory Inspector — FridaSession.mem facade + four /memory endpoints.

The tooling JS executes inside the target process and can't be tested
in isolation. We stub the ``script.exports_sync`` proxy with canned
returns so the Python facade + the API surface get end-to-end coverage
without a real Frida runtime.

Coverage:
  * MemoryOps.modules / scan / read / write all dispatch to the right
    rpc.exports method with the right kwargs
  * scan supports the optional ``module`` scope
  * write returns the previous bytes (rollback affordance)
  * POST /memory/scan, /read, /write + GET /memory/modules round-trip
  * 404 when the session_id is unknown
  * 503 when the session exists but tooling failed to load (mem=None)
  * 400 on missing body fields
"""

from __future__ import annotations

import asyncio
import importlib
import io
from types import SimpleNamespace

import pytest


# ─── unit: MemoryOps facade ──────────────────────────────────────────


class _FakeExportsSync:
    """Stand-in for Frida's ``script.exports_sync`` proxy.

    Records every call as ``(method_name, args, kwargs)`` so the test
    can assert dispatch order. Each method returns a deterministic dict.
    """
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def mem_modules(self):
        self.calls.append(("mem_modules", (), {}))
        return [
            {"name": "Bank", "base": "0x1000", "size": 65536, "path": "/var/Applications/Bank.app/Bank"},
            {"name": "Foundation", "base": "0xff0000", "size": 100000, "path": "/.../Foundation"},
        ]

    def mem_scan(self, pattern, opts):
        self.calls.append(("mem_scan", (pattern,), dict(opts or {})))
        return {
            "results": [{"address": "0x12340", "size": 8, "range_base": "0x12000", "range_size": 4096, "range_protection": "rw-"}],
            "truncated": False,
            "ranges_scanned": 12,
        }

    def mem_read(self, address, size):
        self.calls.append(("mem_read", (address, size), {}))
        return {"address": address, "size": size, "hex": "65 79 4a 68"}

    def mem_write(self, address, hex_bytes):
        self.calls.append(("mem_write", (address, hex_bytes), {}))
        return {"written": len(hex_bytes.split()), "address": address, "previous_hex": "00 11 22 33"}


def test_memory_ops_modules_calls_rpc(tmp_path) -> None:
    from mnexus.runtime.memory_ops import MemoryOps
    fake_handle = SimpleNamespace(exports_sync=_FakeExportsSync())
    out = asyncio.new_event_loop().run_until_complete(MemoryOps(fake_handle).modules())
    assert isinstance(out, list)
    assert out[0]["name"] == "Bank"
    assert fake_handle.exports_sync.calls == [("mem_modules", (), {})]


def test_memory_ops_scan_passes_module_and_max_results() -> None:
    from mnexus.runtime.memory_ops import MemoryOps
    fake_handle = SimpleNamespace(exports_sync=_FakeExportsSync())
    out = asyncio.new_event_loop().run_until_complete(
        MemoryOps(fake_handle).scan("65 79 4a 68", module="Bank", max_results=50)
    )
    assert out["results"][0]["address"] == "0x12340"
    method, args, opts = fake_handle.exports_sync.calls[0]
    assert method == "mem_scan"
    assert args == ("65 79 4a 68",)
    assert opts == {"module": "Bank", "max_results": 50}


def test_memory_ops_scan_passes_none_module_when_unscoped() -> None:
    from mnexus.runtime.memory_ops import MemoryOps
    fake_handle = SimpleNamespace(exports_sync=_FakeExportsSync())
    asyncio.new_event_loop().run_until_complete(MemoryOps(fake_handle).scan("aa bb"))
    _, _, opts = fake_handle.exports_sync.calls[0]
    assert opts == {"module": None, "max_results": 100}


def test_memory_ops_read_passes_address_and_size_as_args() -> None:
    from mnexus.runtime.memory_ops import MemoryOps
    fake_handle = SimpleNamespace(exports_sync=_FakeExportsSync())
    out = asyncio.new_event_loop().run_until_complete(
        MemoryOps(fake_handle).read("0x12340", 32)
    )
    assert out["hex"] == "65 79 4a 68"
    method, args, _ = fake_handle.exports_sync.calls[0]
    assert method == "mem_read"
    assert args == ("0x12340", 32)


def test_memory_ops_write_surfaces_previous_bytes() -> None:
    from mnexus.runtime.memory_ops import MemoryOps
    fake_handle = SimpleNamespace(exports_sync=_FakeExportsSync())
    out = asyncio.new_event_loop().run_until_complete(
        MemoryOps(fake_handle).write("0x12340", "65 79 4a 68")
    )
    # The rollback affordance — previous_hex is what the analyst overwrote.
    assert out["previous_hex"] == "00 11 22 33"
    assert out["written"] == 4
    method, args, _ = fake_handle.exports_sync.calls[0]
    assert method == "mem_write"
    assert args == ("0x12340", "65 79 4a 68")


# ─── endpoint round-trip ─────────────────────────────────────────────


@pytest.fixture
def mem_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a session pre-seeded into the registry. The
    session's ``mem`` is the stub MemoryOps from above so the four
    endpoints round-trip through actual HTTP."""
    from mnexus.runtime import frida_session as fs
    from mnexus.runtime.memory_ops import MemoryOps

    # Wire a session into the registry — no real device, no spawn.
    # Build it by hand so the test isn't coupled to FridaSession.start().
    fs.session_registry.clear()
    sess = fs.FridaSession(project_id="PRJ-PIDX", package="com.bank.app")
    sess.state = "attached"
    sess.session_id = "sid-mem-test"
    sess.mem = MemoryOps(SimpleNamespace(exports_sync=_FakeExportsSync()))
    fs.session_registry[sess.session_id] = sess

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    from fastapi.testclient import TestClient
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    # Reload reset the registry; re-seed.
    fs.session_registry[sess.session_id] = sess
    with TestClient(api_main.app) as c:
        yield c, sess.session_id


def test_endpoint_memory_modules_returns_list(mem_client) -> None:
    client, sid = mem_client
    r = client.get(f"/v1/dynamic/sessions/{sid}/memory/modules")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "modules" in body
    assert body["modules"][0]["name"] == "Bank"


def test_endpoint_memory_scan_passes_options(mem_client) -> None:
    client, sid = mem_client
    r = client.post(
        f"/v1/dynamic/sessions/{sid}/memory/scan",
        json={"pattern": "65 79 4a 68", "module": "Bank", "max_results": 20},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"][0]["address"] == "0x12340"


def test_endpoint_memory_read_round_trips(mem_client) -> None:
    client, sid = mem_client
    r = client.post(
        f"/v1/dynamic/sessions/{sid}/memory/read",
        json={"address": "0x12340", "size": 32},
    )
    assert r.status_code == 200
    assert r.json()["hex"] == "65 79 4a 68"


def test_endpoint_memory_write_returns_previous_bytes(mem_client) -> None:
    """The token-swap workflow — previous_hex is the rollback the analyst
    keeps in case the app crashes."""
    client, sid = mem_client
    r = client.post(
        f"/v1/dynamic/sessions/{sid}/memory/write",
        json={"address": "0x12340", "hex": "65 79 4a 68"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["previous_hex"] == "00 11 22 33"
    assert body["written"] == 4


def test_endpoint_404_on_unknown_session(mem_client) -> None:
    client, _ = mem_client
    r = client.post("/v1/dynamic/sessions/ghost/memory/scan", json={"pattern": "aa"})
    assert r.status_code == 404


def test_endpoint_503_when_tooling_unavailable(mem_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the tooling script failed to load (mem=None), every endpoint
    returns 503 with an actionable message instead of crashing."""
    from mnexus.runtime import session_registry
    client, sid = mem_client
    session_registry[sid].mem = None
    r = client.post(
        f"/v1/dynamic/sessions/{sid}/memory/scan",
        json={"pattern": "aa"},
    )
    assert r.status_code == 503
    assert "tooling unavailable" in r.text.lower()


def test_endpoint_400_on_missing_scan_pattern(mem_client) -> None:
    client, sid = mem_client
    r = client.post(f"/v1/dynamic/sessions/{sid}/memory/scan", json={"max_results": 10})
    assert r.status_code == 400
    assert "pattern" in r.text.lower()


def test_endpoint_400_on_missing_write_address(mem_client) -> None:
    client, sid = mem_client
    r = client.post(f"/v1/dynamic/sessions/{sid}/memory/write", json={"hex": "aa bb"})
    assert r.status_code == 400


def test_tooling_script_source_exposes_four_rpc_methods() -> None:
    """Smoke test the JS source so a refactor that removes one of the
    four methods will fail loudly here instead of at session start."""
    from mnexus.runtime.memory_ops import TOOLING_SCRIPT_SOURCE
    for name in ("memScan", "memRead", "memWrite", "memModules"):
        assert name in TOOLING_SCRIPT_SOURCE, f"{name} missing from rpc.exports"
    assert "rpc.exports" in TOOLING_SCRIPT_SOURCE
