"""IPADecryptor — wrapper over bagbak / frida-ios-dump.

We don't bring real iOS devices or external decryptors into CI. Tests
stub asyncio subprocess + shutil.which so the decryptor logic gets
exercised end-to-end:

  * detect() picks bagbak first, falls back to frida-ios-dump,
    returns None when neither is present
  * decrypt() builds the right command line for the picked tool
  * Output IPA gets surfaced even if the tool wrote it to a wrong
    location (the cwd-scan fallback)
  * Empty bundle_id raises a typed error
  * Tool-missing raises IPADecryptorMissing (→ 503 at the API)
  * Subprocess timeout raises IPADecryptorError with a 'past budget'
    message the API uses to pick 504
  * /v1/ios/decrypt round-trips, /v1/ios/decrypt/status reports
    availability
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnexus.config import NexusConfig
from mnexus.runtime.ipa_decryptor import (
    DecryptResult,
    IPADecryptor,
    IPADecryptorError,
    IPADecryptorMissing,
)


@pytest.fixture
def cfg(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return NexusConfig(workspace=workspace)


# ─── detect() ────────────────────────────────────────────────────────


def test_detect_picks_bagbak_when_both_present(cfg, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Preference order matters: bagbak (modern) over frida-ios-dump (legacy)."""
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: "/usr/local/bin/bagbak" if name == "bagbak" else None)
    # Also drop a fake dump.py under ~/.mnexus/tools/frida-ios-dump/.
    (tmp_path / "tools" / "frida-ios-dump").mkdir(parents=True)
    (tmp_path / "tools" / "frida-ios-dump" / "dump.py").write_text("# stub")
    out = IPADecryptor(cfg).detect()
    assert out == ("bagbak", "/usr/local/bin/bagbak")


def test_detect_falls_back_to_frida_ios_dump_when_vendored(cfg, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: None)
    tools_dir = tmp_path / "tools" / "frida-ios-dump"
    tools_dir.mkdir(parents=True)
    (tools_dir / "dump.py").write_text("# stub frida-ios-dump")
    out = IPADecryptor(cfg).detect()
    assert out is not None
    assert out[0] == "frida-ios-dump"
    assert out[1].endswith("/frida-ios-dump/dump.py")


def test_detect_returns_none_when_nothing_installed(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: None)
    assert IPADecryptor(cfg).detect() is None


# ─── decrypt() ───────────────────────────────────────────────────────


def _stub_subprocess(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"", write_ipa_at: Path | None = None):
    """Build a stub for asyncio.create_subprocess_exec. If write_ipa_at
    is provided, the stub creates that file before returning to
    simulate the decryptor materialising its output."""

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        if write_ipa_at is not None:
            write_ipa_at.parent.mkdir(parents=True, exist_ok=True)
            write_ipa_at.write_bytes(b"PK\x03\x04stub-ipa")
        proc = MagicMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    return _factory


@pytest.mark.asyncio
async def test_decrypt_runs_bagbak_with_expected_args(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    """bagbak gets called with ``bagbak <bundle_id> -o <path>``."""
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: "/usr/local/bin/bagbak" if name == "bagbak" else None)
    expected_out = cfg.workspace / "decrypted-ipas" / "com.test.app.ipa"
    captured: list[list[str]] = []

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        captured.append(list(cmd))
        expected_out.parent.mkdir(parents=True, exist_ok=True)
        expected_out.write_bytes(b"PK\x03\x04ipa")
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.asyncio.create_subprocess_exec", _factory)
    result = await IPADecryptor(cfg).decrypt("com.test.app")
    assert result.tool == "bagbak"
    assert result.ipa_path == expected_out
    cmd = captured[0]
    assert cmd[0] == "bagbak"
    assert "com.test.app" in cmd
    assert "-o" in cmd
    assert str(expected_out) in cmd


@pytest.mark.asyncio
async def test_decrypt_forwards_device_id_to_bagbak(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    """bagbak supports -d <device>; we pass it through."""
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: "/usr/local/bin/bagbak" if name == "bagbak" else None)
    expected_out = cfg.workspace / "decrypted-ipas" / "com.test.app.ipa"
    captured: list[list[str]] = []

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        captured.append(list(cmd))
        expected_out.parent.mkdir(parents=True, exist_ok=True)
        expected_out.write_bytes(b"PK\x03\x04ipa")
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.asyncio.create_subprocess_exec", _factory)
    await IPADecryptor(cfg).decrypt("com.test.app", device_id="01abcd")
    cmd = captured[0]
    assert "-d" in cmd
    assert "01abcd" in cmd


