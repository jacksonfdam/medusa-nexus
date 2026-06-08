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


# ─── VA → file offset translation ─────────────────────────────────────


def _macho_with_one_segment(vmaddr: int, fileoff: int, total_size: int, payload_offset: int, payload: bytes) -> bytes:
    """Build a minimal 64-bit Mach-O with one LC_SEGMENT_64.

    Header:
      magic 0xfeedfacf (LE) · cputype/sub/filetype/ncmds=1/sizeofcmds/flags/reserved

    Then one LC_SEGMENT_64 (cmd=0x19, cmdsize=72):
      segname=__TEXT (16 bytes), vmaddr, vmsize=total_size, fileoff,
      filesize=total_size, prot/sects/flags zeros.

    The 'executable' payload lives at file offset `fileoff + payload_offset`
    so VA = vmaddr + payload_offset translates to that file offset.
    """
    import struct

    header = struct.pack(
        "<IIIIIIII",
        0xFEEDFACF,                     # MH_MAGIC_64 little-endian
        0x0100000C,                     # CPU_TYPE_ARM64
        0,                              # cpusubtype
        2,                              # MH_EXECUTE
        1,                              # ncmds
        72,                             # sizeofcmds
        0, 0,                           # flags, reserved
    )
    segname = b"__TEXT".ljust(16, b"\x00")
    seg = (
        struct.pack("<II", 0x19, 72)                  # cmd=LC_SEGMENT_64, cmdsize=72
        + segname
        + struct.pack(
            "<QQQQ",
            vmaddr, total_size, fileoff, total_size,  # vmaddr / vmsize / fileoff / filesize
        )
        + struct.pack("<IIII", 7, 5, 0, 0)            # maxprot/initprot/nsects/flags
    )
    head_len = len(header) + len(seg)
    # Pad up to fileoff + payload_offset, then write the payload, then pad
    # to total_size.
    if fileoff + payload_offset < head_len:
        # Header is fileoff + payload_offset bytes long — collision. Bump fileoff up.
        # Caller's responsibility, but keep the assert visible:
        raise ValueError("fileoff + payload_offset can't be inside the header")
    pre_payload = b"\x00" * (fileoff + payload_offset - head_len)
    post_payload = b"\x00" * (total_size - (fileoff + payload_offset + len(payload)))
    return header + seg + pre_payload + payload + post_payload


def test_va_to_file_offset_translates_within_segment(tmp_path) -> None:
    from mnexus.runtime.ipa_patcher import _va_to_file_offset

    vmaddr = 0x100000000
    fileoff = 0x0  # segment starts at file beginning
    total_size = 0x1000
    blob = _macho_with_one_segment(vmaddr, fileoff, total_size, 0x200, b"PAYLOAD")
    macho = tmp_path / "exec"
    macho.write_bytes(blob)

    # VA pointing at the payload → file offset
    out = _va_to_file_offset(macho, vmaddr + 0x200)
    assert out == 0x200

    # VA at segment base → file offset 0
    assert _va_to_file_offset(macho, vmaddr) == 0


def test_va_to_file_offset_returns_none_outside_any_segment(tmp_path) -> None:
    from mnexus.runtime.ipa_patcher import _va_to_file_offset
    blob = _macho_with_one_segment(0x100000000, 0, 0x1000, 0x200, b"\x00")
    macho = tmp_path / "exec"
    macho.write_bytes(blob)
    # Way outside the single segment.
    assert _va_to_file_offset(macho, 0x300000000) is None


def test_va_to_file_offset_returns_none_on_non_macho(tmp_path) -> None:
    from mnexus.runtime.ipa_patcher import _va_to_file_offset
    not_macho = tmp_path / "elf-like"
    not_macho.write_bytes(b"\x7fELF" + b"\x00" * 100)
    assert _va_to_file_offset(not_macho, 0x100000000) is None


