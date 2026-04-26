"""MedusaNexus — the brainstem every head reports to.

Responsibilities:
- Owns engine instances and their lifecycle.
- Drives the ingest pipeline: decode → static fan-out → surface build → hook gen
  → (optional) dynamic prep.
- Writes everything into the artifact store so the UI and reports can read it
  back later without running the whole thing again.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from mnexus.config import NexusConfig
from mnexus.core.artifact_store import ArtifactStore
from mnexus.engines import (
    ADBEngine,
    APKToolEngine,
    BaseEngine,
    BurpEngine,
    FridaEngine,
    GhidraEngine,
    IPAToolEngine,
    JADXEngine,
    MobSFEngine,
    VPhoneEngine,
)
from mnexus.engines.apktool_engine import attack_surface_from_meta
from mnexus.engines.base import AnalysisContext
from mnexus.engines.ipatool_engine import attack_surface_from_ipa_meta
from mnexus.intelligence.hook_generator import HookGenerator
from mnexus.models.attack_surface import AttackSurface
from mnexus.models.project import Project

log = logging.getLogger(__name__)


class MedusaNexus:
    """Top-level orchestrator. Instantiate once per process; survive many ingests."""

    def __init__(self, config: NexusConfig | None = None) -> None:
        self.config = config or NexusConfig.from_env()
        self.config.ensure_workspace()
        self.db = ArtifactStore(self.config.db_path)
        self.engines: dict[str, BaseEngine] = self._register_engines()

    def _register_engines(self) -> dict[str, BaseEngine]:
        return {
            "adb": ADBEngine(self.config),
            "apktool": APKToolEngine(self.config),
            "ipatool": IPAToolEngine(self.config),
            "jadx": JADXEngine(self.config),
            "ghidra": GhidraEngine(self.config),
            "mobsf": MobSFEngine(self.config),
            "burp": BurpEngine(self.config),
            "frida": FridaEngine(self.config),
            "vphone": VPhoneEngine(self.config),
        }

    async def doctor(self) -> list[dict[str, object]]:
        """Run health_check across every engine. Used by `mnexus doctor`."""
        results = await asyncio.gather(*(e.health_check() for e in self.engines.values()))
        return [
            {
                "name": r.name,
                "installed": r.installed,
                "version": r.version,
                "path": r.path,
                "message": r.message,
            }
            for r in results
        ]

    async def ingest(
        self,
        artifact_path: Path,
        package_name: str,
        version: str,
        *,
        existing_id: str | None = None,
    ) -> Project:
        """Platform-aware ingest dispatcher.

        Routes by file extension: `.apk`/`.xapk` → Android pipeline,
        `.ipa` → iOS pipeline. Both produce the same `Project` shape; the
        engines that participate just differ.
        """
        suffix = artifact_path.suffix.lower()
        if suffix == ".ipa":
            return await self._ingest_ipa(artifact_path, package_name, version, existing_id=existing_id)
        # Default to the Android path — `.apk`, `.xapk`, or unknown extensions.
        return await self.ingest_apk(artifact_path, package_name, version, existing_id=existing_id)

    async def ingest_apk(
        self,
        apk_path: Path,
        package_name: str,
        version: str,
        *,
        existing_id: str | None = None,
    ) -> Project:
        """Main entry point. APK in, Project out. Pipeline runs in phases.

        Phase 1 — static (parallel): apktool + jadx + mobsf + ghidra.
        Phase 2 — correlate: build AttackSurface from all outputs (manifest +
                  per-engine extras + their findings).
        Phase 3 — generate hooks: Frida scripts derived from static findings.

        When `existing_id` is provided the new project payload reuses that id,
        which lets the rescan endpoint refresh data in place.
        """
        project = Project.from_apk(apk_path, package_name=package_name, version=version, platform="android")
        if existing_id:
            project.id = existing_id
        log.info("ingest started: %s (%s)", project.name, project.apk_sha256[:12])

        context = AnalysisContext(
            apk_path=apk_path,
            workspace=self.config.workspace / project.id,
            package_name=package_name,
            extras={},
        )

        # Run apktool first so the others can read context.extras["apk_meta"].
        try:
            apktool_findings = await self.engines["apktool"].execute(context)
        except Exception as exc:  # noqa: BLE001
            log.warning("apktool engine raised: %s", exc)
            apktool_findings = []

        # The remaining static engines run in parallel.
        static_tasks = [
            self.engines["jadx"].execute(context),
            self.engines["mobsf"].execute(context),
            self.engines["ghidra"].execute(context),
        ]
        static_results = await asyncio.gather(*static_tasks, return_exceptions=True)

        all_findings = list(apktool_findings)
        for res in static_results:
            if isinstance(res, Exception):
                log.warning("static engine raised: %s", res)
                continue
            all_findings.extend(res)

        # Build the AttackSurface from manifest data + per-engine extras.
        meta = context.extras.get("apk_meta") or {}
        exported, natives, deeplinks, perms, sdk_fp = attack_surface_from_meta(meta)

        # Merge crypto operations + ssl/root signals from JADX/Ghidra.
        crypto_ops = []
        ssl_pinning = False
        ssl_lib = None
        root_det = False
        root_lib = None
        statics = context.extras.get("static") or {}
        for sub in statics.values():
            crypto_ops.extend(sub.get("crypto_operations") or [])
            if sub.get("ssl_pinning_detected"):
                ssl_pinning = True
                ssl_lib = ssl_lib or sub.get("ssl_pinning_library")
            if sub.get("root_detection_detected"):
                root_det = True
                root_lib = root_lib or sub.get("root_detection_library")

        # Cleartext traffic flag also lights up the network header strip.
        if (meta.get("uses_cleartext_traffic") or "").lower() == "true":
            # leave unchanged — surfaces in findings already
            pass

        # Project metadata that the manifest gave us.
        if meta.get("min_sdk"):
            try: project.min_sdk = int(meta["min_sdk"])
            except ValueError: pass
        if meta.get("target_sdk"):
            try: project.target_sdk = int(meta["target_sdk"])
            except ValueError: pass
        if meta.get("version_code"):
            try: project.version_code = int(meta["version_code"])
            except ValueError: pass

        project.attack_surface = AttackSurface(
            exported_components=exported,
            deeplinks=deeplinks,
            native_libraries=natives,
            api_endpoints=[],   # populated dynamically once Burp captures land
            permissions=perms,
            sdk_fingerprint=sdk_fp,
            crypto_operations=crypto_ops,
            ssl_pinning_detected=ssl_pinning,
            ssl_pinning_library=ssl_lib,
            root_detection_detected=root_det,
            root_detection_library=root_lib,
            findings=all_findings,
        )

        # Phase 3 — auto-hooks from the surface.
        try:
            hooks = HookGenerator().for_attack_surface(project.attack_surface)
            project.suggested_hooks = [h.script for h in hooks]
        except Exception as exc:  # noqa: BLE001
            log.warning("hook generator raised: %s", exc)

        self.db.save_project(project)
        log.info(
            "ingest done: %s findings · %s components · %s natives · risk=%.1f",
            len(all_findings),
            len(exported),
            len(natives),
            project.attack_surface.risk_score(),
        )
        return project

    async def _ingest_ipa(
        self,
        ipa_path: Path,
        package_name: str,
        version: str,
        *,
        existing_id: str | None = None,
    ) -> Project:
        """iOS-flavoured pipeline.

        Phase 1 — static (parallel): ipatool + mobsf + ghidra (Mach-O path).
                  jadx is skipped (no DEX in iOS).
        Phase 2 — assemble AttackSurface from `context.extras["ipa_meta"]`
                  + per-engine static signals.
        Phase 3 — auto-hooks. HookGenerator is platform-aware — emits
                  Obj-C runtime hooks when project.platform == "ios".
        """
        project = Project.from_apk(ipa_path, package_name=package_name, version=version, platform="ios")
        if existing_id:
            project.id = existing_id
        log.info("[ios] ingest started: %s (%s)", project.name, project.apk_sha256[:12])

        context = AnalysisContext(
            apk_path=ipa_path,
            workspace=self.config.workspace / project.id,
            package_name=package_name,
            extras={"platform": "ios"},
        )

        # Run ipatool first so the others can read context.extras["ipa_meta"].
        try:
            ipatool_findings = await self.engines["ipatool"].execute(context)
        except Exception as exc:  # noqa: BLE001
            log.warning("ipatool engine raised: %s", exc)
            ipatool_findings = []

        # MobSF + Ghidra in parallel. Ghidra autodetects Mach-O.
        static_tasks = [
            self.engines["mobsf"].execute(context),
            self.engines["ghidra"].execute(context),
        ]
        static_results = await asyncio.gather(*static_tasks, return_exceptions=True)

        all_findings = list(ipatool_findings)
        for res in static_results:
            if isinstance(res, Exception):
                log.warning("[ios] static engine raised: %s", res)
                continue
            all_findings.extend(res)

        meta = context.extras.get("ipa_meta") or {}
        surface_kwargs = attack_surface_from_ipa_meta(meta)

        # Per-engine extras.
        crypto_ops = []
        jb_detected = False
        jb_lib: str | None = None
        statics = context.extras.get("static") or {}
        for sub in statics.values():
            crypto_ops.extend(sub.get("crypto_operations") or [])
            if sub.get("jailbreak_detection_detected"):
                jb_detected = True
                jb_lib = jb_lib or sub.get("jailbreak_detection_library")

        # Project metadata from the manifest.
        if meta.get("min_os"):
            try:
                # iOS min_os is "13.0" — store as integer of major version.
                project.min_sdk = int(str(meta["min_os"]).split(".")[0])
            except (ValueError, IndexError):
                pass
        if meta.get("version_code"):
            try:
                project.version_code = int(meta["version_code"])
            except ValueError:
                pass

        from mnexus.models.attack_surface import AttackSurface as _AS
        project.attack_surface = _AS(
            **surface_kwargs,
            api_endpoints=[],
            crypto_operations=crypto_ops,
            ssl_pinning_detected=False,    # iOS: pinning is per-NSURLSession; surfaced in findings instead
            ssl_pinning_library=None,
            root_detection_detected=False,
            root_detection_library=None,
            jailbreak_detection_detected=jb_detected,
            jailbreak_detection_library=jb_lib,
            findings=all_findings,
        )

        # Phase 3 — auto-hooks (platform-aware).
        try:
            hooks = HookGenerator().for_attack_surface(project.attack_surface, platform="ios")
            project.suggested_hooks = [h.script for h in hooks]
        except TypeError:
            # Older HookGenerator signature (no platform kwarg) — fall back.
            try:
                hooks = HookGenerator().for_attack_surface(project.attack_surface)
                project.suggested_hooks = [h.script for h in hooks]
            except Exception as exc:  # noqa: BLE001
                log.warning("[ios] hook generator raised: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("[ios] hook generator raised: %s", exc)

        self.db.save_project(project)
        log.info(
            "[ios] ingest done: %s findings · %s url-schemes · %s frameworks · risk=%.1f",
            len(all_findings),
            len(meta.get("url_schemes") or []),
            len(meta.get("frameworks") or []),
            project.attack_surface.risk_score(),
        )
        return project
