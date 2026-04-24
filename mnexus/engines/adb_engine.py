"""ADB engine — the glue. Lists packages, pulls APKs, runs shell, streams logcat."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class ADBEngine(BaseEngine):
    """Thin async wrapper around `adb`. Not smart. Doesn't need to be."""

    @property
    def name(self) -> str:
        return "adb"

    @property
    def capabilities(self) -> list[str]:
        return ["device_connect", "pull_apk", "install", "logcat", "shell"]

    async def health_check(self) -> EngineStatus:
        path = shutil.which(self.config.adb_path) or self.config.adb_path
        if not path or not Path(path).exists():
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="adb not on PATH. Install platform-tools. This is step zero.",
            )
        version = await self._run([str(path), "version"])
        first_line = version.splitlines()[0] if version else "unknown"
        return EngineStatus(
            name=self.name,
            installed=True,
            version=first_line,
            path=str(path),
            message="connected and gossipy",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """ADB doesn't produce findings on its own — it's plumbing. Returns []."""
        _ = context
        return []

    # ─── public helpers used by orchestrator + UI ───

    async def is_device_connected(self) -> bool:
        output = await self._run([self.config.adb_path, "devices"])
        lines = [ln for ln in output.splitlines()[1:] if ln.strip()]
        return any("device" in ln and "offline" not in ln for ln in lines)

    async def list_packages(self, filter_: str = "") -> list[str]:
        cmd = [self.config.adb_path, "shell", "pm", "list", "packages"]
        if filter_:
            cmd.append(filter_)
        output = await self._run(cmd)
        return [ln.removeprefix("package:").strip() for ln in output.splitlines() if ln.strip()]

    async def pull_apk(self, package_name: str, output_dir: Path) -> list[Path]:
        """Pull base + split APKs. Returns all local paths."""
        output_dir.mkdir(parents=True, exist_ok=True)
        paths_raw = await self._run([self.config.adb_path, "shell", "pm", "path", package_name])
        remote_paths = [ln.removeprefix("package:").strip() for ln in paths_raw.splitlines() if ln.strip()]
        pulled: list[Path] = []
        for remote in remote_paths:
            local = output_dir / Path(remote).name
            await self._run([self.config.adb_path, "pull", remote, str(local)])
            pulled.append(local)
        return pulled

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")
