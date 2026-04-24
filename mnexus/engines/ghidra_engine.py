"""Ghidra engine — the NSA's gift that keeps decompiling. Headless mode only."""

from __future__ import annotations

import asyncio
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class GhidraEngine(BaseEngine):
    """Drives `analyzeHeadless` against every `.so` shipped in the APK.

    Feeds a post-script that dumps JNI table, detects crypto primitives, and
    spots the anti-tamper cliché of the month.
    """

    @property
    def name(self) -> str:
        return "ghidra"

    @property
    def capabilities(self) -> list[str]:
        return ["disassemble", "decompile_native", "find_jni", "analyze_crypto"]

    async def health_check(self) -> EngineStatus:
        if not self.config.ghidra_path or not self.config.ghidra_path.exists():
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="set MNEXUS_GHIDRA_PATH to a Ghidra install dir.",
            )
        headless = self.config.ghidra_path / "support" / "analyzeHeadless"
        if not headless.exists():
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=str(self.config.ghidra_path),
                message="analyzeHeadless not found under support/. Broken install?",
            )
        return EngineStatus(
            name=self.name,
            installed=True,
            version="headless",
            path=str(self.config.ghidra_path),
            message="ready to dissect native blobs",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

    async def analyze_native_lib(self, so_path: Path) -> dict[str, object]:  # pragma: no cover - stub
        """Run analyzeHeadless + post-script. Returns parsed JSON from the script."""
        _ = so_path
        return {}

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")
