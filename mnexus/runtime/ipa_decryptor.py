"""IPADecryptor — pull a FairPlay-decrypted IPA off a jailbroken iOS device.

App Store IPAs ship encrypted; the kernel decrypts in memory at load
time. The standard pentester workflow ("Bloco 2" of the talk):

  1. Spawn the target app on a JB device.
  2. Wait for the kernel to decrypt __TEXT / __DATA segments.
  3. Dump the decrypted pages, fix up LC_ENCRYPTION_INFO so cryptid=0.
  4. Re-pack as IPA.

Implementing that from scratch is a project on its own. Instead, this
wrapper drives the well-tested CLIs already in the ecosystem:

  * **frida-ios-dump** (AloneMonkey, Python) — clones from GitHub,
    runs ``python3 dump.py <bundle_id>``. Output: ``<App>.ipa`` in
    the working directory.
  * **bagbak** (chichou, Node/TypeScript) — ``bagbak <bundle_id> -o
    out.ipa``. Modern alternative; cleaner output shape.

Detection: ``IPADecryptor.detect()`` returns the first available
tool in preference order [bagbak, frida-ios-dump]. ``decrypt()``
runs it as a subprocess; failures surface a clear error string
instead of a stack trace.

When neither tool is present, ``decrypt()`` raises
``IPADecryptorError`` with a hint pointing at the install paths.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class IPADecryptorError(RuntimeError):
    """Raised for any non-environmental decrypt failure — bad bundle id,
    no device, subprocess crashed. Environmental issues (tool missing)
    raise ``IPADecryptorMissing`` so the API can answer 503 cleanly."""


class IPADecryptorMissing(IPADecryptorError):
    """No supported decryptor on PATH or under ``~/.mnexus/tools/``."""


@dataclass
class DecryptResult:
    """JSON-safe outcome of one decrypt run."""
    tool: str
    bundle_id: str
    ipa_path: Path | None
    log: str = ""
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        return {
            "tool":         self.tool,
            "bundle_id":    self.bundle_id,
            "ipa_path":     str(self.ipa_path) if self.ipa_path else None,
            "log":          self.log,
            "duration_ms":  self.duration_ms,
            "warnings":     list(self.warnings),
        }


# Tool definitions — (display name, command builder, output discoverer).
# Adding a third tool is a new entry in _TOOLS.
def _bagbak_cmd(bundle_id: str, out_path: Path) -> list[str]:
    return ["bagbak", bundle_id, "-o", str(out_path)]


def _frida_ios_dump_cmd(bundle_id: str, out_path: Path) -> list[str]:
    """frida-ios-dump's dump.py supports ``-o`` since 2019.

    Falls back to the older positional behaviour in the discoverer if
    the script ignores -o (some forks do; we pick up the first IPA in
    the cwd as a safety net)."""
    return ["python3", "dump.py", bundle_id, "-o", str(out_path)]


class IPADecryptor:
    """Stateless orchestrator — instantiated per request."""

    # Preference order. bagbak first because it's the modern wrapper
    # with structured output; frida-ios-dump as the older fallback.
    _TOOLS = [
        ("bagbak",          _bagbak_cmd,         None),
        ("frida-ios-dump",  _frida_ios_dump_cmd, "dump.py"),
    ]

    def __init__(self, config) -> None:  # type: ignore[no-untyped-def]
        self.config = config

    # ─── detection ───────────────────────────────────────────────────

    def detect(self) -> tuple[str, str] | None:
        """Find the first available tool. Returns (name, executable_path)
        or None when nothing's installed.

        For frida-ios-dump we look for ``dump.py`` in
        ``~/.mnexus/tools/frida-ios-dump/`` first, then ``PATH``.
        """
        # bagbak: simple PATH lookup.
        bagbak = shutil.which("bagbak")
        if bagbak:
            return ("bagbak", bagbak)

        # frida-ios-dump: vendored under ~/.mnexus/tools, or on PATH.
        candidate = self._frida_ios_dump_path()
        if candidate is not None:
            return ("frida-ios-dump", str(candidate))
        return None

    def _frida_ios_dump_path(self) -> Path | None:
        """frida-ios-dump is a git clone, not a pip install. Look under
        the tools dir setup.sh would land it in, then PATH."""
        tools = Path(self.config.workspace).parent / "tools" / "frida-ios-dump"
        candidate = tools / "dump.py"
        if candidate.exists():
            return candidate
        found = shutil.which("dump.py")
        return Path(found) if found else None

    # ─── public API ──────────────────────────────────────────────────

    async def decrypt(
        self,
        bundle_id: str,
        *,
        out_dir: Path | None = None,
        device_id: str | None = None,
        timeout_s: int = 180,
    ) -> DecryptResult:
        """Decrypt the app identified by ``bundle_id`` against the
        connected JB device. Returns the IPA path.

        ``out_dir`` defaults to ``$MNEXUS_WORKSPACE/decrypted-ipas``.
        ``device_id`` is forwarded to the tool when supported (bagbak
        does; frida-ios-dump ignores). ``timeout_s`` aborts the
        subprocess after the budget — large apps can hit this on first
        decrypt; 3 minutes is the sane default.
        """
        if not bundle_id or not bundle_id.strip():
            raise IPADecryptorError("bundle_id is empty")
        tool = self.detect()
        if tool is None:
            raise IPADecryptorMissing(
                "no IPA decryptor installed. Install one:\n"
                "  npm install -g bagbak  (preferred)\n"
                "  OR git clone https://github.com/AloneMonkey/frida-ios-dump "
                "~/.mnexus/tools/frida-ios-dump"
            )

        tool_name, tool_path = tool
        out_dir = out_dir or (Path(self.config.workspace) / "decrypted-ipas")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{bundle_id}.ipa"

        # Build the command from the tool table.
        cmd_builder = next(b for n, b, _ in self._TOOLS if n == tool_name)
        cmd = cmd_builder(bundle_id, out_path)

        # bagbak supports -d <device_id> for multi-device hosts; frida-ios-dump
        # doesn't (uses the first USB device unconditionally).
        if device_id and tool_name == "bagbak":
            cmd.extend(["-d", device_id])

        warnings: list[str] = []
        # frida-ios-dump's dump.py is a script that needs to run from
        # its own directory (imports + config files). cd there for the run.
        cwd: Path | None = None
        if tool_name == "frida-ios-dump":
            cwd = Path(tool_path).parent
            cmd[1] = "dump.py"  # use relative path now that we cd'd

        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
            )
        except FileNotFoundError as exc:
            raise IPADecryptorError(f"failed to spawn {cmd[0]}: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise IPADecryptorError(
                f"{tool_name} ran past {timeout_s}s budget. Large apps may need a higher timeout."
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        log_text = (stdout or b"").decode("utf-8", errors="replace") + (
            "\n--- stderr ---\n" + (stderr or b"").decode("utf-8", errors="replace")
            if stderr else ""
        )

        # Did the IPA materialise? Check the requested path first; fall
        # back to scanning the cwd for any *.ipa newer than ``started``.
        result_path: Path | None = None
        if out_path.exists() and out_path.stat().st_size > 0:
            result_path = out_path
        else:
            # frida-ios-dump's older forks may name the IPA after the
            # display name, not the bundle id. Walk the dirs we know
            # about and pick the freshest .ipa.
            scan_dirs = [out_dir, Path(cwd) if cwd else None, Path.cwd()]
            for d in (d for d in scan_dirs if d and d.exists()):
                for child in sorted(d.glob("*.ipa"), key=lambda p: -p.stat().st_mtime):
                    age = time.time() - child.stat().st_mtime
                    if age < 600:  # 10 minutes — assume this is our output
                        # Move into the canonical workspace location.
                        moved = out_dir / f"{bundle_id}.ipa"
                        if child != moved:
                            shutil.move(str(child), str(moved))
                        result_path = moved
                        warnings.append(
                            f"{tool_name} wrote to '{child}' instead of the requested -o "
                            f"path; we moved it to {moved}."
                        )
                        break
                if result_path is not None:
                    break

        if result_path is None:
            raise IPADecryptorError(
                f"{tool_name} returned exit code {proc.returncode} but "
                f"produced no IPA. Log:\n{log_text[-2000:]}"
            )

        return DecryptResult(
            tool=tool_name,
            bundle_id=bundle_id,
            ipa_path=result_path,
            log=log_text,
            duration_ms=duration_ms,
            warnings=warnings,
        )
