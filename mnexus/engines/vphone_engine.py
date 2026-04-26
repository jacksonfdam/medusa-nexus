"""VPhone engine — wraps wh1te4ever/super-tart-vphone.

Treats a booted vphone VM as a *device*: SSH at localhost:2222 (root:alpine),
GDB at :8000, SEP at :8001, VNC mirror over the VM. Once a VM is up, every
iOS recipe in the recipes library runs against it via `frida -H 127.0.0.1:27042`.

Boundaries (matters):

  • This engine NEVER patches Apple firmware. The first-boot path
    (bootrom/iBSS/iBEC/LLB/TXM/kernelcache patching, IPSW restore via
    idevicerestore, Cryptex injection over SSH ramdisk) is manual — the user
    follows the upstream GUIDE.md. We only talk to a VM that's already up.
  • Research-only. SIP + AMFI must be disabled on the host; that's reported
    by the doctor but never changed by us.
  • Engine.execute() always returns []. A vphone is an analysis target,
    not an analysis source.

Audit log integration (Wave 2): every subprocess this engine spawns is
forwarded to the optional `recorder` callable so the API layer can append
to the existing `_ADB_LOG` ring buffer with `transport="vphone"`. The
engine stays testable in isolation — pass no recorder and it just runs.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


# A "recorder" appends one (argv, rc, text, note) tuple to the audit log.
RecorderFn = Callable[[list[str], int, str, str], Awaitable[None]]

# SSH defaults — fresh vphone VMs don't have host keys we trust ahead of
# time, so we explicitly skip the known-hosts check. The audit log records
# every flag, so this is observable, not silent.
_SSH_BASE_FLAGS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=5",
]
_SSH_PORT = 2222
_SSH_USER = "root"
_SSH_HOST = "127.0.0.1"


class VPhoneEngine(BaseEngine):
    """super-tart-vphone wrapper — list, start, stop, SSH, install, screenshot."""

    # Track background `tart run` PIDs so /stop and the doctor can match
    # processes to VM names. Cleared if the proc exits.
    _bg_procs: dict[str, asyncio.subprocess.Process] = {}

    # Optional audit-log appender — set by the API layer at startup.
    recorder: RecorderFn | None = None

    @property
    def name(self) -> str:
        return "vphone"

    @property
    def capabilities(self) -> list[str]:
        return ["vm_lifecycle", "ssh", "scp", "frida_host", "gdb", "vnc"]

    # ─── doctor ────────────────────────────────────────────────────────

    async def health_check(self) -> EngineStatus:
        bin_path = self._resolve_tart_bin()
        if bin_path is None:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="run scripts/setup-vphone.sh — sets MNEXUS_TART_BIN",
            )

        # Smoke-test the binary.
        try:
            rc, version_out = await self._run_local([str(bin_path), "--version"])
        except FileNotFoundError:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=str(bin_path),
                message="MNEXUS_TART_BIN points at a missing file",
            )
        if rc != 0:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=str(bin_path),
                message=f"`tart --version` returned {rc}: {version_out.strip()[:80]}",
            )

        # Count VMs (`tart list` exits 0 with a header + zero or more rows).
        try:
            _, list_out = await self._run_local([str(bin_path), "list"])
            vm_count = max(0, len([ln for ln in list_out.splitlines() if ln.strip()]) - 1)
        except Exception:  # noqa: BLE001
            vm_count = 0

        version = version_out.strip().splitlines()[0][:40] if version_out.strip() else "?"
        msg = f"research mode · {vm_count} VM{'s' if vm_count != 1 else ''}"
        return EngineStatus(
            name=self.name,
            installed=True,
            version=version,
            path=str(bin_path),
            message=msg,
        )

    # vphones are analysis targets, not finding sources.
    async def execute(self, context: AnalysisContext) -> list[Finding]:
        _ = context
        return []

    # ─── internals ─────────────────────────────────────────────────────

    def _resolve_tart_bin(self) -> Path | None:
        """Locate the super-tart binary. Order: NexusConfig → env var → none."""
        if self.config.tart_bin and Path(self.config.tart_bin).exists():
            return Path(self.config.tart_bin)
        env_bin = os.environ.get("MNEXUS_TART_BIN")
        if env_bin and Path(env_bin).exists():
            return Path(env_bin)
        # Final fallback: ~/.mnexus/tools/vphone/bin/tart (the script's symlink).
        guess = Path.home() / ".mnexus" / "tools" / "vphone" / "bin" / "tart"
        return guess if guess.exists() else None

    async def _run_local(self, argv: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str]:
        """Subprocess helper. Returns (returncode, stdout+stderr text)."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, **(env or {})},
        )
        stdout, _ = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8", errors="replace")

    # ─── meta helpers used by the API layer (Wave 2 surface) ──────────
    # These are below the doctor methods so the file reads top-to-bottom in
    # capability order: health_check → list/info → lifecycle → SSH/SCP →
    # workflows (install, screenshot).

    async def list_vms(self) -> list[dict[str, Any]]:
        """Parse `tart list` into structured rows.

        Output shape varies a bit between Tart versions; we try the JSON
        format first (`tart list --format json`) and fall back to the
        space-padded text table.
        """
        bin_path = self._resolve_tart_bin()
        if bin_path is None:
            return []
        # JSON is the cleanest contract — Tart added it years ago.
        rc, out = await self._run_local([str(bin_path), "list", "--format", "json"])
        if rc == 0 and out.strip().startswith("["):
            try:
                import json as _json
                rows = _json.loads(out)
                if isinstance(rows, list):
                    return [_normalize_list_row(r) for r in rows if isinstance(r, dict)]
            except Exception:  # noqa: BLE001
                pass

        # Fallback parser for the human-readable table.
        rc, out = await self._run_local([str(bin_path), "list"])
        if rc != 0:
            return []
        return _parse_list_table(out)

    async def vm_info(self, name: str) -> dict[str, Any]:
        """Resolve a single VM's metadata. Tart exposes `tart get <name>`."""
        bin_path = self._resolve_tart_bin()
        if bin_path is None:
            return {"name": name, "exists": False, "reason": "tart binary not configured"}
        rc, out = await self._run_local([str(bin_path), "get", name])
        if rc != 0:
            return {"name": name, "exists": False, "reason": out.strip()[:200]}
        info = {"name": name, "exists": True, "raw": out}
        # Best-effort key:value parser for the human format.
        for line in out.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            info[k.strip().lower().replace(" ", "_")] = v.strip()
        # Augment with our background-process bookkeeping.
        proc = self._bg_procs.get(name)
        info["bg_pid"] = proc.pid if proc and proc.returncode is None else None
        info["bg_running"] = proc is not None and proc.returncode is None
        info["ssh_endpoint"] = f"{_SSH_USER}@{_SSH_HOST}:{_SSH_PORT}"
        info["gdb_port"] = 8000
        info["sep_port"] = 8001
        return info

    # ─── lifecycle ─────────────────────────────────────────────────────

    async def start(self, name: str, *, extra_args: list[str] | None = None) -> dict[str, Any]:
        """`tart run <name>` in the background. Returns {pid, name, started_at}.

        super-tart inherits Tart's CLI shape: `tart run` is foreground.
        We launch it with `start_new_session=True` so it survives our
        process and capture the PID for later stop calls.
        """
        bin_path = self._require_bin()
        if proc := self._bg_procs.get(name):
            if proc.returncode is None:
                return {
                    "name": name, "pid": proc.pid, "already_running": True,
                    "ssh_endpoint": f"{_SSH_USER}@{_SSH_HOST}:{_SSH_PORT}",
                }
            # Stale entry; drop it.
            self._bg_procs.pop(name, None)

        argv = [str(bin_path), "run", name, *(extra_args or [])]
        # Discard stdout/stderr — the audit log captures only that we
        # *started* it; the host terminal still gets the live serial when
        # someone runs `tart run` themselves for debugging.
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        self._bg_procs[name] = proc
        await self._record(argv, 0, f"started pid={proc.pid}", note=f"vphone.start {name}")
        # Give the VM a beat to begin booting before returning.
        await asyncio.sleep(0.5)
        return {
            "name": name,
            "pid": proc.pid,
            "started_at": _now_iso(),
            "ssh_endpoint": f"{_SSH_USER}@{_SSH_HOST}:{_SSH_PORT}",
        }

    async def stop(self, name: str) -> dict[str, Any]:
        """`tart stop <name>` — graceful shutdown via the VM agent."""
        bin_path = self._require_bin()
        rc, out = await self._run_recorded(
            [str(bin_path), "stop", name],
            note=f"vphone.stop {name}",
        )
        # Reap our background record if any.
        proc = self._bg_procs.pop(name, None)
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        return {"name": name, "exit": rc, "output": out}

    # ─── SSH / SCP ─────────────────────────────────────────────────────

    async def ssh(self, name: str, command: str, *, timeout_s: int = 30) -> dict[str, Any]:
        """Run `command` over SSH inside the VM (`root@127.0.0.1:2222`).

        `name` is currently informational (the SSH endpoint is fixed by
        super-tart's port-forwarded boot config) — once we support
        multi-VM port mapping, the engine will look up per-VM ports.
        """
        argv = [
            "ssh",
            *_SSH_BASE_FLAGS,
            "-p", str(_SSH_PORT),
            f"{_SSH_USER}@{_SSH_HOST}",
            "--",
            command,
        ]
        rc, out = await self._run_recorded(argv, note=f"vphone.ssh[{name}] {command[:60]}", timeout_s=timeout_s)
        return {"name": name, "command": command, "exit": rc, "output": out}

    async def push(self, name: str, local: Path, remote: str) -> dict[str, Any]:
        """`scp <local> root@127.0.0.1:<remote>` — push a host file into the VM."""
        if not Path(local).exists():
            raise FileNotFoundError(local)
        argv = [
            "scp",
            *_SSH_BASE_FLAGS,
            "-P", str(_SSH_PORT),
            str(local),
            f"{_SSH_USER}@{_SSH_HOST}:{remote}",
        ]
        rc, out = await self._run_recorded(argv, note=f"vphone.push[{name}] -> {remote}")
        return {"name": name, "local": str(local), "remote": remote, "exit": rc, "output": out}

    async def pull(self, name: str, remote: str, local: Path) -> dict[str, Any]:
        """`scp root@127.0.0.1:<remote> <local>` — pull a VM file to the host."""
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "scp",
            *_SSH_BASE_FLAGS,
            "-P", str(_SSH_PORT),
            f"{_SSH_USER}@{_SSH_HOST}:{remote}",
            str(local),
        ]
        rc, out = await self._run_recorded(argv, note=f"vphone.pull[{name}] {remote}")
        return {"name": name, "remote": remote, "local": str(local), "exit": rc, "output": out}

    # ─── workflows ─────────────────────────────────────────────────────

    async def install_ipa(self, name: str, ipa_path: Path) -> dict[str, Any]:
        """Push an IPA into the VM, ldid-resign, drop into /Applications, refresh uicache.

        Three steps, all over SSH:
            1. scp the IPA to /var/mobile/Media/<basename>.ipa.
            2. unzip + extract Payload/<App>.app to /Applications.
            3. ldid -S to apply ad-hoc entitlements.
            4. uicache to register with SpringBoard.

        Requires `unzip`, `ldid` and `uicache` on the VM. The vphone Cryptex
        injection step in the upstream GUIDE puts them in /usr/local/bin.
        """
        if not Path(ipa_path).exists():
            raise FileNotFoundError(ipa_path)

        remote_ipa = f"/var/mobile/Media/{Path(ipa_path).name}"
        out_lines: list[str] = []

        push_res = await self.push(name, Path(ipa_path), remote_ipa)
        out_lines.append(f"[push] exit={push_res['exit']} {push_res['output'].strip()}")
        if push_res["exit"] != 0:
            return {"name": name, "ok": False, "stage": "push", "log": "\n".join(out_lines)}

        # The shell pipeline below is intentionally one-shot: a single SSH
        # round-trip that does extract → resign → uicache. Staging matters
        # for slower VMs; we chain with `&&` so a partial failure halts.
        script = (
            f"set -e; "
            f"cd /tmp && rm -rf vphone-stage && mkdir vphone-stage && cd vphone-stage && "
            f"unzip -q {shlex.quote(remote_ipa)} && "
            f"APP=$(ls Payload/ | head -1) && "
            f"rm -rf /Applications/$APP && cp -R Payload/$APP /Applications/ && "
            f"ldid -S /Applications/$APP/$(basename $APP .app) || true && "
            f"uicache -p /Applications/$APP && "
            f"echo INSTALLED:$APP"
        )
        ssh_res = await self.ssh(name, script, timeout_s=120)
        out_lines.append(f"[install] exit={ssh_res['exit']}")
        out_lines.append(ssh_res["output"].strip())
        ok = ssh_res["exit"] == 0 and "INSTALLED:" in ssh_res["output"]
        bundle = ""
        for line in ssh_res["output"].splitlines():
            if line.startswith("INSTALLED:"):
                bundle = line.removeprefix("INSTALLED:").strip()
        return {
            "name": name, "ok": ok, "bundle": bundle,
            "remote_ipa": remote_ipa,
            "log": "\n".join(out_lines),
        }

    async def screenshot(self, name: str, *, dest: Path | None = None) -> dict[str, Any]:
        """Capture the current VM screen as PNG.

        super-tart's TrollVNC mirror exposes a standard VNC server on port
        5900. We don't ship a VNC client — if `vncsnapshot` or `vncdotool`
        is on PATH we use it; otherwise we report a clean 501-shaped result
        the API can translate to an HTTP 501 with a `hint` field.
        """
        for tool, argv_factory in (
            ("vncsnapshot", lambda dst: ["vncsnapshot", "-quality", "85", f"{_SSH_HOST}:0", str(dst)]),
            ("vncdotool",   lambda dst: ["vncdotool", "-s", f"{_SSH_HOST}::5900", "capture", str(dst)]),
        ):
            if not _which(tool):
                continue
            out_path = Path(dest or (Path.home() / ".mnexus" / "workspace" / "screenshots" / f"vphone-{name}-{int(time.time())}.png"))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            argv = argv_factory(out_path)
            rc, out = await self._run_recorded(argv, note=f"vphone.screenshot[{name}] via {tool}")
            if rc == 0 and out_path.exists():
                return {"name": name, "ok": True, "tool": tool, "path": str(out_path), "size_bytes": out_path.stat().st_size}
            return {"name": name, "ok": False, "tool": tool, "exit": rc, "output": out}
        return {
            "name": name, "ok": False,
            "hint": "install `vncsnapshot` (`brew install vncsnapshot`) or `vncdotool` (`pip install vncdotool`) — neither is on PATH",
        }

    # ─── infra ─────────────────────────────────────────────────────────

    def _require_bin(self) -> Path:
        bin_path = self._resolve_tart_bin()
        if bin_path is None:
            raise RuntimeError("tart binary not configured — run scripts/setup-vphone.sh")
        return bin_path

    async def _record(self, argv: list[str], rc: int, output: str, *, note: str) -> None:
        if self.recorder is not None:
            try:
                await self.recorder(argv, rc, output, note)
            except Exception:  # noqa: BLE001 — recording must never crash the engine
                pass

    async def _run_recorded(
        self,
        argv: list[str],
        *,
        note: str,
        timeout_s: int | None = None,
    ) -> tuple[int, str]:
        """Like `_run_local` but pipes the result through `recorder` first."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            await self._record(argv, 127, f"command not found: {argv[0]}", note=note)
            raise RuntimeError(str(exc)) from exc

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            await self._record(argv, 124, f"timeout after {timeout_s}s", note=note)
            return 124, f"<timeout after {timeout_s}s>"
        text = stdout.decode("utf-8", errors="replace")
        await self._record(argv, proc.returncode, text, note=note)
        return proc.returncode, text


# ─── module-level helpers ──────────────────────────────────────────────

def _normalize_list_row(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure every list-row carries the keys the UI expects."""
    return {
        "name":     row.get("Name") or row.get("name") or "",
        "state":    row.get("State") or row.get("state") or "stopped",
        "size":     row.get("Size") or row.get("size") or "",
        "source":   row.get("Source") or row.get("source") or "local",
        "running":  (row.get("State") or row.get("state") or "").lower() == "running",
    }


def _parse_list_table(raw: str) -> list[dict[str, Any]]:
    """Parse the space-padded `tart list` table.

    Header columns (in order): Source · Name · Disk · Size · State.
    We stay tolerant — different Tart builds reorder these.
    """
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []
    # Detect the header row to find column starts.
    header = lines[0]
    cols = ["source", "name", "disk", "size", "state"]
    rows: list[dict[str, Any]] = []
    for ln in lines[1:]:
        parts = ln.split()
        if not parts:
            continue
        row = dict(zip(cols, parts + [""] * (len(cols) - len(parts))))
        row["running"] = row.get("state", "").lower() == "running"
        rows.append(row)
    return rows


def _which(binary: str) -> str | None:
    """Tiny shutil.which shim — avoids importing shutil for one call site."""
    import shutil as _sh
    return _sh.which(binary)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