@pytest.mark.asyncio
async def test_patch_via_va_translates_then_writes_bytes(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: build an IPA whose executable is a real Mach-O,
    patch by VA, verify the bytes landed at the right file offset."""
    import zipfile

    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)

    vmaddr = 0x100000000
    payload_offset = 0x400
    blob = _macho_with_one_segment(vmaddr, 0, 0x1000, payload_offset, b"\xaa" * 32)

    ipa = tmp_path / "fixture.ipa"
    with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Payload/Foo.app/Foo", blob)
        zf.writestr("Payload/Foo.app/Info.plist", b"<plist><dict/></plist>")

    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "return_zero_at_offset", "va": hex(vmaddr + payload_offset)},
    ])
    assert result.patched_path is not None
    with zipfile.ZipFile(result.patched_path) as zf:
        patched = zf.read("Payload/Foo.app/Foo")
    # Bytes at the translated file offset should be the ret-zero sequence.
    assert patched[payload_offset:payload_offset + 8] == _ARM64_MOV_X0_0 + _ARM64_RET


# ─── dylib injection ──────────────────────────────────────────────────


def _macho_with_slack(segment_fileoff: int) -> bytes:
    """Build a Mach-O with one LC_SEGMENT_64 whose data starts at
    ``segment_fileoff`` — the gap between the existing cmds and that
    fileoff is the available slack for injection.
    """
    import struct

    header = struct.pack(
        "<IIIIIIII",
        0xFEEDFACF, 0x0100000C, 0, 2, 1, 72, 0, 0,
    )
    segname = b"__TEXT".ljust(16, b"\x00")
    seg = (
        struct.pack("<II", 0x19, 72)
        + segname
        + struct.pack("<QQQQ", 0x100000000, 0x1000, segment_fileoff, 0x800)
        + struct.pack("<IIII", 7, 5, 0, 0)
    )
    head_len = 32 + 72  # header + one LC_SEGMENT_64
    pre = b"\x00" * (segment_fileoff - head_len)
    payload = b"\xaa" * 0x800
    return header + seg + pre + payload


def test_inject_load_dylib_writes_new_command_when_slack_fits(tmp_path) -> None:
    from mnexus.runtime.ipa_patcher import _inject_load_dylib
    import struct

    # 1024-byte slack — plenty of room for the injection.
    macho = tmp_path / "exec"
    macho.write_bytes(_macho_with_slack(segment_fileoff=0x500))
    out = _inject_load_dylib(macho, "@executable_path/Frameworks/Frida.dylib")
    assert out["ok"] is True
    assert out["dylib_path"] == "@executable_path/Frameworks/Frida.dylib"
    # Read back the file and parse the header to check ncmds + sizeofcmds bumped.
    data = macho.read_bytes()
    ncmds = struct.unpack_from("<I", data, 4 + 12)[0]
    sizeofcmds = struct.unpack_from("<I", data, 4 + 16)[0]
    assert ncmds == 2  # original 1 + injected 1
    assert sizeofcmds > 72  # original 72 + injected cmdsize
    # The new command's cmd field should be LC_LOAD_DYLIB (0x0C) right
    # after the original segment cmd (header 32 + seg 72 = 104).
    new_cmd = struct.unpack_from("<I", data, 32 + 72)[0]
    assert new_cmd == 0x0C
    # Dylib path bytes should appear in the load-commands region.
    assert b"@executable_path/Frameworks/Frida.dylib\x00" in data[:0x500]


def test_inject_load_dylib_skips_when_no_slack(tmp_path) -> None:
    """If the first segment's fileoff is right after the cmds, there's
    zero slack — injection skips with a clear reason."""
    from mnexus.runtime.ipa_patcher import _inject_load_dylib

    macho = tmp_path / "exec-tight"
    macho.write_bytes(_macho_with_slack(segment_fileoff=32 + 72))  # no slack
    out = _inject_load_dylib(macho, "@executable_path/X.dylib")
    assert out["ok"] is False
    assert "slack" in out["reason"]


def test_inject_load_dylib_rejects_non_macho(tmp_path) -> None:
    from mnexus.runtime.ipa_patcher import _inject_load_dylib
    elf = tmp_path / "elf"
    elf.write_bytes(b"\x7fELF" + b"\x00" * 100)
    out = _inject_load_dylib(elf, "@executable_path/X.dylib")
    assert out["ok"] is False
    assert "64-bit little-endian" in out["reason"]


@pytest.mark.asyncio
async def test_patch_inject_load_dylib_round_trips(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: build a real IPA with a Mach-O that has slack, run
    the full patcher with inject_load_dylib, verify the rebuilt IPA
    carries the new load command."""
    import struct
    import zipfile

    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    macho_bytes = _macho_with_slack(segment_fileoff=0x500)
    ipa = tmp_path / "fixture.ipa"
    with zipfile.ZipFile(ipa, "w") as zf:
        zf.writestr("Payload/Foo.app/Foo", macho_bytes)

    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "inject_load_dylib", "dylib_path": "@executable_path/Frida.dylib"},
    ])
    assert result.patched_path is not None
    with zipfile.ZipFile(result.patched_path) as zf:
        patched = zf.read("Payload/Foo.app/Foo")
    ncmds = struct.unpack_from("<I", patched, 4 + 12)[0]
    assert ncmds == 2  # bumped from 1 to 2
    assert b"Frida.dylib" in patched


@pytest.mark.asyncio
async def test_patch_inject_load_dylib_missing_path_is_skipped(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty dylib_path → skipped (not failed) with a reason."""
    import zipfile

    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    ipa = tmp_path / "fixture.ipa"
    with zipfile.ZipFile(ipa, "w") as zf:
        zf.writestr("Payload/Foo.app/Foo", _macho_with_slack(0x500))
    result = await IPAPatcher(cfg).patch(ipa, [{"name": "inject_load_dylib"}])
    assert not result.patches_applied
    assert "dylib_path" in result.patches_skipped[0]["reason"]


@pytest.mark.asyncio
async def test_patch_via_va_skipped_when_va_outside_any_segment(cfg, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zipfile

    monkeypatch.setattr("mnexus.runtime.ipa_patcher.shutil.which", lambda name: None)
    blob = _macho_with_one_segment(0x100000000, 0, 0x1000, 0x400, b"\x00" * 16)
    ipa = tmp_path / "fixture.ipa"
    with zipfile.ZipFile(ipa, "w") as zf:
        zf.writestr("Payload/Foo.app/Foo", blob)
    result = await IPAPatcher(cfg).patch(ipa, [
        {"name": "return_zero_at_offset", "va": "0x300000000"},
    ])
    assert not result.patches_applied
    assert "not covered" in result.patches_skipped[0]["reason"]


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


def test_endpoint_ios_patcher_supported_lists_all_patches(ipa_client) -> None:
    client, _ = ipa_client
    body = client.get("/v1/ios/patcher/supported").json()
    names = {p["name"] for p in body["patches"]}
    assert names == set(SUPPORTED_PATCHES)
