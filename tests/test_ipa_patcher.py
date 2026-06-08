"""IPAPatcher — Mach-O byte editor + re-sign loop.

We synthesise a fake IPA by zipping a Payload/Foo.app/Foo "executable"
filled with predictable bytes, then assert that the patcher writes
the expected ARM64 instructions at the right offsets. The signing
step is monkeypatched (no ldid / codesign on CI) — we only assert
that the patcher TRIED to sign and surfaced 'no signing tool'.

Coverage:

  * return_zero_at_offset writes ``mov x0,#0; ret`` (8 bytes)
  * nop_at_offset writes N ARM64 NOPs (4 bytes each)
  * Both patches return previous_hex for rollback
  * Multiple patches in one call land all mutations
  * Offset past end of file → skipped, not crashed
  * Unknown patch name → IPAPatcherError before any work
  * Empty patches → IPAPatcherError
  * Bad zip / missing file → typed error
  * IPA without Payload/X.app/X structure → typed error
  * /v1/projects/{id}/ios/patch round-trip
  * /v1/ios/patcher/supported lists the two patches
"""

from __future__ import annotations

import asyncio
import importlib
import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mnexus.config import NexusConfig
from mnexus.runtime.ipa_patcher import (
    IPAPatcher,
    IPAPatcherError,
    SUPPORTED_PATCHES,
    _ARM64_NOP,
    _ARM64_MOV_X0_0,
    _ARM64_RET,
)


def _build_fake_ipa(tmp_path: Path, executable_payload: bytes) -> Path:
    """Construct a Payload/Foo.app/Foo IPA whose 'executable' is the
    given byte sequence — gives the test deterministic offsets to
    patch into."""
    ipa = tmp_path / "fixture.ipa"
    with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Payload/Foo.app/Foo", executable_payload)
        zf.writestr("Payload/Foo.app/Info.plist", b"<plist><dict/></plist>")
    return ipa


@pytest.fixture
def cfg(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return NexusConfig(workspace=workspace)


# ─── happy-path patches ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_return_zero_writes_the_mov_x0_zero_plus_ret_sequence(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No signing tools on PATH — patcher should still produce a result + warn.
    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)

    # Construct a Mach-O with 64 bytes of 0xAA at the start; patch
    # offset 16 (room for the 8-byte payload).
    fake_exe = b"\xaa" * 64
    ipa = _build_fake_ipa(tmp_path, fake_exe)
    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "return_zero_at_offset", "offset": "0x10"},
    ])
    assert result.patched_path is not None
    assert result.patched_path.exists()

    # Unzip the patched IPA and verify the 8 bytes at offset 16.
    with zipfile.ZipFile(result.patched_path) as zf:
        patched_exe = zf.read("Payload/Foo.app/Foo")
    assert patched_exe[16:24] == _ARM64_MOV_X0_0 + _ARM64_RET
    # And the bytes outside the patch window are untouched.
    assert patched_exe[:16] == b"\xaa" * 16
    assert patched_exe[24:] == b"\xaa" * (len(fake_exe) - 24)
    # Rollback hex echo lands in patches_applied.
    assert result.patches_applied[0]["previous_hex"] == "aa " * 8 + "aa".replace("aa", "aa") if False else True
    # More simply: it should be the old 8 bytes (0xaa) as hex.
    assert result.patches_applied[0]["previous_hex"].replace(" ", "") == "aa" * 8


@pytest.mark.asyncio
async def test_nop_at_offset_writes_count_nops(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    fake_exe = b"\xff" * 128
    ipa = _build_fake_ipa(tmp_path, fake_exe)
    # NOP-out 5 instructions = 20 bytes starting at offset 32.
    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "nop_at_offset", "offset": "0x20", "count": 5},
    ])
    with zipfile.ZipFile(result.patched_path) as zf:
        patched_exe = zf.read("Payload/Foo.app/Foo")
    assert patched_exe[32:32 + 20] == _ARM64_NOP * 5
    assert patched_exe[:32] == b"\xff" * 32
    assert patched_exe[52:] == b"\xff" * (128 - 52)


@pytest.mark.asyncio
async def test_multiple_patches_apply_in_one_pass(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    fake_exe = b"\xcc" * 256
    ipa = _build_fake_ipa(tmp_path, fake_exe)
    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "return_zero_at_offset", "offset": "0x40"},
        {"name": "nop_at_offset", "offset": "0x80", "count": 3},
    ])
    assert len(result.patches_applied) == 2
    with zipfile.ZipFile(result.patched_path) as zf:
        patched = zf.read("Payload/Foo.app/Foo")
    assert patched[0x40:0x48] == _ARM64_MOV_X0_0 + _ARM64_RET
    assert patched[0x80:0x80 + 12] == _ARM64_NOP * 3


# ─── error / edge paths ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_patch_name_raises_before_any_work(cfg, tmp_path) -> None:
    ipa = _build_fake_ipa(tmp_path, b"\x00" * 64)
    with pytest.raises(IPAPatcherError) as exc:
        await IPAPatcher(cfg).patch(ipa, [{"name": "rooted", "offset": "0x10"}])
    assert "unknown" in str(exc.value).lower() or "supported" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_empty_patch_list_raises(cfg, tmp_path) -> None:
    ipa = _build_fake_ipa(tmp_path, b"\x00" * 64)
    with pytest.raises(IPAPatcherError):
        await IPAPatcher(cfg).patch(ipa, [])


@pytest.mark.asyncio
async def test_missing_ipa_raises(cfg, tmp_path) -> None:
    with pytest.raises(IPAPatcherError):
        await IPAPatcher(cfg).patch(tmp_path / "ghost.ipa", [{"name": "nop_at_offset", "offset": 0}])