@pytest.mark.asyncio
async def test_decrypt_finds_ipa_when_tool_wrote_to_wrong_path(cfg, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Older frida-ios-dump forks ignore -o and write the IPA in cwd
    named after the app's display name. The fallback scans recent
    .ipa files and moves the right one to the canonical workspace
    location."""
    tools_dir = tmp_path / "tools" / "frida-ios-dump"
    tools_dir.mkdir(parents=True)
    (tools_dir / "dump.py").write_text("# stub")
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: None)
    misplaced = tools_dir / "DisplayName.ipa"

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        misplaced.write_bytes(b"PK\x03\x04ipa")
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok", b""))
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.asyncio.create_subprocess_exec", _factory)
    result = await IPADecryptor(cfg).decrypt("com.test.app")
    # The IPA got moved into the canonical workspace location.
    assert result.ipa_path == cfg.workspace / "decrypted-ipas" / "com.test.app.ipa"
    assert result.ipa_path.exists()
    assert any("moved" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_decrypt_raises_missing_when_no_tool_installed(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: None)
    with pytest.raises(IPADecryptorMissing) as exc:
        await IPADecryptor(cfg).decrypt("com.test.app")
    msg = str(exc.value)
    assert "bagbak" in msg
    assert "frida-ios-dump" in msg


@pytest.mark.asyncio
async def test_decrypt_empty_bundle_id_raises(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: "/usr/local/bin/bagbak" if name == "bagbak" else None)
    with pytest.raises(IPADecryptorError):
        await IPADecryptor(cfg).decrypt("   ")


@pytest.mark.asyncio
async def test_decrypt_timeout_surfaces_past_budget_message(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    """Slow tool → asyncio.TimeoutError → IPADecryptorError with the
    'past budget' phrase the API uses to pick 504."""
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: "/usr/local/bin/bagbak" if name == "bagbak" else None)

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        proc = MagicMock()
        proc.returncode = 0
        # communicate() never returns within timeout.
        async def _hang(*a, **k):  # noqa: ARG001
            await asyncio.sleep(60)
            return (b"", b"")
        proc.communicate = _hang
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.asyncio.create_subprocess_exec", _factory)
    with pytest.raises(IPADecryptorError) as exc:
        await IPADecryptor(cfg).decrypt("com.test.app", timeout_s=1)
    assert "past" in str(exc.value) and "budget" in str(exc.value)


@pytest.mark.asyncio
async def test_decrypt_raises_when_tool_produced_no_ipa(cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool exited successfully but no .ipa landed anywhere → error
    with the tail of the log so the analyst can debug."""
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: "/usr/local/bin/bagbak" if name == "bagbak" else None)

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"some output", b"no errors but no ipa either"))
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.asyncio.create_subprocess_exec", _factory)
    with pytest.raises(IPADecryptorError) as exc:
        await IPADecryptor(cfg).decrypt("com.test.app")
    assert "produced no IPA" in str(exc.value)


def test_decrypt_result_model_dump_is_json_safe(tmp_path) -> None:
    result = DecryptResult(
        tool="bagbak",
        bundle_id="com.test.app",
        ipa_path=tmp_path / "x.ipa",
        log="line one\nline two",
        duration_ms=1234,
        warnings=["moved file"],
    )
    d = result.model_dump()
    assert d["ipa_path"].endswith("x.ipa")
    import json
    json.dumps(d)  # raises on non-serializable


# ─── /v1/ios/decrypt round-trip ──────────────────────────────────────


@pytest.fixture
def ipa_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with shutil.which + subprocess stubbed to a 'bagbak
    that always succeeds and writes a stub IPA'."""
    import importlib
    from fastapi.testclient import TestClient

    fake_bagbak_path = tmp_path / "fake-bagbak"
    fake_bagbak_path.write_text("# stub binary")

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    monkeypatch.setattr(
        "mnexus.runtime.ipa_decryptor.shutil.which",
        lambda name: str(fake_bagbak_path) if name == "bagbak" else None,
    )

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        # Find the -o argument and write a stub IPA there.
        for i, a in enumerate(cmd):
            if a == "-o" and i + 1 < len(cmd):
                Path(cmd[i + 1]).parent.mkdir(parents=True, exist_ok=True)
                Path(cmd[i + 1]).write_bytes(b"PK\x03\x04stub-ipa")
                break
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"decrypted ok", b""))
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.asyncio.create_subprocess_exec", _factory)

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def test_endpoint_decrypt_returns_ipa_path(ipa_client) -> None:
    r = ipa_client.post("/v1/ios/decrypt", data={"bundle_id": "com.test.app", "ingest": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool"] == "bagbak"
    assert body["ipa_path"].endswith("/com.test.app.ipa")
    assert body["duration_ms"] >= 0


def test_endpoint_decrypt_503_when_no_tool(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import importlib
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setattr("mnexus.runtime.ipa_decryptor.shutil.which", lambda name: None)

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post("/v1/ios/decrypt", data={"bundle_id": "com.x.y", "ingest": "false"})
        assert r.status_code == 503
        assert "bagbak" in r.text or "frida-ios-dump" in r.text


def test_endpoint_decrypt_status_reports_availability(ipa_client) -> None:
    body = ipa_client.get("/v1/ios/decrypt/status").json()
    assert body["available"] is True
    assert body["tool"] == "bagbak"
    assert body["install_hint"] is None
