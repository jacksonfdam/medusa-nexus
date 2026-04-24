"""JADX engine — the only decompiler that doesn't apologize."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class JADXEngine(BaseEngine):
    """Runs `jadx` for full APK → Java/Kotlin source with deobfuscation hints."""

    @property
    def name(self) -> str:
        return "jadx"

    @property
    def capabilities(self) -> list[str]:
        return ["decompile", "search", "xref"]

    async def health_check(self) -> EngineStatus:
        path = shutil.which(self.config.jadx_path)
        if not path:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="jadx not found. `brew install jadx` or `sdkmanager jadx`.",
            )
        out = await self._run([path, "--version"])
        return EngineStatus(name=self.name, installed=True, version=out.strip() or "?", path=path, message="ready to decompile")

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        """Decompile + produce secret/crypto-misuse findings. Full impl pending."""
        _ = context
        return []

    async def decompile(self, apk_path: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        await self._run(
            [
                self.config.jadx_path,
                "--deobf",
                "--show-bad-code",
                "--output-dir",
                str(output_dir),
                str(apk_path),
            ]
        )
        return output_dir

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")
