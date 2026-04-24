"""Frida engine — where static suspicions meet dynamic evidence.

Wraps Frida itself plus the two ch0pin frameworks: Medusa (recipe modules) and
Stheno (APK patching). Everything dynamic in this platform funnels through here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class FridaEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "frida"

    @property
    def capabilities(self) -> list[str]:
        return [
            "hook",
            "trace",
            "bypass_ssl",
            "bypass_root",
            "crypto_log",
            "intent_monitor",
            "medusa_recipes",
            "stheno_patch",
        ]

    async def health_check(self) -> EngineStatus:
        try:
            import frida  # type: ignore[import-untyped]
        except ImportError:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="pip install frida. Then come back.",
            )
        return EngineStatus(
            name=self.name,
            installed=True,
            version=frida.__version__,
            path=shutil.which("frida"),
            message="ready to hook things you aren't supposed to hook",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

    # ─── helpers ───

    def load_medusa_module(self, module_name: str) -> str:  # pragma: no cover - stub
        """Read a Medusa recipe from disk and return its Frida script text."""
        if not self.config.medusa_path:
            raise FileNotFoundError("MNEXUS_MEDUSA_PATH not set. No recipes for you.")
        module = self.config.medusa_path / "modules" / f"{module_name}.med"
        if not module.exists():
            raise FileNotFoundError(f"medusa module not found: {module_name}")
        return module.read_text()

    async def patch_with_stheno(self, apk_path: Path, patches: list[str]) -> Path:  # pragma: no cover - stub
        """Invoke Stheno on `apk_path` with the listed patches. Returns patched apk path."""
        _ = apk_path, patches
        raise NotImplementedError("stheno binding pending — see plan iteration 3")
