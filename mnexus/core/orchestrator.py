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
    JADXEngine,
    MobSFEngine,
)
from mnexus.engines.base import AnalysisContext
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
            "jadx": JADXEngine(self.config),
            "ghidra": GhidraEngine(self.config),
            "mobsf": MobSFEngine(self.config),
            "burp": BurpEngine(self.config),
            "frida": FridaEngine(self.config),
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

    async def ingest_apk(self, apk_path: Path, package_name: str, version: str) -> Project:
        """Main entry point. APK in, Project out. Pipeline runs in phases.

        Phase 1 — static (parallel): apktool + jadx + mobsf + ghidra.
        Phase 2 — correlate: build AttackSurface from all outputs.
        Phase 3 — generate hooks: Frida scripts derived from static findings.
        Phase 4 — (optional) dynamic prep when a device is connected.
        """
        project = Project.from_apk(apk_path, package_name=package_name, version=version)
        log.info("ingest started: %s (%s)", project.name, project.apk_sha256[:12])

        context = AnalysisContext(
            apk_path=apk_path,
            workspace=self.config.workspace / project.id,
            package_name=package_name,
        )

        static_tasks = [
            self.engines["apktool"].execute(context),
            self.engines["jadx"].execute(context),
            self.engines["mobsf"].execute(context),
            self.engines["ghidra"].execute(context),
        ]
        static_results = await asyncio.gather(*static_tasks, return_exceptions=True)

        all_findings = []
        for res in static_results:
            if isinstance(res, Exception):
                log.warning("static engine raised: %s", res)
                continue
            all_findings.extend(res)

        project.attack_surface = AttackSurface(findings=all_findings)
        # TODO: feed to Correlator + HookGenerator once those land.

        self.db.save_project(project)
        log.info("ingest done: %s findings", len(all_findings))
        return project
