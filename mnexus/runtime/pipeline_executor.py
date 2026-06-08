"""PipelineExecutor — turns a YAML pipeline definition into actual engine calls.

The Pipeline Editor screen has been able to display YAML since v0; what
nobody could do was hit ``[ RUN ]`` and watch it execute. This module
closes that loop.

Design:

  * One ``PipelineRun`` per ``/v1/pipelines/{name}/run`` call. Lives
    in a process-local registry keyed by short opaque ``run_id`` so
    the SSE stream + status polling can attach to it.
  * Sequential or parallel stages, declared by the YAML.
  * Per-stage outcome surfaces ``ok`` / ``skipped`` / ``failed`` + a
    free-form ``output`` dict (findings count, generated path, …)
  * Engine dispatch is table-driven — adding a new ``engine + action``
    pair is one entry in ``_STAGE_HANDLERS``.

Engine actions supported in this iteration:

  * apktool / decode             — already run as part of ingest; this
                                   is essentially a no-op confirming
                                   the decoded tree exists.
  * jadx / decompile             — JADXEngine.execute against the
                                   project's stored APK + surface.
  * mobsf / full_scan            — MobSFEngine.execute.
  * ghidra / analyze_native_libs — GhidraEngine.execute.
  * playintel / scan             — PlayIntelEngine.analyze_package via
                                   the existing scan-from-project flow.
  * reporter / generate          — ReportGenerator writes to disk.
  * stheno / patch               — APKPatcher with patches from the
                                   stage params.
  * frida / run_session          — soft-skip in this iteration; the
                                   dynamic flow needs a connected
                                   device and is better launched from
                                   the Dynamic tab. Marked ``skipped``
                                   with a clear hint.

Unknown engine/action pairs land on ``skipped`` rather than failing
the whole pipeline — the operator may have a custom stage they're
prototyping; we don't want one typo to abort everything.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


@dataclass
class StageOutcome:
    """One stage's result — what happened, how long it took."""
    name: str
    engine: str = ""
    action: str = ""
    status: str = "pending"  # pending | running | ok | skipped | failed
    started_at: float | None = None
    finished_at: float | None = None
    duration_ms: int | None = None
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":         self.name,
            "engine":       self.engine,
            "action":       self.action,
            "status":       self.status,
            "started_at":   self.started_at,
            "finished_at":  self.finished_at,
            "duration_ms":  self.duration_ms,
            "error":        self.error,
            "output":       self.output,
        }


@dataclass
class PipelineRun:
    """A live pipeline execution. Held in the registry until the
    process restarts; not persisted across reloads on purpose — the
    artefacts each stage produced are persisted by their respective
    engines and survive."""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    pipeline_name: str = ""
    project_id: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    state: str = "queued"  # queued | running | ok | failed
    stages: list[StageOutcome] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id":         self.run_id,
            "pipeline_name":  self.pipeline_name,
            "project_id":     self.project_id,
            "started_at":     self.started_at,
            "finished_at":    self.finished_at,
            "state":          self.state,
            "error":          self.error,
            "stages":         [s.to_dict() for s in self.stages],
        }


# Process-local registry. Sessions die with uvicorn restarts.
pipeline_runs: dict[str, PipelineRun] = {}


# ─── stage handlers ──────────────────────────────────────────────────


# A handler receives (project, stage_definition) and returns the
# output dict for the stage. Raising means failure; returning None
# means skipped.
StageHandler = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any] | None]]


async def _handle_apktool_decode(nexus, project, stage) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    """No-op confirmation — apktool already ran during ingest. We
    surface 'decoded_components_count' so the stage isn't empty."""
    _ = stage
    surface = project.attack_surface
    if surface is None:
        return None
    return {
        "decoded_components": len(surface.exported_components),
        "deeplinks": len(surface.deeplinks),
        "permissions": len(surface.permissions),
    }


async def _handle_jadx_decompile(nexus, project, stage) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    _ = stage
    from mnexus.engines.base import AnalysisContext
    engine = nexus.engines.get("jadx")
    if engine is None:
        raise RuntimeError("jadx engine not registered")
    ctx = AnalysisContext(apk_path=project.apk_path, package_name=project.package_name)
    findings = await engine.execute(ctx)
    return {"findings": len(findings)}


async def _handle_mobsf_full_scan(nexus, project, stage) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    _ = stage
    from mnexus.engines.base import AnalysisContext
    engine = nexus.engines.get("mobsf")
    if engine is None:
        raise RuntimeError("mobsf engine not registered")
    ctx = AnalysisContext(apk_path=project.apk_path, package_name=project.package_name)
    findings = await engine.execute(ctx)
    return {"findings": len(findings)}


