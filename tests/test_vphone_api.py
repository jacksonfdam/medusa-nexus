"""`/v1/vphones/*` — API smoke tests.

These run without a real super-tart binary. Without `MNEXUS_TART_BIN` set
and no `tart` on PATH, every endpoint exits cleanly: graceful 200 with
empty data for read-only calls, 503 for lifecycle commands, 422 for
missing form fields, 501 for screenshot when no VNC client is installed.
This suite locks in those contracts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A TestClient with no super-tart binary configured anywhere."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.delenv("MNEXUS_TART_BIN", raising=False)
    # Point HOME at an empty dir so the ~/.mnexus/tools/vphone/bin/tart
    # fallback also resolves to nothing.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    import importlib

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


# ─── read-only endpoints — clean defaults ──────────────────────────────

def test_vphones_list_returns_empty_array_when_unconfigured(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/vphones")
    assert r.status_code == 200
    assert r.json() == []


def test_vphones_info_returns_exists_false_when_unconfigured(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/vphones/whatever")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "whatever"
    assert body["exists"] is False
    assert "tart binary not configured" in body["reason"].lower()


# ─── lifecycle — 503 when binary is absent ─────────────────────────────

def test_vphones_start_503_when_unconfigured(isolated_client: TestClient) -> None:
    r = isolated_client.post("/v1/vphones/whatever/start", data={"extra_args": ""})
    assert r.status_code == 503
    assert "tart binary not configured" in r.text.lower()


def test_vphones_stop_503_when_unconfigured(isolated_client: TestClient) -> None:
    r = isolated_client.post("/v1/vphones/whatever/stop")
    assert r.status_code == 503


# ─── ssh — empty command rejected, real SSH attempt records audit log ──

def test_vphones_ssh_rejects_empty_command(isolated_client: TestClient) -> None:
    """Empty command is rejected — either at FastAPI's form validation (422)
    or by our explicit `if not command.strip()` guard (400). Both are
    correct behaviour."""
    r = isolated_client.post("/v1/vphones/whatever/ssh", data={"command": ""})
    assert r.status_code in (400, 422)
    # When FastAPI rejects at parse time the body mentions `command`;
    # when our explicit check fires the message says `empty`.
    body_lower = r.text.lower()
    assert "command" in body_lower or "empty" in body_lower


def test_vphones_ssh_records_attempt_in_audit_log(isolated_client: TestClient) -> None:
    """Even a *failed* SSH (no real VM listening on :2222) must show up in
    /v1/adb/log with transport='vphone' — that's the whole point of the
    unified audit trail."""
    r = isolated_client.post(
        "/v1/vphones/lab-vm/ssh",
        data={"command": "uname -a"},
    )
    # 200 with non-zero exit, OR 500 if `ssh` itself isn't on PATH —
    # both prove the engine ran. Either way the audit log records it.
    assert r.status_code in (200, 500)

    log = isolated_client.get("/v1/adb/log").json()
    vphone_rows = [e for e in log["log"] if e.get("transport") == "vphone"]
    assert vphone_rows, "expected at least one vphone audit-log row"
    last = vphone_rows[-1]
    # Note carries the VM name so the Command Log can group by target.
    assert "lab-vm" in last["note"]
    # The full ssh argv is recorded — including the StrictHostKeyChecking flags
    # (research-mode tradeoff is observable, not silent).
    assert "StrictHostKeyChecking=no" in last["command"]


# ─── screenshot — 501 envelope when no VNC client on PATH ──────────────

def test_vphones_screenshot_501_with_install_hint_when_no_vnc_client(
    isolated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The screenshot path looks for vncsnapshot or vncdotool. In the
    sandbox neither is installed, so the API returns 501 with a hint."""
    # Defensive: clear PATH so even if a CI image had vncsnapshot, we get
    # the unconfigured branch.
    monkeypatch.setenv("PATH", "/nowhere")

    r = isolated_client.post("/v1/vphones/whatever/screenshot")
    assert r.status_code == 501
    detail = r.json().get("detail", {})
    # FastAPI wraps dict details under `detail` directly.
    assert detail.get("ok") is False
    assert "vncsnapshot" in detail.get("hint", "")


# ─── form-field validation — 422 instead of crashing ───────────────────

def test_vphones_ssh_missing_command_returns_422(isolated_client: TestClient) -> None:
    """No `command` form field → FastAPI's standard 422, not a 500."""
    r = isolated_client.post("/v1/vphones/whatever/ssh")
    assert r.status_code == 422
    assert "command" in r.text


# ─── audit-log unification — adb + vphone share /v1/adb/log ────────────

def test_audit_log_returns_transport_field_on_every_row(isolated_client: TestClient) -> None:
    """After a vphone SSH attempt, the ADB log should contain at least one
    vphone row — and every row (adb-flavoured back-compat ones too) should
    have a `transport` field."""
    isolated_client.post("/v1/vphones/lab-vm/ssh", data={"command": "id"})
    log = isolated_client.get("/v1/adb/log").json()
    assert log["log"], "expected at least the ssh attempt to be logged"
    assert all("transport" in row for row in log["log"])
    assert any(row["transport"] == "vphone" for row in log["log"])