@pytest.mark.asyncio
async def test_offset_past_end_of_file_skipped(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The patch should be marked SKIPPED with a clear reason rather
    than crashing the whole batch — same belt-and-suspenders as the
    Android patcher."""
    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    ipa = _build_fake_ipa(tmp_path, b"\x00" * 16)  # only 16 bytes
    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "return_zero_at_offset", "offset": "0x100"},  # well past end
    ])
    assert not result.patches_applied
    assert len(result.patches_skipped) == 1
    assert "exceeds Mach-O size" in result.patches_skipped[0]["reason"]


@pytest.mark.asyncio
async def test_corrupt_ipa_raises(cfg, tmp_path) -> None:
    bad = tmp_path / "notazip.ipa"
    bad.write_bytes(b"this is not a zip")
    with pytest.raises(IPAPatcherError) as exc:
        await IPAPatcher(cfg).patch(bad, [{"name": "nop_at_offset", "offset": 0}])
    assert "zip" in str(exc.value).lower() or "corrupt" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_ipa_without_payload_structure_raises(cfg, tmp_path) -> None:
    """A zip that doesn't contain Payload/<X>.app/<X> — should error
    early, not produce garbage."""
    ipa = tmp_path / "bad-structure.ipa"
    with zipfile.ZipFile(ipa, "w") as zf:
        zf.writestr("README.txt", "this isn't an IPA")
    with pytest.raises(IPAPatcherError) as exc:
        await IPAPatcher(cfg).patch(ipa, [{"name": "nop_at_offset", "offset": 0}])
    assert "Payload" in str(exc.value)


# ─── signing fallbacks ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signing_uses_ldid_when_available(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mnexus.runtime.ipa_patcher.shutil.which",
        lambda name: "/usr/local/bin/ldid" if name == "ldid" else None,
    )

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_patcher.asyncio.create_subprocess_exec", _factory)

    ipa = _build_fake_ipa(tmp_path, b"\x00" * 64)
    result = await IPAPatcher(cfg).patch(ipa, [{"name": "nop_at_offset", "offset": 0, "count": 1}])
    assert result.signing_tool == "ldid"
    assert not any("unsigned" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_signing_falls_back_to_codesign(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mnexus.runtime.ipa_patcher.shutil.which",
        lambda name: "/usr/bin/codesign" if name == "codesign" else None,
    )

    async def _factory(*cmd, **kwargs):  # noqa: ARG001
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    monkeypatch.setattr("mnexus.runtime.ipa_patcher.asyncio.create_subprocess_exec", _factory)

    ipa = _build_fake_ipa(tmp_path, b"\x00" * 64)
    result = await IPAPatcher(cfg).patch(ipa, [{"name": "nop_at_offset", "offset": 0}])
    assert result.signing_tool == "codesign-adhoc"


@pytest.mark.asyncio
async def test_no_signing_tool_warns_unsigned(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    ipa = _build_fake_ipa(tmp_path, b"\x00" * 64)
    result = await IPAPatcher(cfg).patch(ipa, [{"name": "nop_at_offset", "offset": 0}])
    assert result.signing_tool is None
    assert any("unsigned" in w.lower() for w in result.warnings)


# ─── /v1/projects/{id}/ios/patch round-trip ─────────────────────────


@pytest.fixture
def ipa_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Upload a stub IPA into a Project, then test the endpoint."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)

    # Build a real IPA with a deterministic 'executable' so the patch
    # has somewhere to land.
    fake_exe = b"\xaa" * 256
    ipa_bytes_buf = io.BytesIO()
    with zipfile.ZipFile(ipa_bytes_buf, "w") as zf:
        zf.writestr("Payload/Foo.app/Foo", fake_exe)
        zf.writestr("Payload/Foo.app/Info.plist", b"<plist><dict/></plist>")
    ipa_bytes = ipa_bytes_buf.getvalue()

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/ipas/upload",
            files={"file": ("target.ipa", io.BytesIO(ipa_bytes), "application/octet-stream")},
            data={"package": "com.target.bank.test", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid


def test_endpoint_ios_patch_returns_patched_ipa(ipa_client) -> None:
    client, pid = ipa_client
    r = client.post(
        f"/v1/projects/{pid}/ios/patch",
        json={"patches": [{"name": "return_zero_at_offset", "offset": "0x10"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["patched_path"].endswith("-patched.ipa")
    assert len(body["patches_applied"]) == 1
    # Unsigned warning lands because we mocked shutil.which to return None.
    assert any("unsigned" in w.lower() for w in body["warnings"])


def test_endpoint_ios_patch_400_on_unknown_name(ipa_client) -> None:
    client, pid = ipa_client
    r = client.post(
        f"/v1/projects/{pid}/ios/patch",
        json={"patches": [{"name": "rooted", "offset": "0x0"}]},
    )
    assert r.status_code == 400


def test_endpoint_ios_patch_400_on_empty_patches(ipa_client) -> None:
    client, pid = ipa_client
    r = client.post(f"/v1/projects/{pid}/ios/patch", json={"patches": []})
    assert r.status_code == 400


def test_endpoint_ios_patch_400_on_missing_field(ipa_client) -> None:
    client, pid = ipa_client
    r = client.post(f"/v1/projects/{pid}/ios/patch", json={})
    assert r.status_code == 400


def test_endpoint_ios_patcher_supported_lists_two(ipa_client) -> None:
    client, _ = ipa_client
    body = client.get("/v1/ios/patcher/supported").json()
    names = {p["name"] for p in body["patches"]}
    assert names == set(SUPPORTED_PATCHES)
