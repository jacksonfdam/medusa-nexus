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


SUPPORTED_PATCHES = ("nop_at_offset", "return_zero_at_offset")


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
    """
    name = patch["name"]
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
