"""APKTool engine — resource whisperer. Decodes manifest + resources."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class APKToolEngine(BaseEngine):
    """Wraps `apktool d` for manifest parsing + resource inspection."""

    @property
    def name(self) -> str:
        return "apktool"

    @property
    def capabilities(self) -> list[str]:
        return ["decode", "manifest", "resources"]

    async def health_check(self) -> EngineStatus:
        path = shutil.which(self.config.apktool_path)
        if not path:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="apktool missing. `brew install apktool` or download the jar.",
            )
        out = await self._run([path, "--version"])
        return EngineStatus(name=self.name, installed=True, version=out.strip() or "?", path=path, message="ready to decode")

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

    async def decode(self, apk_path: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        await self._run([self.config.apktool_path, "d", "-f", "-o", str(output_dir), str(apk_path)])
        return output_dir

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")
