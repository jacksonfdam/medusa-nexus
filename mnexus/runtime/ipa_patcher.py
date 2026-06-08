"""IPAPatcher — Mach-O byte editor + re-sign loop (Bloco 1).

Analogue of ``APKPatcher`` for iOS. Where Android lets you decode →
mutate AndroidManifest.xml → repack → re-sign, iOS forces you down
to the binary level: the analyst finds an address in Ghidra/Hopper
and wants to overwrite a few bytes to neutralise a check.

Two patches in this iteration:

  * ``nop_at_offset``           Write ARM64 NOPs (4 bytes each) at a
                                file offset for N instructions. Use
                                this to wipe a call to an anti-Frida
                                check or a sandbox-escape probe.

  * ``return_zero_at_offset``   Write ``mov x0, #0 ; ret`` (8 bytes)
                                so the function returns false. The
                                canonical 'disable_jailbreak_check'
                                pattern from the talk.

Patch is keyed by **file offset**, not virtual address — the analyst
reads the offset off Ghidra's "Offset" column directly. We don't
parse load commands or do RVA translation in this iteration; that's
worth a follow-up but the file-offset form is simpler and what every
disassembler shows by default.

Re-signing tries, in order:
  1. ``ldid -S`` (Saurik's tool — common on JB devices, no cert needed)
  2. ``codesign --force --sign -`` (Apple's tool — ad-hoc signature,
     accepted by JB devices with AMFI patches)

When neither is on PATH, we ship the patched IPA UNSIGNED and warn:
the analyst can sign manually with a developer cert.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


SUPPORTED_PATCHES = ("nop_at_offset", "return_zero_at_offset", "inject_load_dylib")


# ARM64 instruction encodings, little-endian:
#   nop                 = 0x1f2003d5  (HEX: 1f 20 03 d5)
#   mov x0, #0          = 0x00008052  (HEX: 00 00 80 52)
#     Actually mov x0, #0 with sf=1 (64-bit) is encoded as
#     0xd2800000 (HEX: 00 00 80 d2). Verified by `clang -c -o /tmp/x.o
#     -arch arm64 -x assembler <<<'mov x0, #0'; otool -tv /tmp/x.o`.
#   ret                 = 0xd65f03c0  (HEX: c0 03 5f d6)
_ARM64_NOP = bytes.fromhex("1f2003d5")
_ARM64_MOV_X0_0 = bytes.fromhex("000080d2")
_ARM64_RET = bytes.fromhex("c0035fd6")


class IPAPatcherError(RuntimeError):
    """Raised when a patch can't be applied — malformed IPA, missing
    Mach-O, offset past end of file."""


@dataclass
class IPAPatchResult:
    ipa_path: Path
    patched_path: Path | None
    patches_applied: list[dict] = field(default_factory=list)
    patches_skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    signing_tool: str | None = None
    preview: bool = False

    def model_dump(self) -> dict:
        return {
            "ipa_path":         str(self.ipa_path),
            "patched_path":     str(self.patched_path) if self.patched_path else None,
            "patches_applied":  list(self.patches_applied),
            "patches_skipped":  list(self.patches_skipped),
            "warnings":         list(self.warnings),
            "signing_tool":     self.signing_tool,
            "preview":          self.preview,
        }


class IPAPatcher:
    """Stateless — instantiate per request."""

    def __init__(self, config) -> None:  # type: ignore[no-untyped-def]
        self.config = config

    # ─── public API ──────────────────────────────────────────────────

    async def patch(
        self,
        ipa_path: Path,
        patches: Iterable[dict],
        *,
        out_dir: Path | None = None,
    ) -> IPAPatchResult:
        """Apply ``patches`` to the main Mach-O inside ``ipa_path``.

        Each patch dict shape:
          {"name": "nop_at_offset", "offset": "0x100123456", "count": 1}
          {"name": "return_zero_at_offset", "offset": "0x100123456"}

        Both ``offset`` forms accepted: hex ('0x…') or decimal.

        Returns the patched IPA path + per-patch outcomes + the signing
        tool used. On a server without unzip/zip/ldid/codesign the
        result is still meaningful (preview=true for the most extreme
        case where we can't even open the IPA — but unzip is in
        Python's stdlib so that branch only fires for malformed IPAs).
        """
        patch_list = list(patches)
        if not patch_list:
            raise IPAPatcherError("at least one patch is required")
        # Validate names up front so a typo aborts before the IPA gets
        # unzipped — same pattern APKPatcher uses.
        unknown = [p for p in patch_list if p.get("name") not in SUPPORTED_PATCHES]
        if unknown:
            raise IPAPatcherError(
                f"unknown patches: {[p.get('name') for p in unknown]!r} — "
                f"supported: {SUPPORTED_PATCHES}"
            )
        if not ipa_path.exists():
            raise IPAPatcherError(f"ipa does not exist: {ipa_path}")

        out_dir = out_dir or (Path(self.config.workspace) / "patched-ipas")
        out_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="mnexus-ipa-patch-") as tmp:
            work = Path(tmp)
            extracted = work / "extracted"
            extracted.mkdir()
            try:
                with zipfile.ZipFile(ipa_path) as zf:
                    zf.extractall(extracted)
            except zipfile.BadZipFile as exc:
                raise IPAPatcherError(f"not a zip / corrupt IPA: {exc}") from exc

            mach_o = _find_main_macho(extracted)
            if mach_o is None:
                raise IPAPatcherError(
                    "couldn't locate Payload/<App>.app/<Executable> in the IPA"
                )

            applied: list[dict] = []
            skipped: list[dict] = []
            for p in patch_list:
                outcome = _apply_patch(p, mach_o)
                if outcome.get("ok"):
                    applied.append({"name": p["name"], "offset": p.get("offset"), **outcome})
                else:
                    skipped.append({"name": p["name"], "offset": p.get("offset"), "reason": outcome.get("reason", "?")})

            warnings: list[str] = []
            signing_tool: str | None = None
            if applied:
                signing_tool = await self._sign_or_warn(mach_o, warnings)

            patched = out_dir / f"{ipa_path.stem}-patched.ipa"
            _repack_ipa(extracted, patched)

        return IPAPatchResult(
            ipa_path=ipa_path,
            patched_path=patched if applied else None,
            patches_applied=applied,
            patches_skipped=skipped,
            warnings=warnings,
            signing_tool=signing_tool,
        )

    # ─── internals ───────────────────────────────────────────────────

    async def _sign_or_warn(self, mach_o: Path, warnings: list[str]) -> str | None:
        """Try ldid first, codesign second. Returns the tool name used
        or None when both are missing."""
        ldid = shutil.which("ldid")
        if ldid is not None:
            rc = await self._run([ldid, "-S", str(mach_o)])
            if rc == 0:
                return "ldid"
            warnings.append("ldid returned non-zero; trying codesign…")

        codesign = shutil.which("codesign")
        if codesign is not None:
            rc = await self._run([codesign, "--force", "--sign", "-", str(mach_o)])
            if rc == 0:
                return "codesign-adhoc"
            warnings.append("codesign returned non-zero; APK ships unsigned")

        if ldid is None and codesign is None:
            warnings.append(
                "no signing tool on PATH (ldid / codesign). "
                "Patched IPA ships unsigned; you'll have to sign manually "
                "before installing on a non-JB device."
            )
        return None

    async def _run(self, cmd: list[str]) -> int:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning(
                "ipa-patcher subprocess failed: %s\nstdout: %s\nstderr: %s",
                " ".join(cmd),
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        return proc.returncode or 0


# ─── module-level helpers ────────────────────────────────────────────


def _inject_load_dylib(macho_path: Path, dylib_path: str) -> dict:
    """Add an ``LC_LOAD_DYLIB`` load command pointing at ``dylib_path``.

    Native implementation — no optool / insert_dylib dependency. Walks
    the header, finds slack between ``sizeofcmds`` (end of existing
    load commands) and the start of the first segment's file payload,
    fits the new command in if there's room.

    Most Mach-O binaries linker-pad load commands generously (4KB+ of
    zeros), so injection works without relocating any segment. If
    there isn't enough slack, we skip with a clear reason rather than
    rewriting the file layout (which would require fixing every
    fileoff / vmaddr downstream — out of scope for now).

    LC_LOAD_DYLIB layout (cmd=0x0C):
        u32 cmd          = 0x0C
        u32 cmdsize      = padded total
        u32 name_offset  = 24 (right after this struct)
        u32 timestamp    = 2
        u32 current_ver  = 0x00010000  (1.0.0)
        u32 compat_ver   = 0x00010000
        char name[]      NUL-terminated, padded to 8-byte boundary
    """
    import struct

    MAGIC_64_LE = b"\xcf\xfa\xed\xfe"
    LC_LOAD_DYLIB = 0x0C
    LC_SEGMENT_64 = 0x19

    try:
        data = bytearray(macho_path.read_bytes())
    except OSError as exc:
        return {"ok": False, "reason": f"read failed: {exc}"}

    if data[:4] != MAGIC_64_LE:
        return {"ok": False, "reason": "only 64-bit little-endian Mach-O supported (Mach-O 32-bit / fat / BE not implemented)"}

    # Parse the 32-byte mach_header_64.
    if len(data) < 32:
        return {"ok": False, "reason": "Mach-O header truncated"}
    cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from(
        "<IIIIIII", data, 4,
    )
    header_end = 32
    cmds_end = header_end + sizeofcmds

    # Find the lowest fileoff among LC_SEGMENT_64s (ignoring __PAGEZERO
    # which has fileoff=0 and filesize=0). That tells us where the
    # 'available slack' ends.
    cursor = header_end
    lowest_data_fileoff: int | None = None
    for _ in range(ncmds):
        if cursor + 8 > len(data):
            return {"ok": False, "reason": "load commands exceed file size"}
        cmd, cmdsize = struct.unpack_from("<II", data, cursor)
        if cmd == LC_SEGMENT_64 and cursor + 8 + 64 <= len(data):
            # vmaddr / vmsize / fileoff / filesize at bytes 16..48 of segment body
            fileoff = struct.unpack_from("<Q", data, cursor + 8 + 16 + 16)[0]
            filesize = struct.unpack_from("<Q", data, cursor + 8 + 16 + 24)[0]
            if filesize > 0:
                if lowest_data_fileoff is None or fileoff < lowest_data_fileoff:
                    lowest_data_fileoff = fileoff
        cursor += cmdsize

    # Compute the new command size. Path is NUL-terminated, padded so
    # cmdsize is a multiple of 8.
    path_bytes = dylib_path.encode("utf-8") + b"\x00"
    base_cmd_size = 24  # cmd + cmdsize + name_off + timestamp + cur_ver + compat_ver
    total = base_cmd_size + len(path_bytes)
    if total % 8:
        path_bytes += b"\x00" * (8 - total % 8)
    new_cmdsize = base_cmd_size + len(path_bytes)

    # Check we have slack between cmds_end and lowest_data_fileoff.
    if lowest_data_fileoff is None:
        return {"ok": False, "reason": "no LC_SEGMENT_64 with filesize > 0; binary layout unsupported"}
    slack = lowest_data_fileoff - cmds_end
    if slack < new_cmdsize:
        return {"ok": False, "reason": (
            f"only {slack} bytes of load-command slack; need {new_cmdsize}. "
            "Use insert_dylib / optool externally to relocate segments."
        )}

    # Build the new load command.
    new_cmd = (
        struct.pack(
            "<IIIIII",
            LC_LOAD_DYLIB,
            new_cmdsize,
            24,             # name offset within the command
            2,              # timestamp (arbitrary >0)
            0x00010000,     # current_version 1.0.0
            0x00010000,     # compatibility_version 1.0.0
        )
        + path_bytes
    )
    assert len(new_cmd) == new_cmdsize

    # Splice: write the new command at the end of the existing cmds
    # area (still inside the slack region). Update header counters.
    data[cmds_end:cmds_end + new_cmdsize] = new_cmd
    struct.pack_into("<I", data, 4 + 12, ncmds + 1)                    # ncmds field
    struct.pack_into("<I", data, 4 + 16, sizeofcmds + new_cmdsize)     # sizeofcmds field

    try:
        macho_path.write_bytes(bytes(data))
    except OSError as exc:
        return {"ok": False, "reason": f"write failed: {exc}"}

    return {
        "ok": True,
        "dylib_path": dylib_path,
        "bytes_written": new_cmdsize,
        "slack_remaining": slack - new_cmdsize,
        "cmds_end": cmds_end,
    }


def _va_to_file_offset(macho_path: Path, va: int) -> int | None:
    """Translate a Mach-O virtual address to a file offset.

    Walks ``LC_SEGMENT_64`` load commands from the Mach-O header until
    we find one whose VM range covers ``va``, then computes
    ``file_offset = (va - vmaddr) + fileoff``.

    Returns ``None`` when no segment claims the address — usually means
    the analyst gave us a wrong VA or a fat-binary slice we didn't pick.

    We only walk 64-bit Mach-O for now (``MH_MAGIC_64`` /
    ``MH_CIGAM_64``). 32-bit (``MH_MAGIC`` / ``LC_SEGMENT``) is
    rarer on modern iOS — left as a follow-up. Fat binaries
    (``FAT_MAGIC``/``FAT_MAGIC_64``) are also out of scope here; the
    typical workflow ingests an already-thinned single-arch binary.
    """
    import struct

    LC_SEGMENT_64 = 0x19
    MAGIC_64_LE = b"\xcf\xfa\xed\xfe"  # little-endian on disk (arm64)
    MAGIC_64_BE = b"\xfe\xed\xfa\xcf"  # big-endian variant

    try:
        with macho_path.open("rb") as fh:
            magic = fh.read(4)
            if magic not in (MAGIC_64_LE, MAGIC_64_BE):
                return None  # not a 64-bit Mach-O thin slice
            endian = "<" if magic == MAGIC_64_LE else ">"
            # mach_header_64 layout after magic:
            #   cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved
            fh.read(24)  # skip past cputype...reserved (we want the cmds count)
            # Actually re-read with proper struct: 7×u32 = 28 bytes total
            fh.seek(4)  # right after magic
            header = fh.read(28)
            cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack(
                endian + "IIIIIII", header,
            )
            for _ in range(ncmds):
                cmd_header = fh.read(8)
                if len(cmd_header) < 8:
                    return None
                cmd, cmdsize = struct.unpack(endian + "II", cmd_header)
                rest = fh.read(cmdsize - 8)
                if cmd != LC_SEGMENT_64:
                    continue
                # segment_command_64 layout (already past cmd+cmdsize):
                #   segname[16], vmaddr u64, vmsize u64, fileoff u64,
                #   filesize u64, maxprot u32, initprot u32, nsects u32, flags u32
                if len(rest) < 64:
                    return None
                vmaddr, vmsize, fileoff, filesize = struct.unpack(
                    endian + "QQQQ", rest[16:48],
                )
                if vmaddr <= va < vmaddr + vmsize:
                    return (va - vmaddr) + fileoff
        return None
    except (OSError, struct.error):
        return None


def _find_main_macho(extracted_root: Path) -> Path | None:
    """Find ``Payload/<App>.app/<Executable>`` in an unzipped IPA.

    The executable name lives in ``Info.plist`` under
    ``CFBundleExecutable``, but parsing the binary plist is overkill
    when the convention almost always matches the .app stem. We try
    the convention first, then walk the directory for any file lacking
    an extension that's also marked executable in the original zip.
    """
    payload = extracted_root / "Payload"
    if not payload.exists():
        return None
    apps = [p for p in payload.iterdir() if p.is_dir() and p.name.endswith(".app")]
    if not apps:
        return None
    app = apps[0]  # only one .app per Payload
    # Convention: <Name>.app/<Name>
    stem = app.name[:-4]  # strip '.app'
    candidate = app / stem
    if candidate.exists() and candidate.is_file():
        return candidate
    # Fallback: scan for a file with no extension.
    for child in app.iterdir():
        if child.is_file() and "." not in child.name:
            return child
    return None


def _parse_offset(raw) -> int:  # type: ignore[no-untyped-def]
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, str):
        raise IPAPatcherError(f"offset must be int or str, got {type(raw).__name__}")
    s = raw.strip()
    if not s:
        raise IPAPatcherError("offset is empty")
    return int(s, 0)  # auto-detects 0x / 0o / 0b


def _apply_patch(patch: dict, mach_o: Path) -> dict:
    """Dispatch one patch by name. Returns ``{ok: bool, ...}``.

    Failures land on ``{ok: False, reason: "..."}`` rather than raising
    so a typo in one patch doesn't abort the rest of the batch.

    Two ways to address bytes:
      * ``offset``  — file offset (Ghidra's "Offset" column / Hopper's "File offset")
      * ``va``      — virtual address (Ghidra's "Address" / "Addr" column).
                      We translate via LC_SEGMENT_64 load commands.

    Patches may supply either field; ``va`` takes precedence when both
    are present (the analyst is presumably copy-pasting the VA they
    just saw in the disassembler).
    """
    name = patch["name"]

    # inject_load_dylib is structurally different — no byte-at-offset
    # write, no VA→offset translation. Dispatch early before the offset
    # parsing kicks in.
    if name == "inject_load_dylib":
        dylib_path = patch.get("dylib_path") or ""
        if not isinstance(dylib_path, str) or not dylib_path.strip():
            return {"ok": False, "reason": "inject_load_dylib needs 'dylib_path' (str)"}
        return _inject_load_dylib(mach_o, dylib_path.strip())

    # VA translation path — convert to file offset before falling
    # through to the byte-write logic.
    if patch.get("va") is not None:
        try:
            va = _parse_offset(patch.get("va"))
        except IPAPatcherError as exc:
            return {"ok": False, "reason": f"bad va: {exc}"}
        if va < 0:
            return {"ok": False, "reason": "va must be non-negative"}
        translated = _va_to_file_offset(mach_o, va)
        if translated is None:
            return {"ok": False, "reason": f"va {hex(va)} not covered by any LC_SEGMENT_64 in {mach_o.name}"}
        offset = translated
    else:
        try:
            offset = _parse_offset(patch.get("offset"))
        except IPAPatcherError as exc:
            return {"ok": False, "reason": f"bad offset: {exc}"}
        if offset < 0:
            return {"ok": False, "reason": "offset must be non-negative"}

    size = mach_o.stat().st_size
    if name == "nop_at_offset":
        count = int(patch.get("count", 1))
        total_bytes = 4 * count
        if offset + total_bytes > size:
            return {"ok": False, "reason": f"offset+{total_bytes} exceeds Mach-O size {size}"}
        with mach_o.open("r+b") as fh:
            fh.seek(offset)
            previous = fh.read(total_bytes)
            fh.seek(offset)
            fh.write(_ARM64_NOP * count)
        return {"ok": True, "bytes_written": total_bytes, "previous_hex": previous.hex(" ")}

    if name == "return_zero_at_offset":
        new_bytes = _ARM64_MOV_X0_0 + _ARM64_RET
        if offset + len(new_bytes) > size:
            return {"ok": False, "reason": f"offset+{len(new_bytes)} exceeds Mach-O size {size}"}
        with mach_o.open("r+b") as fh:
            fh.seek(offset)
            previous = fh.read(len(new_bytes))
            fh.seek(offset)
            fh.write(new_bytes)
        return {"ok": True, "bytes_written": len(new_bytes), "previous_hex": previous.hex(" ")}

    return {"ok": False, "reason": f"unknown patch '{name}'"}


def _repack_ipa(extracted_root: Path, out_path: Path) -> None:
    """Zip the extracted Payload tree back into an IPA.

    Preserves the on-disk layout: walks the tree and writes each file
    relative to ``extracted_root``. Stored compression (vs deflated)
    matches what xcrun emits — Apple's tools don't compress the .app
    bundle.
    """
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for child in extracted_root.rglob("*"):
            if child.is_dir():
                continue
            zf.write(child, arcname=str(child.relative_to(extracted_root)))
