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

    async def extract_manifest(self, apk_path: Path) -> dict[str, str]:
        """Fast path for upload flow: decode just enough to read the manifest.

        `-s` skips DEX sources. Returns dict with at minimum `package` and
        `version_name`. Empty dict on failure (caller decides how to react).
        """
        import xml.etree.ElementTree as ET

        out = apk_path.parent / f"_manifest-{apk_path.stem}"
        try:
            await self._run(
                [self.config.apktool_path, "d", "-s", "-f", "-o", str(out), str(apk_path)]
            )
        except Exception:  # noqa: BLE001 — we really do want to swallow everything here
            return {}

        manifest_path = out / "AndroidManifest.xml"
        if not manifest_path.exists():
            return {}

        try:
            root = ET.parse(manifest_path).getroot()
        except ET.ParseError:
            return {}

        ns = "{http://schemas.android.com/apk/res/android}"
        return {
            "package": root.get("package", "") or "",
            "version_name": root.get(f"{ns}versionName") or "",
            "version_code": root.get(f"{ns}versionCode") or "",
            "min_sdk": (root.find("uses-sdk").get(f"{ns}minSdkVersion") if root.find("uses-sdk") is not None else "") or "",
            "target_sdk": (root.find("uses-sdk").get(f"{ns}targetSdkVersion") if root.find("uses-sdk") is not None else "") or "",
        }

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")