async def _handle_ghidra_native(nexus, project, stage) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    _ = stage
    from mnexus.engines.base import AnalysisContext
    engine = nexus.engines.get("ghidra")
    if engine is None:
        raise RuntimeError("ghidra engine not registered")
    ctx = AnalysisContext(apk_path=project.apk_path, package_name=project.package_name)
    findings = await engine.execute(ctx)
    return {"findings": len(findings)}


async def _handle_playintel_scan(nexus, project, stage) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Run the PlayIntel analyser against the project's stored APK.

    Skips when the project doesn't have an apk_path that exists on
    disk — analyst already saw the 410 elsewhere."""
    _ = stage
    from pathlib import Path
    apk_path = project.apk_path if isinstance(project.apk_path, Path) else Path(str(project.apk_path))
    if not apk_path.exists():
        return None
    from mnexus.engines.play_intel_engine import PlayIntelEngine
    from mnexus.playintel.apk_source import local_source_for
    engine = PlayIntelEngine(nexus.config)
    source = local_source_for(apk_path, workspace=nexus.config.workspace)
    outcome, findings = await engine.analyze_package(
        project.package_name, source=source, workspace=nexus.config.workspace,
        run_active_probes=False,
    )
    return {
        "findings": len(findings),
        "firebase_projects": len({c.project_id for c in outcome.report.firebase_configs}),
    }


async def _handle_stheno_patch(nexus, project, stage) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Run APKPatcher with the patches from the stage parameters."""
    from pathlib import Path
    from mnexus.runtime.apk_patcher import APKPatcher, SUPPORTED_PATCHES

    apk_path = project.apk_path if isinstance(project.apk_path, Path) else Path(str(project.apk_path))
    if not apk_path.exists():
        return None
    patches = stage.get("patches") or list(SUPPORTED_PATCHES)
    if isinstance(patches, str):
        patches = [p.strip() for p in patches.split(",") if p.strip()]
    result = await APKPatcher(nexus.config).patch(apk_path, patches)
    return result.model_dump()


