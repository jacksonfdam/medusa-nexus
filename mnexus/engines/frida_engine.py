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

    def load_medusa_module(self, module_name: str) -> str:
        """Read a Medusa recipe from disk and return its Frida script text.

        Accepts three slug shapes for the same on-disk file, all equivalent:

          * ``encryption/cipher_1``       — fully qualified, as returned by /v1/recipes
          * ``encryption/cipher_1.med``   — with extension
          * ``cipher_1``                  — bare stem; resolved by recursive search

        The bare-stem form is convenient but ambiguous when multiple modules
        share a name (Medusa has, e.g., several ``init.med`` siblings).
        We pick the first hit in deterministic order and warn via the exception
        message when ambiguity is detected.
        """
        if not self.config.medusa_path:
            raise FileNotFoundError("MNEXUS_MEDUSA_PATH not set. No recipes for you.")

        modules_dir = self.config.medusa_path / "modules"
        if not modules_dir.exists():
            raise FileNotFoundError(f"medusa modules dir missing: {modules_dir}")

        slug = module_name.removesuffix(".med")

        # Fully-qualified path — fastest path, no traversal needed.
        candidate = modules_dir / f"{slug}.med"
        if candidate.exists() and candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")

        # Bare stem — recursive fallback.
        matches = sorted(modules_dir.rglob(f"{slug}.med"))
        if not matches:
            raise FileNotFoundError(f"medusa module not found: {module_name}")
        if len(matches) > 1:
            # Surface the ambiguity but pick a deterministic winner so callers
            # don't have to deal with the exception in the common case.
            options = ", ".join(str(p.relative_to(modules_dir).with_suffix("")) for p in matches)
            import logging
            logging.getLogger(__name__).warning(
                "medusa module '%s' is ambiguous; picking %s. Use one of: %s",
                module_name, matches[0].relative_to(modules_dir), options,
            )
        return matches[0].read_text(encoding="utf-8", errors="replace")

    async def patch_with_stheno(self, apk_path: Path, patches: list[str]) -> Path:
        """Apply ``patches`` to ``apk_path`` and return the patched APK.

        The original spec called this 'Stheno' patching — ch0pin/Stheno
        turned out to be a runtime intent monitor, not an APK patcher.
        The actual implementation uses apktool + apksigner via
        ``APKPatcher`` and the name is kept for back-compat. New
        callers should prefer ``APKPatcher`` directly so they can
        read the full PatchResult (warnings, skipped patches, keystore
        path).
        """
        from mnexus.runtime.apk_patcher import APKPatcher, APKPatcherError

        patcher = APKPatcher(self.config)
        try:
            result = await patcher.patch(apk_path, patches)
        except APKPatcherError as exc:
            raise RuntimeError(f"patch failed: {exc}") from exc
        if result.patched_path is None:
            raise RuntimeError(
                "patcher returned no APK — check warnings: " + ", ".join(result.warnings)
            )
        return result.patched_path