async def _handle_reporter_generate(nexus, project, stage) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Render markdown report for the project. Other formats can be
    added with stage.formats=[…]."""
    from pathlib import Path
    from mnexus.reporting.generator import ReportFormat, ReportGenerator, ReportTemplate

    out_dir = nexus.config.workspace / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    template_value = stage.get("template", "technical")
    formats = stage.get("formats") or ["markdown"]
    if isinstance(formats, str):
        formats = [formats]

    template = ReportTemplate(template_value) if isinstance(template_value, str) else template_value
    generator = ReportGenerator(project)
    paths: list[str] = []
    for fmt_str in formats:
        try:
            fmt = ReportFormat(fmt_str) if isinstance(fmt_str, str) else fmt_str
        except ValueError:
            continue
        ext = fmt.value if fmt.value != "markdown" else "md"
        path = out_dir / f"{project.id}-{template.value}.{ext}"
        generator.generate(template, fmt, str(path))
        paths.append(str(path))
    return {"paths": paths, "template": template.value}


async def _handle_frida_run_session(nexus, project, stage) -> dict[str, Any] | None:  # type: ignore[no-untyped-def]
    """Soft-skip — running a real Frida session needs a connected
    device and is better launched from the Dynamic tab."""
    _ = nexus, project, stage
    return None  # signals skipped


# Table-driven dispatch — adding a new (engine, action) pair is one entry.
_STAGE_HANDLERS: dict[tuple[str, str], StageHandler] = {
    ("apktool",   "decode"):              _handle_apktool_decode,
    ("jadx",      "decompile"):           _handle_jadx_decompile,
    ("mobsf",     "full_scan"):           _handle_mobsf_full_scan,
    ("ghidra",    "analyze_native_libs"): _handle_ghidra_native,
    ("playintel", "scan"):                _handle_playintel_scan,
    ("stheno",    "patch"):               _handle_stheno_patch,
    ("reporter",  "generate"):            _handle_reporter_generate,
    ("frida",     "run_session"):         _handle_frida_run_session,
}


# ─── executor ────────────────────────────────────────────────────────


def _normalise_stages(parsed: Any) -> list[dict[str, Any]]:
    """Flatten YAML stages into a list of single-step dicts.

    Pipeline YAML allows two shapes:

      stages:
        - name: intake
          engine: apktool
          action: decode

      stages:
        - name: static_scan
          parallel: true
          steps:
            - { engine: jadx,  action: decompile }
            - { engine: mobsf, action: full_scan }

    We flatten parallel groups into individual stages prefixed with
    the parent name so the run log reads chronologically. Parallelism
    is achieved by asyncio.gather inside the executor — declared
    parallelism is a hint we honor, not a hard requirement.
    """
    if not isinstance(parsed, dict):
        return []
    stages_raw = parsed.get("stages")
    if not isinstance(stages_raw, list):
        return []
    out: list[dict[str, Any]] = []
    for s in stages_raw:
        if not isinstance(s, dict):
            continue
        if s.get("steps") and isinstance(s["steps"], list):
            parent_name = s.get("name", "group")
            for i, child in enumerate(s["steps"]):
                if not isinstance(child, dict):
                    continue
                merged = {
                    **child,
                    "name": child.get("name", f"{parent_name}.{i}"),
                    "_parallel_group": parent_name if s.get("parallel") else None,
                }
                out.append(merged)
        else:
            out.append(dict(s))
    return out


async def execute_pipeline(nexus, project, pipeline_yaml: str, pipeline_name: str = "") -> PipelineRun:  # type: ignore[no-untyped-def]
    """Run every stage of ``pipeline_yaml`` against ``project``.

    Returns the completed ``PipelineRun``. Also registers it in
    ``pipeline_runs`` so the GET endpoint can fetch it by id.

    Failures in one stage don't abort subsequent stages — the run
    state is ``failed`` overall if any stage failed, ``ok`` otherwise.
    """
    import yaml

    run = PipelineRun(pipeline_name=pipeline_name, project_id=project.id, state="running")
    pipeline_runs[run.run_id] = run

    try:
        parsed = yaml.safe_load(pipeline_yaml) or {}
    except yaml.YAMLError as exc:
        run.state = "failed"
        run.error = f"YAML parse error: {exc}"
        run.finished_at = time.time()
        return run

    stages = _normalise_stages(parsed)
    if not stages:
        run.state = "failed"
        run.error = "pipeline declares no stages"
        run.finished_at = time.time()
        return run

    # Group stages by their parallel_group when present so we can
    # asyncio.gather them.
    groups: list[list[dict[str, Any]]] = []
    cur_group: list[dict[str, Any]] = []
    cur_key: Any = None
    for s in stages:
        key = s.get("_parallel_group")
        if key is not None and key == cur_key:
            cur_group.append(s)
        else:
            if cur_group:
                groups.append(cur_group)
            cur_group = [s]
            cur_key = key
    if cur_group:
        groups.append(cur_group)

    for group in groups:
        await asyncio.gather(*(_run_one_stage(nexus, project, run, stage_def) for stage_def in group))

    run.finished_at = time.time()
    any_failed = any(s.status == "failed" for s in run.stages)
    run.state = "failed" if any_failed else "ok"
    return run


async def _run_one_stage(nexus, project, run, stage_def) -> None:  # type: ignore[no-untyped-def]
    """Run one stage and append its outcome to ``run.stages``."""
    name = stage_def.get("name", "<unnamed>")
    engine = (stage_def.get("engine") or "").lower()
    action = (stage_def.get("action") or "").lower()
    outcome = StageOutcome(name=name, engine=engine, action=action, status="running")
    outcome.started_at = time.time()
    run.stages.append(outcome)

    handler = _STAGE_HANDLERS.get((engine, action))
    if handler is None:
        outcome.status = "skipped"
        outcome.error = f"no handler for {engine}/{action}"
        outcome.finished_at = time.time()
        outcome.duration_ms = int((outcome.finished_at - outcome.started_at) * 1000)
        return

    try:
        result = await handler(nexus, project, stage_def)
    except Exception as exc:  # noqa: BLE001 — surfacing the error onto the run is the point
        log.warning("pipeline stage '%s' failed: %s", name, exc)
        outcome.status = "failed"
        outcome.error = f"{exc.__class__.__name__}: {exc}"
        outcome.finished_at = time.time()
        outcome.duration_ms = int((outcome.finished_at - outcome.started_at) * 1000)
        return

    outcome.finished_at = time.time()
    outcome.duration_ms = int((outcome.finished_at - outcome.started_at) * 1000)
    if result is None:
        outcome.status = "skipped"
        outcome.error = outcome.error or "handler returned None — skipped"
    else:
        outcome.status = "ok"
        outcome.output = result
