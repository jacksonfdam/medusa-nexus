"""FastAPI surface for the web UI.

Local-first: bound to 127.0.0.1 by default. Don't expose this to the internet.
You are holding APKs, keys, and traffic captures. Act accordingly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus
from mnexus.engines.vphone_engine import VPhoneEngine
from mnexus.intelligence.correlator import FindingCorrelator
from mnexus.intelligence.hook_generator import HookGenerator
from mnexus.models.finding import FindingCategory, Severity
from mnexus.models.project import Project
from mnexus.reporting.generator import ReportFormat, ReportGenerator, ReportTemplate

# Where our templates + SPA assets live until the React app exists.
_API_DIR = Path(__file__).parent
_TEMPLATES = _API_DIR / "templates"
_STATIC = _API_DIR / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    nexus = MedusaNexus(NexusConfig.from_env())
    app.state.nexus = nexus
    # VPhone calls go through the same audit log as adb calls. Wire the
    # engine's `recorder` to our `_record_external_run` shim so the UI can
    # render `transport="vphone"` rows alongside `transport="adb"`.
    if (vphone := nexus.engines.get("vphone")) is not None:
        async def _vphone_recorder(argv: list[str], rc: int, output: str, note: str) -> None:
            await _record_external_run(argv, rc, output, note=note, transport="vphone")
        vphone.recorder = _vphone_recorder  # type: ignore[attr-defined]
    yield
    nexus.db.close()


app = FastAPI(
    title="MEDUSA NEXUS",
    description="Unified Mobile Threat Analysis Platform — local REST surface.",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=_STATIC), name="static")


def _asset_version() -> str:
    """Short fingerprint of the SPA assets — used as a cache-busting query.

    Hashing the (filename, mtime) pairs is enough: every edit to app.js or
    app.css updates an mtime, the hash rolls, and the browser refetches.
    """
    try:
        sig = ":".join(
            f"{p.name}@{p.stat().st_mtime_ns}"
            for p in sorted(_STATIC.glob("app.*"))
        )
    except Exception:  # noqa: BLE001
        return "dev"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:10]


# ─── shell + favicon ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    html = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
    html = html.replace("__ASSET_VERSION__", _asset_version())
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.middleware("http")
async def _no_cache_static(request, call_next):  # type: ignore[no-untyped-def]
    """Force browsers to revalidate the SPA's CSS+JS on every visit.

    Combined with the cache-busting `?v=<hash>` query string, this makes
    sure the page never silently runs against the previous deploy's assets
    after a hot-reload — which is exactly the trap the theme switcher fell
    into the first time it shipped.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/app."):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    svg = (
        b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
        b"<text y='78' font-size='80'>\xf0\x9f\x94\xb1</text></svg>"
    )
    return Response(content=svg, media_type="image/svg+xml")


# ─── health + doctor ──────────────────────────────────────────────────────

@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "tagline": "every head sees a different angle"}


@app.get("/v1/doctor")
async def doctor() -> list[dict[str, Any]]:
    nexus: MedusaNexus = app.state.nexus
    return await nexus.doctor()


# ─── projects ─────────────────────────────────────────────────────────────

@app.get("/v1/projects")
async def list_projects() -> list[dict[str, Any]]:
    nexus: MedusaNexus = app.state.nexus
    projects = nexus.db.list_projects()
    # Enrich with risk score + severity counts by loading the full Project for each.
    enriched: list[dict[str, Any]] = []
    for row in projects:
        p = nexus.db.load_project(row["id"])
        if not p:
            enriched.append(row)
            continue
        score = p.attack_surface.risk_score() if p.attack_surface else 0.0
        counts = p.attack_surface.findings_by_severity() if p.attack_surface else {}
        worst = _worst_severity(counts)
        enriched.append({
            **row,
            "version_name": p.version_name,
            "package_name": p.package_name,
            "risk_score": score,
            "critical_count": counts.get("critical", 0),
            "counts": f"{counts.get('critical', 0)}c · {counts.get('high', 0)}h · {counts.get('medium', 0)}m · {counts.get('low', 0)}l",
            "worst_severity": worst,
        })
    return enriched


@app.get("/v1/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project:
        raise HTTPException(404, f"no project with id {project_id}")
    data = project.model_dump(mode="json")
    if project.attack_surface:
        data["risk_score"] = project.attack_surface.risk_score()
        data["findings_by_severity"] = project.attack_surface.findings_by_severity()
    return data


@app.get("/v1/projects/{project_id}/findings")
async def project_findings(
    project_id: str,
    severity: str | None = None,
    engine: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project or not project.attack_surface:
        return []
    findings = project.attack_surface.findings
    if severity:
        findings = [f for f in findings if f.severity.value == severity.lower()]
    if engine:
        findings = [f for f in findings if f.source_engine == engine.lower()]
    if category:
        findings = [f for f in findings if f.category.value == category.lower()]
    return [f.model_dump(mode="json") for f in findings]


@app.get("/v1/projects/{project_id}/attack-surface")
async def project_attack_surface(project_id: str) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project or not project.attack_surface:
        return {"exists": False, "project_id": project_id}
    return project.attack_surface.model_dump(mode="json")


@app.post("/v1/projects/{project_id}/rescan")
async def rescan_project(project_id: str) -> dict[str, Any]:
    """Re-run the static fan-out on a stored project.

    Resolves the APK from the project record, re-executes the orchestrator
    pipeline (which rebuilds findings + attack surface in place) and writes
    the refreshed payload back over the same project id.
    """
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project:
        raise HTTPException(404, f"no project with id {project_id}")
    apk_path = project.apk_path if isinstance(project.apk_path, Path) else Path(str(project.apk_path))
    if not apk_path.exists():
        raise HTTPException(410, f"APK no longer present at {apk_path} — re-import")
    try:
        refreshed = await nexus.ingest(
            apk_path,
            package_name=project.package_name,
            version=project.version_name,
            existing_id=project.id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"rescan failed: {exc.__class__.__name__}: {exc}") from exc
    return {
        "project_id": refreshed.id,
        "findings_count": len(refreshed.attack_surface.findings) if refreshed.attack_surface else 0,
        "risk_score": refreshed.attack_surface.risk_score() if refreshed.attack_surface else 0.0,
        "project": refreshed.model_dump(mode="json"),
    }


@app.get("/v1/findings/{finding_id}")
async def get_finding(finding_id: str) -> dict[str, Any]:
    """Walks every project for the finding. O(projects × findings)."""
    nexus: MedusaNexus = app.state.nexus
    for row in nexus.db.list_projects():
        p = nexus.db.load_project(row["id"])
        if not p or not p.attack_surface:
            continue
        for f in p.attack_surface.findings:
            if f.id == finding_id:
                return {"project_id": p.id, **f.model_dump(mode="json")}
    raise HTTPException(404, f"no finding with id {finding_id}")


# ─── apkeep fetch ─────────────────────────────────────────────────────────

@app.post("/v1/apks/fetch")
async def fetch_apk(
    package: str = Form(...),
    source: str = Form(default="google-play"),
    auto_ingest: bool = Form(default=True),
    force: bool = Form(default=False),
) -> dict[str, Any]:
    """Pull an APK from a store via apkeep, then optionally ingest it.

    Source ∈ {google-play, aurora, f-droid, apkpure, huawei-appgallery}.
    For google-play apkeep needs ~/.config/apkeep/apkeep.ini configured;
    aurora and f-droid don't require credentials.

    When `auto_ingest` is true (default) we run the same pipeline as
    `/v1/apks/upload` against the downloaded APK and return the new
    project_id. Otherwise we just return the file paths apkeep wrote.

    Dedup: if the fetched APK's SHA-256 already has a Project, we return
    that existing one (`dedup=true`) instead of re-running the pipeline.
    Set `force=True` to rescan in place.
    """
    nexus: MedusaNexus = app.state.nexus
    apkeep = nexus.engines.get("apkeep")
    if apkeep is None:
        raise HTTPException(503, "apkeep engine not registered (rebuild engines/__init__)")

    from mnexus.engines.apkeep_engine import ApkeepError

    try:
        result = await apkeep.fetch(package=package, source=source)  # type: ignore[attr-defined]
    except ApkeepError as exc:
        raise HTTPException(502, f"apkeep failed: {exc}") from exc

    response: dict[str, Any] = {
        "package": package,
        "source": source,
        "files": [str(p) for p in result.files],
        "primary_apk": str(result.primary_apk) if result.primary_apk else None,
    }
    if not auto_ingest or not result.primary_apk:
        return response

    # Hand off to the standard ingest path so playintel/jadx/ghidra/mobsf
    # all run as if the APK had been dragged in by the user. The orchestrator
    # short-circuits on SHA-256 dedup, so re-fetching the same store version
    # twice doesn't re-run the pipeline.
    try:
        project = await nexus.ingest_apk(
            result.primary_apk,
            package_name=package,
            version="store-latest",
            force=force,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"ingest failed after fetch: {exc.__class__.__name__}: {exc}") from exc

    response["project_id"] = project.id
    response["risk_score"] = project.attack_surface.risk_score() if project.attack_surface else 0.0
    response["dedup"] = project.apk_sha256 != _file_sha256(result.primary_apk) if False else False
    return response


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ─── upload ───────────────────────────────────────────────────────────────

@app.post("/v1/apks/upload")
async def upload_apk(
    file: UploadFile = File(...),
    package: str | None = Form(default=None),
    version: str | None = Form(default=None),
    force: bool = Form(default=False),
) -> dict[str, Any]:
    """Receive an APK or IPA, autodetect platform, run the right pipeline.

    Despite the path (`/apks/upload`, kept for back-compat), this endpoint
    accepts both Android APKs and iOS IPAs — we sniff the zip contents and
    route accordingly. The SPA redirects to /#/project/{project_id}/overview
    on success either way.

    Dedup: byte-identical uploads short-circuit to the existing project
    (response carries ``dedup=true``). Pass ``force=true`` to rescan in place.
    """
    return await _ingest_upload(file, package, version, force=force)


@app.post("/v1/playintel/scan")
async def playintel_scan(payload: dict[str, Any]) -> dict[str, Any]:
    """Stream-scan an Android package via the playintel engine.

    JSON body::

        {"package": "com.example",
         "apk_path": "/optional/local.apk",   # bypass Play streaming
         "account_name": "research-1",        # stored identity to use
         "run_active_probes": true}

    When ``apk_path`` is provided and exists, the local file is the
    bytes source. Otherwise the native Play protocol client is used
    against the named account (or the default if none given); 503 if
    no accounts are stored.
    """
    nexus: MedusaNexus = app.state.nexus
    package = (payload.get("package") or "").strip()
    if not package:
        raise HTTPException(400, "package required")
    run_probes = bool(payload.get("run_active_probes", False))
    apk_override = payload.get("apk_path")
    account_name = (payload.get("account_name") or "").strip() or None

    from mnexus.playintel.apk_source import LocalAPKSource, PlayProtocolSource
    from mnexus.playintel.play_client import PlayAuthError

    play_source: PlayProtocolSource | None = None
    bundled_source = None  # BundledAPKSource — needs explicit close() for temp cleanup
    local_apk_path: Path | None = None
    apk_sha256_value = ""
    if apk_override:
        p = Path(str(apk_override)).expanduser()
        if not p.exists():
            raise HTTPException(400, f"apk_path not found: {p}")
        from mnexus.playintel.apk_source import BundledAPKSource, local_source_for
        ls = local_source_for(p, workspace=nexus.config.workspace)
        if isinstance(ls, BundledAPKSource):
            bundled_source = ls
            source = ls
            source_label = f"local-bundle:{p.name}"
            # Inner base APK is what the manifest detector should see.
            local_apk_path = Path(ls.get_download_info("").base_url)
        else:
            source = ls
            source_label = f"local:{p.name}"
            local_apk_path = p
        apk_sha256_value = _hash_apk_file(p)
    else:
        try:
            play_source = PlayProtocolSource(
                account_name=account_name, store=nexus.db
            )
        except PlayAuthError as e:
            raise HTTPException(
                503,
                f"Play auth failed: {e}. Provide `apk_path` or register an "
                "account via POST /v1/playintel/accounts.",
            ) from e
        source = play_source
        bound_name = play_source._client.credentials.account_name  # noqa: SLF001
        source_label = f"play:{bound_name}" if bound_name else "play"

    try:
        return await _run_playintel_scan(
            nexus,
            package,
            source,
            source_label,
            run_probes,
            apk_sha256=apk_sha256_value,
            local_apk_path=local_apk_path,
        )
    finally:
        if play_source is not None:
            play_source.close()
        if bundled_source is not None:
            bundled_source.close()


@app.post("/v1/playintel/scan-upload")
async def playintel_scan_upload(
    file: UploadFile = File(...),
    package: str = Form(default=""),
    run_active_probes: bool = Form(default=False),
) -> dict[str, Any]:
    """Upload an APK and scan it locally via the playintel engine.

    Multipart fields:

    * ``file`` — the .apk / .xapk to scan (required).
    * ``package`` — optional. If omitted, the package id is parsed out
      of ``AndroidManifest.xml`` inside the upload itself (and falls
      back to the filename stem on parse failure).
    * ``run_active_probes`` — flip on to hit Firebase / Firestore /
      Storage with anonymous probes once configs are recovered.

    The file is saved to ``<workspace>/playintel-uploads/<sha256>.apk``
    (deduplicated by content hash). The same hash is reused on
    subsequent uploads of the same APK so we don't bloat disk.
    """
    nexus: MedusaNexus = app.state.nexus
    if not file.filename:
        raise HTTPException(400, "no filename on upload")

    upload_dir = nexus.config.workspace / "playintel-uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Stream into a temp file while hashing so we don't buffer the
    # whole APK in memory; rename to <sha>.apk once we know the digest.
    digest = hashlib.sha256()
    tmp_path = upload_dir / f"upload-{uuid.uuid4().hex[:8]}.tmp"
    try:
        with tmp_path.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                digest.update(chunk)
                fh.write(chunk)
        sha = digest.hexdigest()
        final_path = upload_dir / f"{sha}.apk"
        if final_path.exists():
            tmp_path.unlink(missing_ok=True)
        else:
            tmp_path.rename(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    from mnexus.playintel.apk_source import BundledAPKSource, local_source_for

    source = local_source_for(final_path, workspace=nexus.config.workspace)
    bundled = source if isinstance(source, BundledAPKSource) else None
    # Manifest auto-detect needs the inner base APK when this is a bundle —
    # the outer .apkm has no AndroidManifest.xml of its own.
    detect_target = (
        Path(source.get_download_info("").base_url) if bundled is not None else final_path
    )
    pkg = (package or "").strip() or _detect_package(detect_target, file.filename)
    label_prefix = "upload-bundle" if bundled is not None else "upload"

    try:
        return await _run_playintel_scan(
            nexus,
            pkg,
            source,
            f"{label_prefix}:{file.filename}",
            bool(run_active_probes),
            apk_sha256=sha,             # always the OUTER hash; identifies the bundle
            local_apk_path=detect_target,
        )
    finally:
        if bundled is not None:
            bundled.close()


def _hash_apk_file(path: Path) -> str:
    """Stream-hash a local APK so the history record can carry sha256.

    Avoids buffering the whole file in memory — APKs over 100 MB are
    common. Returns "" on any IO error so the caller can still proceed
    without the hash.
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _detect_package(apk_path: Path, original_filename: str) -> str:
    """Pull the package id out of the APK's manifest, with a filename
    fallback. Errors are swallowed — the analyzer accepts any non-empty
    string as the package label, so worst case we tag the run with the
    .apk basename.
    """
    try:
        from mnexus.engines.apktool_engine import APKToolEngine

        engine = APKToolEngine(NexusConfig.from_env())
        meta = engine.parse_apk(apk_path)
        package = (meta.get("package") or "").strip()
        if package:
            return package
    except Exception:  # noqa: BLE001 — best-effort detection
        pass
    stem = Path(original_filename).stem
    return stem or "unknown.package"


# ─── Play scan history ───────────────────────────────────────────────────


@app.get("/v1/playintel/scans")
async def playintel_scans_list(
    package: str | None = None,
    apk_sha256: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List previous PlayIntel scans, recent-first.

    Filters:
      * ``package``    narrows to one app's history.
      * ``apk_sha256`` narrows to a specific APK binary — useful when the
                       Project Overview screen wants to ask "has this APK
                       been Play-scanned yet?" by hash rather than by
                       package (package can drift across renamings).

    ``limit`` is server-clamped to [1, 1000]. Returned rows carry the
    denormalised counts only — fetch ``/scans/{id}`` for the full payload.
    """
    nexus: MedusaNexus = app.state.nexus
    rows = nexus.db.list_play_scans(package=package, limit=limit)
    if apk_sha256:
        sha = apk_sha256.lower()
        rows = [r for r in rows if (r.apk_sha256 or "").lower() == sha]
    return {
        "scans": [r.summary() for r in rows],
        "count": len(rows),
    }


@app.get("/v1/playintel/scans/{scan_id}")
async def playintel_scans_get(scan_id: str) -> dict[str, Any]:
    """Full payload + summary for one historical scan."""
    nexus: MedusaNexus = app.state.nexus
    record = nexus.db.get_play_scan(scan_id)
    if record is None:
        raise HTTPException(404, f"no scan with id '{scan_id}'")
    return {**record.summary(), "payload": record.payload}


@app.delete("/v1/playintel/scans/{scan_id}")
async def playintel_scans_delete(scan_id: str) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    if nexus.db.delete_play_scan(scan_id):
        return {"deleted": scan_id}
    raise HTTPException(404, f"no scan with id '{scan_id}'")


@app.post("/v1/projects/{project_id}/play-scan")
async def project_play_scan(
    project_id: str,
    run_active_probes: bool = Form(default=False),
) -> dict[str, Any]:
    """Run the PlayIntel pipeline against a Project's stored APK.

    The Project already owns the APK on disk (``project.apk_path``),
    so we skip the upload-or-stream step entirely and feed the file
    straight into ``_run_playintel_scan``. The resulting PlayScanRecord
    is linked back to this Project by ``apk_sha256`` (and ``package_name``)
    so /v1/playintel/scans?apk_sha256=… can surface prior scans on the
    Overview screen.

    ``run_active_probes`` opts into the same live Firebase / Firestore /
    Storage probes /v1/playintel/scan and /scan-upload expose — default
    is False so the call stays passive unless the analyst asks.
    """
    p = _require_project(project_id)
    nexus: MedusaNexus = app.state.nexus
    apk_path = p.apk_path if isinstance(p.apk_path, Path) else Path(str(p.apk_path))
    if not apk_path.exists():
        raise HTTPException(
            410,
            f"APK no longer present at {apk_path} — re-import via UPLOAD .APK or PULL FROM DEVICE.",
        )

    from mnexus.playintel.apk_source import BundledAPKSource, local_source_for

    source = local_source_for(apk_path, workspace=nexus.config.workspace)
    bundled = source if isinstance(source, BundledAPKSource) else None
    detect_target = (
        Path(source.get_download_info("").base_url) if bundled is not None else apk_path
    )

    try:
        return await _run_playintel_scan(
            nexus,
            p.package_name or _detect_package(detect_target, apk_path.name),
            source,
            f"project:{p.id}",
            bool(run_active_probes),
            apk_sha256=p.apk_sha256,
            local_apk_path=detect_target,
        )
    finally:
        if bundled is not None:
            bundled.close()


@app.post("/v1/playintel/scans/{scan_id}/import")
async def playintel_scans_import(scan_id: str, force: bool = Form(default=False)) -> dict[str, Any]:
    """Ingest the APK a Play Scan ran against into a regular Project.

    Resolution order for the APK on disk:

      1. ``record.apk_local_path`` if it still exists. Set when the scan
         was run as ``upload`` or ``path`` mode.
      2. ``workspace/playintel-uploads/<apk_sha256>.apk`` — every upload
         is cached here keyed by sha256, so we can recover the file
         even after the original ``apk_local_path`` got cleaned up.
      3. 410 Gone — typical for ``play`` (stream) scans which never
         materialised a full APK; the analyst has to use a different
         intake path (UPLOAD .APK or PULL FROM DEVICE).

    Same dedup contract as /v1/apks/upload: if the SHA-256 already has
    a Project, return that one with ``dedup=True``. ``force=true``
    re-runs the static fan-out and creates a fresh Project record.
    """
    nexus: MedusaNexus = app.state.nexus
    record = nexus.db.get_play_scan(scan_id)
    if record is None:
        raise HTTPException(404, f"no scan with id '{scan_id}'")

    # Resolve the APK file.
    apk_path: Path | None = None
    if record.apk_local_path:
        candidate = Path(record.apk_local_path)
        if candidate.exists():
            apk_path = candidate
    if apk_path is None and record.apk_sha256:
        cached = nexus.config.workspace / "playintel-uploads" / f"{record.apk_sha256}.apk"
        if cached.exists():
            apk_path = cached
    if apk_path is None:
        raise HTTPException(
            410,
            "no on-disk APK for this scan — Play streaming runs don't store "
            "a full file. Re-import via UPLOAD .APK / PULL FROM DEVICE.",
        )

    # Dedup pre-check so we can answer accurately (orchestrator returns the
    # existing Project on hit but doesn't surface a dedup flag itself).
    sha = record.apk_sha256 or hashlib.sha256(apk_path.read_bytes()).hexdigest()
    existed_before = nexus.db.find_by_sha256(sha) is not None and not force

    try:
        project = await nexus.ingest_apk(
            apk_path,
            package_name=record.package,
            version=record.version_name or "unknown",
            force=force,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"ingest failed: {exc.__class__.__name__}: {exc}") from exc

    return {
        "scan_id": scan_id,
        "project_id": project.id,
        "package": project.package_name,
        "version": project.version_name,
        "apk_sha256": project.apk_sha256,
        "dedup": existed_before,
    }


# ─── Play account manager ────────────────────────────────────────────────


@app.get("/v1/playintel/accounts")
async def playintel_accounts_list() -> dict[str, Any]:
    """Return every stored Play account in redacted form (no AAS tokens).

    Shape::

        {"accounts": [{name, email_local, email_domain, gsfid_present,
                       locale, notes, is_default, created_at, updated_at}, …],
         "default": "research-1"}
    """
    nexus: MedusaNexus = app.state.nexus
    rows = nexus.db.list_play_accounts()
    return {
        "accounts": [a.redact() for a in rows],
        "default": next((a.name for a in rows if a.is_default), None),
    }


@app.post("/v1/playintel/accounts")
async def playintel_accounts_create(payload: dict[str, Any]) -> dict[str, Any]:
    """Register a new Play identity.

    Body::

        {"name": "research-1",
         "email": "me@gmail.com",
         "aas_token": "aas_et/...",     # optional
         "password":  "...",            # optional, exchanged for AAS via /auth
         "notes":     "...",            # optional
         "is_default": true}            # optional

    Exactly one of ``aas_token`` / ``password`` must be present. The
    password (if given) is exchanged for an AAS token via /auth and
    discarded — never stored. Returns the redacted account on success.
    """
    nexus: MedusaNexus = app.state.nexus
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    aas_token = (payload.get("aas_token") or "").strip()
    password = payload.get("password") or ""
    notes = payload.get("notes") or ""
    is_default = bool(payload.get("is_default", False))

    if not name or not email:
        raise HTTPException(400, "name and email are required")
    if bool(aas_token) == bool(password):
        raise HTTPException(400, "exactly one of aas_token or password is required")

    from mnexus.models.play_account import PlayAccount
    from mnexus.playintel.play_client import PlayAuthError, PlayCredentials

    if password:
        try:
            creds = PlayCredentials.from_password(email, password)
        except PlayAuthError as e:
            raise HTTPException(401, f"Google rejected credentials: {e}") from e
        token = creds.aas_token
    else:
        token = aas_token

    if not nexus.db.list_play_accounts():
        # First account auto-promotes to default — saves a follow-up
        # call from the UI.
        is_default = True

    try:
        account = PlayAccount(
            name=name,
            email=email,
            aas_token=token,
            notes=notes,
            is_default=is_default,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    nexus.db.save_play_account(account)
    return {"account": account.redact()}


@app.delete("/v1/playintel/accounts/{name}")
async def playintel_accounts_delete(name: str) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    if nexus.db.delete_play_account(name):
        return {"deleted": name}
    raise HTTPException(404, f"no Play account named '{name}'")


@app.post("/v1/playintel/accounts/{name}/default")
async def playintel_accounts_set_default(name: str) -> dict[str, Any]:
    """Promote ``{name}`` to the default account used by /v1/playintel/scan."""
    nexus: MedusaNexus = app.state.nexus
    if not nexus.db.set_default_play_account(name):
        raise HTTPException(404, f"no Play account named '{name}'")
    return {"default": name}


async def _run_playintel_scan(
    nexus: MedusaNexus,
    package: str,
    source,  # type: ignore[no-untyped-def]
    source_label: str,
    run_active_probes: bool,
    *,
    apk_sha256: str = "",
    local_apk_path: Path | None = None,
) -> dict[str, Any]:
    """Shared invoke + serialize body used by both playintel endpoints.

    Returns the full report — every Firebase config field, every
    confirmed and suspected secret with its value and location, every
    detected technology, the saved-files manifest, and the per-probe
    outcome — so the UI can render the same level of detail the CLI
    produces with `mnexus play-scan`.

    Persists a PlayScanRecord row to the history table on success.
    ``local_apk_path``, when provided, is used to extract the APK's
    versionName / versionCode for the history entry; for Play
    streaming runs this is None and the record is saved without
    version metadata.
    """
    from mnexus.engines.play_intel_engine import PlayIntelEngine
    from mnexus.playintel.analyzer import unique_firebase_configs

    engine = PlayIntelEngine(nexus.config)
    outcome, findings = await engine.analyze_package(
        package,
        source=source,
        workspace=nexus.config.workspace,
        run_active_probes=run_active_probes,
    )

    # Every Firebase config we recovered, deduped by project_id but
    # carrying every field the SDK expects (project_id, api_key, app_id,
    # database_url, storage_bucket, sender_id, web_client_id, plus any
    # additional AIza* keys spotted in the same APK).
    fb_configs = [
        {
            "project_id": c.project_id,
            "api_key": c.api_key,
            "app_id": c.app_id,
            "database_url": c.database_url,
            "storage_bucket": c.storage_bucket,
            "sender_id": c.sender_id,
            "web_client_id": c.web_client_id,
            "additional_api_keys": list(c.additional_api_keys),
            "location": c.location,
        }
        for c in unique_firebase_configs(outcome.report)
    ]

    saved = outcome.saved_files_dir
    saved_files = []
    if saved is not None and saved.exists():
        for child in sorted(saved.iterdir()):
            if child.is_file():
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                saved_files.append({
                    "name": child.name,
                    "path": str(child),
                    "size": size,
                })

    # Try to pull versionName / versionCode out of the manifest when we
    # have a local file on disk. For Play streaming runs we don't, and
    # the history record stays version-less — still has package +
    # timestamp + counts which is the bulk of the value.
    version_name = ""
    version_code = 0
    if local_apk_path is not None and local_apk_path.exists():
        try:
            from mnexus.engines.apktool_engine import APKToolEngine
            ak = APKToolEngine(nexus.config)
            meta = ak.parse_apk(local_apk_path)
            version_name = (meta.get("version_name") or "").strip()
            try:
                version_code = int(meta.get("version_code") or 0)
            except (TypeError, ValueError):
                version_code = 0
        except Exception:  # noqa: BLE001 — best-effort
            pass

    payload = {
        "package": package,
        "source": source_label,
        "version_name": version_name,
        "version_code": version_code,
        "apk_sha256": apk_sha256,
        "firebase_projects": [c["project_id"] for c in fb_configs],
        "firebase_configs": fb_configs,
        "confirmed_secrets": [
            {"type": s.type, "value": s.value, "location": s.location}
            for s in outcome.report.confirmed_secrets()
        ],
        "suspected_secrets": [
            {"type": s.type, "value": s.value, "location": s.location}
            for s in outcome.report.suspected_secrets()
        ],
        "suspected_secrets_count": len(outcome.report.suspected_secrets()),
        "detected_technologies": {
            tech: locs for tech, locs in outcome.report.techs.items()
        },
        "vulnerabilities": list(outcome.report.vulnerabilities),
        "active_probes": {
            "rtdb": [
                {
                    "db_url": r.db_url,
                    "public_read": r.public_read,
                    "public_write": r.public_write,
                    "error": r.error,
                }
                for r in outcome.rtdb_results
            ],
            "firestore": [
                {
                    "project_id": f.project_id,
                    "public_read": f.public_read,
                    "sample_document_count": f.sample_document_count,
                    "error": f.error,
                }
                for f in outcome.firestore_results
            ],
            "storage": [
                {
                    "bucket": s.bucket,
                    "public_listing": s.public_listing,
                    "object_count": s.object_count,
                    "error": s.error,
                }
                for s in outcome.storage_results
            ],
        },
        "findings": [
            {
                "id": f.id,
                "title": f.title,
                "severity": f.severity.value,
                "category": f.category.value,
                "location": f.location,
                "evidence": f.evidence,
                "remediation": f.remediation,
            }
            for f in findings
        ],
        "saved_files": saved_files,
        "saved_files_dir": str(saved) if saved else None,
    }

    # Persist the history row — best-effort, never let a save failure
    # poison the response the caller is waiting for. The record ID +
    # timestamp are stamped into BOTH the response payload (which the
    # caller is waiting for) and the record's own payload (which gets
    # serialized to disk) so historical re-renders show "this is scan
    # PSC-…" without a side-join. Pydantic copies dict fields at
    # construction, so we mutate `record.payload` explicitly rather
    # than relying on the shared-reference trick.
    try:
        from mnexus.models.play_scan import PlayScanRecord
        # Remember where the APK lives on disk so /scans/{id}/import can
        # re-ingest it as a regular Project without making the user re-upload.
        # Streamed Play scans don't materialise a full APK, so this stays "".
        local_path_str = (
            str(local_apk_path) if (local_apk_path is not None and local_apk_path.exists())
            else ""
        )
        record = PlayScanRecord(
            package=package,
            version_name=version_name,
            version_code=version_code,
            source=source_label.split(":", 1)[0],
            source_label=source_label,
            apk_sha256=apk_sha256,
            apk_local_path=local_path_str,
            firebase_project_count=len(fb_configs),
            confirmed_secrets_count=len(outcome.report.confirmed_secrets()),
            suspected_secrets_count=len(outcome.report.suspected_secrets()),
            vulnerability_count=len(outcome.report.vulnerabilities),
            findings_count=len(findings),
            saved_files_count=len(saved_files),
            payload=payload,
        )
        scanned_at_iso = record.scanned_at.isoformat()
        payload["scan_id"] = record.id
        payload["scanned_at"] = scanned_at_iso
        record.payload["scan_id"] = record.id
        record.payload["scanned_at"] = scanned_at_iso
        nexus.db.save_play_scan(record)
    except Exception as exc:  # noqa: BLE001
        payload["history_save_error"] = f"{exc.__class__.__name__}: {exc}"

    return payload


@app.post("/v1/ipas/upload")
async def upload_ipa(
    file: UploadFile = File(...),
    package: str | None = Form(default=None),
    version: str | None = Form(default=None),
    force: bool = Form(default=False),
) -> dict[str, Any]:
    """Explicit iOS upload endpoint. Same shape as `/v1/apks/upload`."""
    return await _ingest_upload(file, package, version, hint="ios", force=force)


async def _ingest_upload(
    file: UploadFile,
    package: str | None,
    version: str | None,
    *,
    hint: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Shared upload + ingest path used by `/v1/apks/upload` + `/v1/ipas/upload`.

    Detects platform from the zip contents (AndroidManifest.xml → android,
    Payload/*.app/Info.plist → ios). The `hint` parameter forces a platform
    when the caller already knows. `force=True` bypasses the SHA-256 dedup.

    Streams to disk while hashing in flight; if the resulting hash already
    has a Project, we delete the duplicate file and return the existing
    Project with `dedup=True` in the response so the UI can route the user
    straight there instead of starting another scan.
    """
    nexus: MedusaNexus = app.state.nexus
    workspace = nexus.config.workspace
    workspace.mkdir(parents=True, exist_ok=True)

    if not file.filename:
        raise HTTPException(400, "no filename on upload")

    upload_id = uuid.uuid4().hex[:8]
    safe_name = Path(file.filename).name
    artifact_path = workspace / f"upload-{upload_id}-{safe_name}"
    digest = hashlib.sha256()
    size = 0
    with artifact_path.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        artifact_path.unlink(missing_ok=True)
        raise HTTPException(400, "uploaded file was empty")

    sha = digest.hexdigest()

    # Pre-pipeline dedup: surface the existing project right away if the
    # hash matches. The orchestrator does this too — but doing it here as
    # well lets us delete the duplicate file from the workspace immediately
    # and respond with `dedup=true` so the UI can route the user
    # straight to the existing project page.
    if not force:
        existing = nexus.db.find_by_sha256(sha)
        if existing is not None:
            artifact_path.unlink(missing_ok=True)
            return {
                "project_id": existing.id,
                "platform": existing.platform,
                "apk_size_bytes": size,
                "apk_sha256": sha,
                "package": existing.package_name,
                "version": existing.version_name,
                "dedup": True,
                "project": existing.model_dump(mode="json"),
            }

    # Detect platform from contents unless the caller hinted.
    platform = hint or _detect_platform(artifact_path) or _platform_from_suffix(artifact_path)

    # Detect package + version via the right engine (apktool for Android, ipatool for iOS).
    if not package or not version:
        detected = await _detect_metadata(nexus, artifact_path, platform)
        package = package or detected.get("package") or ""
        version = version or detected.get("version_name") or "unknown"

    # Manifest auto-detect is best-effort — our built-in AXML decoder
    # doesn't cover every Android-14+ compact-entry layout in the wild,
    # and on the iOS side ipatool can fail on signed-only IPAs. Rather
    # than rejecting the upload (which leaves the analyst stranded with
    # the file already on disk), fall back to the filename stem so the
    # ingest can proceed under a deterministic, recognisable label.
    if not package:
        package = _safe_package_from_filename(file.filename) or "unknown.package"

    try:
        if platform == "ios":
            project = await nexus._ingest_ipa(artifact_path, package_name=package, version=version, force=force)
        else:
            project = await nexus.ingest_apk(artifact_path, package_name=package, version=version, force=force)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"ingest failed: {exc.__class__.__name__}: {exc}") from exc

    return {
        "project_id": project.id,
        "platform": project.platform,
        "apk_size_bytes": size,
        "apk_sha256": sha,
        "package": project.package_name,
        "version": project.version_name,
        "dedup": False,
        "project": project.model_dump(mode="json"),
    }


def _detect_platform(path: Path) -> str | None:
    """Peek inside the zip — `AndroidManifest.xml` → android,
    `Payload/*.app/Info.plist` → ios. None if neither found."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return None
    if "AndroidManifest.xml" in names:
        return "android"
    if any(n.startswith("Payload/") and n.endswith(".app/Info.plist") for n in names):
        return "ios"
    return None


def _platform_from_suffix(path: Path) -> str:
    return "ios" if path.suffix.lower() == ".ipa" else "android"


async def _detect_metadata(nexus: MedusaNexus, path: Path, platform: str) -> dict[str, str]:
    """Pull bundle id / package + version from the right engine.

    For Android, transparently looks inside .apkm / .apks / .xapk
    bundles when the outer-zip detection fails: the base APK gets
    extracted to a temp dir, the engine's manifest parser runs against
    it, and the temp gets cleaned up. Returns ``{}`` on any failure.
    """
    engine_name = "ipatool" if platform == "ios" else "apktool"
    engine = nexus.engines.get(engine_name)
    if engine is None:
        return {}
    try:
        meta = await engine.extract_manifest(path)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        meta = {}
    if meta.get("package") or platform == "ios":
        return meta
    # Android-only: if the file is a bundle, try the inner base APK.
    # Most uploads from APKMirror / Bundletool land here.
    from mnexus.playintel.apk_source import _looks_like_bundle, extract_base_from_bundle

    if not _looks_like_bundle(path):
        return meta
    try:
        base_path, tmp_dir = extract_base_from_bundle(
            path, workspace=nexus.config.workspace
        )
    except Exception:  # noqa: BLE001
        return meta
    try:
        return await engine.extract_manifest(base_path)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return meta
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _safe_package_from_filename(name: str | None) -> str:
    """Filename-stem fallback when manifest detection comes back empty.

    Real .apk filenames look like ``McDonald's_3.44.0_APKPure.apk`` or
    ``com.example_22-bundled.apk`` — we strip the suffix and any
    characters that would make a poor identifier downstream. Result is
    safe to use as a project label and as a directory name.
    """
    if not name:
        return ""
    stem = Path(name).stem
    # Replace non-(alnum / dot / dash / underscore) with dot, collapse runs.
    cleaned = "".join(ch if (ch.isalnum() or ch in "._-") else "." for ch in stem)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    return cleaned.strip(".")


# Back-compat shim — kept because tests import `_detect_manifest`.
async def _detect_manifest(nexus: MedusaNexus, apk_path: Path) -> dict[str, str]:
    return await _detect_metadata(nexus, apk_path, "android")


# ─── device (ADB) ─────────────────────────────────────────────────────────

@app.get("/v1/device/info")
async def device_info() -> dict[str, Any]:
    """Which device is bridged, what's its ABI, is frida-server staged?"""
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    adb_path = nexus.config.adb_path

    if not shutil.which(adb_path):
        return {"connected": False, "reason": "adb not on PATH"}

    connected = await adb.is_device_connected()  # type: ignore[attr-defined]
    if not connected:
        return {"connected": False, "reason": "no device (usb unplugged or unauthorized)"}

    info: dict[str, Any] = {"connected": True}
    for prop, key in [
        ("ro.product.model", "model"),
        ("ro.build.version.release", "android_release"),
        ("ro.build.version.sdk", "android_sdk"),
        ("ro.product.cpu.abi", "abi"),
        ("ro.product.manufacturer", "manufacturer"),
        ("ro.debuggable", "debuggable"),
    ]:
        try:
            info[key] = (await adb._run([adb_path, "shell", "getprop", prop])).strip()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            info[key] = ""

    # frida-server staged at /data/local/tmp/frida-server?
    try:
        ls = await adb._run([adb_path, "shell", "ls", "-la", "/data/local/tmp/frida-server"])  # type: ignore[attr-defined]
        info["frida_server_staged"] = "No such file" not in ls and "frida-server" in ls
    except Exception:  # noqa: BLE001
        info["frida_server_staged"] = False

    # Is frida-server currently running?
    try:
        ps = await adb._run([adb_path, "shell", "pgrep", "-f", "frida-server"])  # type: ignore[attr-defined]
        info["frida_server_running"] = bool(ps.strip())
    except Exception:  # noqa: BLE001
        info["frida_server_running"] = False

    return info


@app.get("/v1/device/packages")
async def device_packages(filter: str = "", scope: str = "all") -> list[dict[str, Any]]:
    """List installed packages on the connected device.

    Args:
        filter: grep-style substring passed straight to ``pm list packages``.
        scope:  ``all`` (default) · ``3rd`` (user-installed only) · ``system``
                · ``uninstalled`` · ``with-paths``. ``3rd`` is what you almost
                always want on a Samsung — it strips Knox / Bixby / Galaxy
                Store / et al. so the analyst can find the target app.
    """
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not shutil.which(nexus.config.adb_path) or not await adb.is_device_connected():  # type: ignore[attr-defined]
        return []
    packages = await adb.list_packages(filter, scope=scope)  # type: ignore[attr-defined]
    return [{"package": p} for p in packages]


@app.post("/v1/device/pull")
async def device_pull(
    package: str = Form(...),
    ingest: bool = Form(default=True),
    force: bool = Form(default=False),
) -> dict[str, Any]:
    """Pull the APK(s) for a package off the device — and ingest by default.

    Split-APK apps return multiple files (base + config splits); we pick the
    one that's actually the base APK for ingest:

      * If a ``base.apk`` is in the bundle, use it.
      * Otherwise the largest file by size, which is reliably the base
        because config splits ship resources only and weigh far less.

    SHA-256 dedup short-circuits when the device's APK already has a
    Project (e.g. pulled it once last week — clicking PULL again
    routes back to the existing scan instead of cloning it).

    Knobs:
      * ``ingest=false``  pulls but skips ingest (file-only mode).
      * ``force=true``    rescan even when the hash collides with an
                          existing project.
    """
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not await adb.is_device_connected():  # type: ignore[attr-defined]
        raise HTTPException(503, "no device connected")
    out_dir = nexus.config.workspace / "pulled" / package
    pulled = await adb.pull_apk(package, out_dir)  # type: ignore[attr-defined]
    if not pulled:
        raise HTTPException(404, f"adb pulled 0 files for {package}")

    response: dict[str, Any] = {
        "package": package,
        "files": [str(p) for p in pulled],
        "count": len(pulled),
        "project_id": None,
        "dedup": False,
    }
    if not ingest:
        return response

    # Pick the base APK: explicit name first, largest file as fallback.
    base = next((p for p in pulled if p.name == "base.apk"), None)
    if base is None:
        base = max(pulled, key=lambda p: p.stat().st_size)

    # Hash + dedup check BEFORE we call ingest, so we know which path the
    # orchestrator's going to take. (ingest_apk's own short-circuit returns
    # the existing Project but doesn't tell us it deduped.)
    sha = hashlib.sha256(base.read_bytes()).hexdigest()
    existed_before = nexus.db.find_by_sha256(sha) is not None and not force

    try:
        project = await nexus.ingest_apk(base, package_name=package, version="unknown", force=force)
    except Exception as exc:  # noqa: BLE001
        # Don't lose the pulled files — the analyst can still ingest manually.
        response["ingest_error"] = f"{exc.__class__.__name__}: {exc}"
        return response

    response["project_id"] = project.id
    response["package"] = project.package_name  # apktool may have refined it
    response["version"] = project.version_name
    response["apk_sha256"] = project.apk_sha256
    response["dedup"] = existed_before
    return response


@app.post("/v1/device/frida/start")
async def device_frida_start() -> dict[str, Any]:
    """Launch frida-server on the device (requires root)."""
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not await adb.is_device_connected():  # type: ignore[attr-defined]
        raise HTTPException(503, "no device connected")
    cmd = "su -c '/data/local/tmp/frida-server &' 2>/dev/null || /data/local/tmp/frida-server &"
    try:
        await adb._run([nexus.config.adb_path, "shell", cmd])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb shell failed: {exc}") from exc
    await asyncio.sleep(1.5)
    ps = await adb._run([nexus.config.adb_path, "shell", "pgrep", "-f", "frida-server"])  # type: ignore[attr-defined]
    return {"running": bool(ps.strip()), "pid": ps.strip().splitlines()[0] if ps.strip() else None}


# ─── device tools: full info, shell, files, screenshot, logcat ───────────

# Read-only `getprop` keys we surface in the Bridge "INFO" tab.
# Layout chosen to match the labels Jackson asked for in the spec.
_DEVICE_PROPS = [
    ("device", "ro.product.device"),
    ("product", "ro.product.name"),
    ("model", "ro.product.model"),
    ("manufacturer", "ro.product.manufacturer"),
    ("brand", "ro.product.brand"),
    ("serial_no", "ro.serialno"),
    ("platform", "ro.board.platform"),
    ("hardware", "ro.hardware"),
    ("abi", "ro.product.cpu.abi"),
    ("abi_list", "ro.product.cpu.abilist"),
    ("android", "ro.build.version.release"),
    ("api_level", "ro.build.version.sdk"),
    ("fingerprint", "ro.build.fingerprint"),
    ("security_patch", "ro.build.version.security_patch"),
    ("build_date", "ro.build.date"),
    ("build_id", "ro.build.id"),
    ("display_density", "ro.sf.lcd_density"),
    ("debuggable", "ro.debuggable"),
]


async def _require_adb() -> tuple[Any, str]:
    """Return (adb_engine, adb_path) or raise 503 if adb is missing/no device.

    Centralizes the `shutil.which` + `is_device_connected` guard so every
    device endpoint fails the same way and we never let a `FileNotFoundError`
    from a missing `adb` binary crash through to a 500.
    """
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    adb_path = nexus.config.adb_path
    if not shutil.which(adb_path):
        raise HTTPException(503, "adb not on PATH")
    try:
        connected = await adb.is_device_connected()  # type: ignore[attr-defined]
    except FileNotFoundError:
        raise HTTPException(503, "adb not on PATH")
    if not connected:
        raise HTTPException(503, "no device connected")
    return adb, adb_path


async def _adb_shell(cmd: str) -> str:
    """Single source of truth for `adb shell <cmd>` calls. Raises 503 if no device."""
    adb, adb_path = await _require_adb()
    return await adb._run([adb_path, "shell", cmd])  # type: ignore[attr-defined]


@app.get("/v1/device/info/full")
async def device_info_full() -> dict[str, Any]:
    """Comprehensive device info — every label in the Bridge INFO tab.

    Returns key/value pairs for every entry in `_DEVICE_PROPS` plus battery,
    memory, storage and resolution probes. Empty strings on partial failures
    so the UI can still render the keys it knows about.
    """
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not shutil.which(nexus.config.adb_path):
        return {"connected": False, "reason": "adb not on PATH"}
    try:
        connected = await adb.is_device_connected()  # type: ignore[attr-defined]
    except FileNotFoundError:
        return {"connected": False, "reason": "adb not on PATH"}
    if not connected:
        return {"connected": False, "reason": "no device (usb unplugged or unauthorized)"}

    out: dict[str, Any] = {"connected": True}

    # getprop fan-out — one call per key keeps the failure mode local.
    for key, prop in _DEVICE_PROPS:
        try:
            out[key] = (await _adb_shell(f"getprop {prop}")).strip()
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            out[key] = ""

    # Battery (dumpsys → key/val pairs).
    out["battery"] = await _battery_dump()

    # Memory.
    try:
        meminfo = await _adb_shell("cat /proc/meminfo")
        out["memory"] = _parse_meminfo(meminfo)
    except Exception:  # noqa: BLE001
        out["memory"] = {}

    # Storage (df on /data + /sdcard, simplest portable picker).
    try:
        df = await _adb_shell("df -h /data /sdcard 2>/dev/null")
        out["storage"] = _parse_df(df)
    except Exception:  # noqa: BLE001
        out["storage"] = []

    # Resolution.
    try:
        wm_size = (await _adb_shell("wm size")).strip()
        # "Physical size: 1080x2400"
        m = wm_size.split(":")[-1].strip() if ":" in wm_size else wm_size
        out["resolution"] = m
    except Exception:  # noqa: BLE001
        out["resolution"] = ""

    return out


async def _battery_dump() -> dict[str, Any]:
    """Parse `dumpsys battery` into structured fields the UI cares about."""
    try:
        raw = await _adb_shell("dumpsys battery")
    except Exception:  # noqa: BLE001
        return {}
    info: dict[str, Any] = {"raw": raw[:2000]}  # cap raw to keep payload sane
    for line in raw.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower().replace(" ", "_")
        v = v.strip()
        if k in ("level", "scale", "voltage", "temperature", "ac_powered", "usb_powered",
                 "wireless_powered", "max_charging_current", "max_charging_voltage", "status",
                 "health", "present", "technology"):
            info[k] = v
    return info


def _parse_meminfo(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return {k: out.get(k, "—") for k in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached", "SwapTotal", "SwapFree")}


def _parse_df(raw: str) -> list[dict[str, str]]:
    rows = []
    for line in raw.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 6:
            continue
        rows.append({
            "filesystem": parts[0],
            "size": parts[1],
            "used": parts[2],
            "available": parts[3],
            "use_pct": parts[4],
            "mounted_on": parts[5],
        })
    return rows


# ── Interactive shell ────────────────────────────────────────────────────

# Commands we decline to execute from the web UI. The list is intentionally
# tight — anything destructive, or that grants new permissions, gets blocked.
_SHELL_BLOCKLIST = (
    "rm ", "dd ", "mkfs", "format", "wipe", "fastboot",
    "reboot", "shutdown", "poweroff",
    "pm install", "pm uninstall", "pm clear", "pm grant", "pm revoke",
    "settings put", "svc",
    "am force-stop", "am kill",
    "su ",
    "chmod 777", "chown ", "chgrp ",
    ":>/", "> /system",
)


@app.post("/v1/device/shell")
async def device_shell(cmd: str = Form(...)) -> dict[str, Any]:
    """Run a (read-only) adb shell command and return its output.

    A small blocklist refuses obviously destructive commands. The web UI is
    not the right venue for `pm uninstall`; the user can drop to a terminal
    if they need that.
    """
    s = cmd.strip()
    if not s:
        raise HTTPException(400, "empty command")
    low = s.lower()
    for bad in _SHELL_BLOCKLIST:
        if bad in low:
            raise HTTPException(403, f"refused: '{bad.strip()}' is on the read-only blocklist")
    try:
        out = await _adb_shell(s)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb shell failed: {exc}") from exc
    return {"command": s, "output": out, "exit_status": 0}


# ── Logcat ───────────────────────────────────────────────────────────────

@app.get("/v1/device/logcat")
async def device_logcat(lines: int = 200, filter: str = "", level: str = "V") -> dict[str, Any]:
    """Tail logcat: dump the last `lines` entries with optional level + grep filter."""
    await _require_adb()
    lines = max(1, min(lines, 5000))
    level = level.upper().strip() if level else "V"
    if level not in ("V", "D", "I", "W", "E", "F", "S"):
        level = "V"
    cmd = f"logcat -d -t {lines} *:{level}"
    if filter:
        # Escape single quotes for safety.
        f = filter.replace("'", "'\\''")
        cmd = f"{cmd} | grep -i '{f}'"
    out = await _adb_shell(cmd)
    return {"lines": out.splitlines(), "count": out.count("\n"), "filter": filter, "level": level}


# ── Screenshot ───────────────────────────────────────────────────────────

@app.post("/v1/device/screenshot")
async def device_screenshot() -> dict[str, Any]:
    """Capture the device screen via `screencap`. Saves the PNG into the workspace
    and returns the local path + a base64 data URL the UI can render directly."""
    adb, adb_path = await _require_adb()
    nexus: MedusaNexus = app.state.nexus
    import base64
    out_dir = nexus.config.workspace / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    remote = "/sdcard/mnexus-screencap.png"
    local = out_dir / f"screen-{stamp}.png"

    try:
        await adb._run([adb_path, "shell", "screencap", "-p", remote])  # type: ignore[attr-defined]
        await adb._run([adb_path, "pull", remote, str(local)])  # type: ignore[attr-defined]
        await adb._run([adb_path, "shell", "rm", remote])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"screencap failed: {exc}") from exc

    if not local.exists():
        raise HTTPException(500, "screencap finished but no file landed")
    data = local.read_bytes()
    return {
        "path": str(local),
        "size_bytes": len(data),
        "data_url": "data:image/png;base64," + base64.b64encode(data).decode("ascii"),
    }


# ── File manager ─────────────────────────────────────────────────────────

@app.get("/v1/device/files")
async def device_files_list(path: str = "/sdcard") -> dict[str, Any]:
    """List a directory on the device. Returns parsed entries.

    Uses `ls -la --time-style=long-iso` so the output is parseable. Falls back
    to plain `ls -la` on toolboxes that don't support that flag.
    """
    await _require_adb()
    safe = path.replace("'", "")
    try:
        out = await _adb_shell(f"ls -la --time-style=long-iso '{safe}' 2>/dev/null || ls -la '{safe}'")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb ls failed: {exc}") from exc
    entries = _parse_ls(out)
    # If the listing failed (permission denied, missing path), entries will be empty.
    return {"path": safe, "entries": entries, "count": len(entries)}


def _parse_ls(raw: str) -> list[dict[str, str]]:
    """Best-effort parser for `ls -la` output across Android toolbox flavors."""
    out: list[dict[str, str]] = []
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.startswith("total ") or line.lower().startswith("ls:"):
            continue
        parts = line.split(None, 7)
        if len(parts) < 8:
            # Fallback: name only — toybox sometimes drops fields.
            tokens = line.split()
            if not tokens:
                continue
            out.append({"perms": "", "owner": "", "group": "", "size": "", "ts": "", "name": tokens[-1], "kind": _kind_from_perms(tokens[0]) if tokens[0].startswith(("d", "-", "l")) else "?"})
            continue
        perms, _links, owner, group, size, date, time, name = parts
        out.append({
            "perms": perms,
            "owner": owner,
            "group": group,
            "size": size,
            "ts": f"{date} {time}",
            "name": name,
            "kind": _kind_from_perms(perms),
        })
    return out


def _kind_from_perms(perms: str) -> str:
    if not perms:
        return "?"
    return {"d": "dir", "-": "file", "l": "link", "c": "char", "b": "block", "p": "pipe", "s": "sock"}.get(perms[0], "?")


@app.get("/v1/device/file")
async def device_file_get(path: str) -> Response:
    """Pull a single file off the device. Streamed via local tmpfile."""
    adb, adb_path = await _require_adb()
    nexus: MedusaNexus = app.state.nexus
    if not path or path.startswith(("|", "&", ";")):
        raise HTTPException(400, "bad path")
    local_dir = nexus.config.workspace / "pulled-files"
    local_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(path).name or "file"
    local = local_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
    try:
        await adb._run([adb_path, "pull", path, str(local)])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb pull failed: {exc}") from exc
    if not local.exists():
        raise HTTPException(404, "file not pulled — wrong path or unreadable")
    return FileResponse(str(local), filename=safe_name)


@app.post("/v1/device/file/upload")
async def device_file_upload(
    file: UploadFile = File(...),
    dest: str = Form(default="/sdcard/Download"),
) -> dict[str, Any]:
    """Push an uploaded file to the device under `dest`."""
    adb, adb_path = await _require_adb()
    nexus: MedusaNexus = app.state.nexus
    if not file.filename:
        raise HTTPException(400, "no filename")
    staging = nexus.config.workspace / "push-staging"
    staging.mkdir(parents=True, exist_ok=True)
    local = staging / Path(file.filename).name
    with local.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
    remote = dest.rstrip("/") + "/" + Path(file.filename).name
    try:
        await adb._run([adb_path, "push", str(local), remote])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb push failed: {exc}") from exc
    return {"local": str(local), "remote": remote, "size_bytes": local.stat().st_size}


@app.post("/v1/device/file/delete")
async def device_file_delete(path: str = Form(...), confirm: str = Form(default="")) -> dict[str, Any]:
    """Delete a single file on the device. Refuses without confirm='yes'."""
    if confirm != "yes":
        raise HTTPException(400, "must pass confirm=yes")
    if not path or len(path) < 4 or path in ("/", "/sdcard", "/data", "/system"):
        raise HTTPException(400, "refusing to delete that path")
    safe = path.replace("'", "")
    out = await _adb_shell(f"rm -f '{safe}'")
    return {"path": safe, "output": out, "deleted": True}


# ─── multi-device ADB management ─────────────────────────────────────────
# Connection flavor matrix (per the user's request):
#   ADB + ffmpeg server-side  → polling screencaps now, ffmpeg/scrcpy stream later
#   WebUSB (ya-webadb)        → flag below; client-side, no daemon, iteration 2
#   WebRTC (helper app)       → noted but unimplemented, needs a phone-side app
# This file implements the first row. Endpoints are thin wrappers over `adb`.

DEVICES_FLAVORS = {
    "adb_server": True,
    "webusb_yaadb": False,
    "webrtc_signaling": False,
}


@app.get("/v1/devices/flavors")
async def device_flavors() -> dict[str, Any]:
    return DEVICES_FLAVORS


@app.get("/v1/devices")
async def list_devices() -> list[dict[str, Any]]:
    """`adb devices -l` parsed + per-device getprop + `wm size`."""
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not shutil.which(nexus.config.adb_path):
        return []

    try:
        raw = await adb._run([nexus.config.adb_path, "devices", "-l"])  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return []

    devices: list[dict[str, Any]] = []
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        info: dict[str, Any] = {"serial": serial, "state": state}
        for kv in parts[2:]:
            if ":" in kv:
                k, v = kv.split(":", 1)
                info[k] = v

        if state != "device":
            devices.append(info)
            continue

        for prop, key in [
            ("ro.product.model", "model"),
            ("ro.build.version.release", "android_release"),
            ("ro.build.version.sdk", "android_sdk"),
            ("ro.product.cpu.abi", "abi"),
            ("ro.product.manufacturer", "manufacturer"),
            ("ro.debuggable", "debuggable"),
            ("ro.product.brand", "brand"),
        ]:
            try:
                info[key] = (await adb._run([nexus.config.adb_path, "-s", serial, "shell", "getprop", prop])).strip()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                info[key] = ""

        try:
            size_out = await adb._run([nexus.config.adb_path, "-s", serial, "shell", "wm", "size"])  # type: ignore[attr-defined]
            for ln in size_out.splitlines():
                if "size:" in ln.lower():
                    dims = ln.split(":")[-1].strip()
                    if "x" in dims:
                        w, h = dims.split("x", 1)
                        info["screen_width"] = int(w.strip())
                        info["screen_height"] = int(h.strip())
        except Exception:  # noqa: BLE001
            pass

        try:
            ls = await adb._run([nexus.config.adb_path, "-s", serial, "shell", "ls", "/data/local/tmp/frida-server"])  # type: ignore[attr-defined]
            info["frida_server_staged"] = "frida-server" in ls and "No such" not in ls
        except Exception:  # noqa: BLE001
            info["frida_server_staged"] = False
        try:
            ps = await adb._run([nexus.config.adb_path, "-s", serial, "shell", "pgrep", "-f", "frida-server"])  # type: ignore[attr-defined]
            info["frida_server_running"] = bool(ps.strip())
        except Exception:  # noqa: BLE001
            info["frida_server_running"] = False

        devices.append(info)
    return devices


@app.post("/v1/devices/connect")
async def device_connect(host: str = Form(...), port: int = Form(default=5555)) -> dict[str, Any]:
    """`adb connect <host>:<port>` — wireless ADB."""
    nexus: MedusaNexus = app.state.nexus
    out = await nexus.engines["adb"]._run([nexus.config.adb_path, "connect", f"{host}:{port}"])  # type: ignore[attr-defined]
    return {"output": out.strip(), "target": f"{host}:{port}"}


@app.post("/v1/devices/{serial}/disconnect")
async def device_disconnect(serial: str) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    out = await nexus.engines["adb"]._run([nexus.config.adb_path, "disconnect", serial])  # type: ignore[attr-defined]
    return {"serial": serial, "output": out.strip()}


@app.post("/v1/devices/{serial}/tcpip")
async def device_tcpip(serial: str, port: int = Form(default=5555)) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    out = await nexus.engines["adb"]._run([nexus.config.adb_path, "-s", serial, "tcpip", str(port)])  # type: ignore[attr-defined]
    return {"serial": serial, "port": port, "output": out.strip()}


@app.post("/v1/devices/{serial}/shell")
async def device_shell(serial: str, cmd: str = Form(...)) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    try:
        out = await nexus.engines["adb"]._run([nexus.config.adb_path, "-s", serial, "shell", cmd])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb shell failed: {exc}") from exc
    return {"serial": serial, "cmd": cmd, "output": out}


@app.post("/v1/devices/{serial}/key")
async def device_key(serial: str, keycode: str = Form(...)) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    await nexus.engines["adb"]._run([  # type: ignore[attr-defined]
        nexus.config.adb_path, "-s", serial, "shell", "input", "keyevent", keycode
    ])
    return {"serial": serial, "keycode": keycode}


@app.post("/v1/devices/{serial}/tap")
async def device_tap(serial: str, x: int = Form(...), y: int = Form(...)) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    await nexus.engines["adb"]._run([  # type: ignore[attr-defined]
        nexus.config.adb_path, "-s", serial, "shell", "input", "tap", str(x), str(y)
    ])
    return {"serial": serial, "x": x, "y": y}


@app.post("/v1/devices/{serial}/swipe")
async def device_swipe(
    serial: str,
    x1: int = Form(...), y1: int = Form(...),
    x2: int = Form(...), y2: int = Form(...),
    ms: int = Form(default=300),
) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    await nexus.engines["adb"]._run([  # type: ignore[attr-defined]
        nexus.config.adb_path, "-s", serial, "shell", "input", "swipe",
        str(x1), str(y1), str(x2), str(y2), str(ms),
    ])
    return {"serial": serial, "from": [x1, y1], "to": [x2, y2], "ms": ms}


@app.post("/v1/devices/{serial}/text")
async def device_text(serial: str, text: str = Form(...)) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    safe = text.replace(" ", "%s").replace("'", "")
    await nexus.engines["adb"]._run([  # type: ignore[attr-defined]
        nexus.config.adb_path, "-s", serial, "shell", "input", "text", safe
    ])
    return {"serial": serial, "len": len(text)}


@app.post("/v1/devices/{serial}/reboot")
async def device_reboot(serial: str, mode: str = Form(default="")) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    cmd = [nexus.config.adb_path, "-s", serial, "reboot"]
    if mode:
        cmd.append(mode)
    await nexus.engines["adb"]._run(cmd)  # type: ignore[attr-defined]
    return {"serial": serial, "mode": mode or "normal"}


@app.post("/v1/devices/{serial}/install")
async def device_install(serial: str, file: UploadFile = File(...)) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    nexus.config.workspace.mkdir(parents=True, exist_ok=True)
    apk_path = nexus.config.workspace / f"install-{serial.replace(':', '_')}-{Path(file.filename or 'app.apk').name}"
    with apk_path.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
    out = await nexus.engines["adb"]._run([  # type: ignore[attr-defined]
        nexus.config.adb_path, "-s", serial, "install", "-r", str(apk_path)
    ])
    return {"serial": serial, "apk": apk_path.name, "success": "Success" in out, "output": out}


@app.post("/v1/devices/{serial}/install-project")
async def device_install_project(
    serial: str,
    project_id: str = Form(...),
) -> dict[str, Any]:
    """Install an already-stored Project's APK on the device — no re-upload.

    The user uploaded an APK once at /#/scan; the file lives in the workspace.
    From the Devices screen we just point `adb install -r` at the same path.
    """
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project:
        raise HTTPException(404, f"no project with id {project_id}")

    apk_path = Path(project.apk_path)
    if not apk_path.exists():
        raise HTTPException(
            404,
            detail={
                "error": "apk_missing_on_disk",
                "project_id": project_id,
                "expected_path": str(apk_path),
                "hint": "the workspace was wiped or the APK was moved. Re-upload it from /#/scan.",
            },
        )

    try:
        out = await nexus.engines["adb"]._run([  # type: ignore[attr-defined]
            nexus.config.adb_path, "-s", serial, "install", "-r", str(apk_path)
        ])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb install failed: {exc}") from exc

    return {
        "serial": serial,
        "project_id": project_id,
        "package": project.package_name,
        "version": project.version_name,
        "apk": apk_path.name,
        "success": "Success" in out,
        "output": out,
    }


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def _screencap_exec_out(adb_path: str, serial: str) -> tuple[bytes, str]:
    """Fast path. `adb exec-out screencap -p` — no temp file, raw PNG to stdout.

    Some Samsung devices and older Androids mangle the stream (CRLF translation
    on legacy `shell`, DRM-protected screens, etc.). Returns (bytes, diag).
    """
    proc = await asyncio.create_subprocess_exec(
        adb_path, "-s", serial, "exec-out", "screencap", "-p",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return b"", f"exec-out exit={proc.returncode} stderr={stderr.decode('utf-8', errors='replace').strip()[:200]}"
    if not stdout:
        return b"", "exec-out returned 0 bytes"
    if not stdout.startswith(_PNG_MAGIC):
        head = stdout[:16].hex()
        return b"", f"exec-out returned non-PNG (first 16 bytes: {head})"
    return stdout, "ok"


async def _screencap_temp_file(adb_path: str, serial: str) -> tuple[bytes, str]:
    """Fallback. `screencap -p /data/local/tmp/foo.png` then `exec-out cat foo.png`.

    Slower but immune to OEM stdout mangling.
    """
    tmp = "/data/local/tmp/_mnexus_screen.png"
    cap = await asyncio.create_subprocess_exec(
        adb_path, "-s", serial, "shell", "screencap", "-p", tmp,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, cap_err = await cap.communicate()
    if cap.returncode != 0:
        return b"", f"capture-to-tmp exit={cap.returncode} stderr={cap_err.decode('utf-8', errors='replace').strip()[:200]}"

    cat = await asyncio.create_subprocess_exec(
        adb_path, "-s", serial, "exec-out", "cat", tmp,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, cat_err = await cat.communicate()

    # Best-effort cleanup; don't await.
    asyncio.create_task(_silent_rm(adb_path, serial, tmp))

    if cat.returncode != 0:
        return b"", f"cat exit={cat.returncode} stderr={cat_err.decode('utf-8', errors='replace').strip()[:200]}"
    if not stdout.startswith(_PNG_MAGIC):
        return b"", f"cat returned non-PNG (first 16 bytes: {stdout[:16].hex()})"
    return stdout, "ok"


async def _silent_rm(adb_path: str, serial: str, path: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        adb_path, "-s", serial, "shell", "rm", "-f", path,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()


@app.get("/v1/devices/{serial}/screencap.png")
async def device_screencap(serial: str) -> Response:
    """Single PNG. Tries exec-out fast path first, falls back to temp-file.

    Validated against the PNG magic header so we never serve a half-baked stream
    to the `<img>` tag (that was the cause of the SM-F741B "stalled" bug).
    """
    nexus: MedusaNexus = app.state.nexus

    png, diag1 = await _screencap_exec_out(nexus.config.adb_path, serial)
    if png:
        return Response(
            content=png, media_type="image/png",
            headers={"Cache-Control": "no-cache", "X-MNexus-Path": "exec-out"},
        )

    png2, diag2 = await _screencap_temp_file(nexus.config.adb_path, serial)
    if png2:
        return Response(
            content=png2, media_type="image/png",
            headers={"Cache-Control": "no-cache", "X-MNexus-Path": "temp-file"},
        )

    raise HTTPException(
        503,
        detail={
            "error": "screencap_failed",
            "exec_out": diag1,
            "temp_file": diag2,
            "hint": "OEM screen-protect (Knox/DRM) or USB hiccup. Try /v1/devices/{serial}/screencap-debug for raw output.",
        },
    )


@app.get("/v1/devices/{serial}/screencap-debug")
async def device_screencap_debug(serial: str) -> dict[str, Any]:
    """Diagnostic JSON for the screencap path — used when the mirror stalls."""
    nexus: MedusaNexus = app.state.nexus
    out: dict[str, Any] = {"serial": serial}

    png, diag = await _screencap_exec_out(nexus.config.adb_path, serial)
    out["exec_out"] = {
        "ok": bool(png),
        "size_bytes": len(png),
        "head_hex": png[:16].hex() if png else "",
        "diag": diag,
    }

    png2, diag2 = await _screencap_temp_file(nexus.config.adb_path, serial)
    out["temp_file"] = {
        "ok": bool(png2),
        "size_bytes": len(png2),
        "head_hex": png2[:16].hex() if png2 else "",
        "diag": diag2,
    }
    out["picked"] = "exec-out" if png else ("temp-file" if png2 else "none")
    return out


# ─── MJPEG live stream ───────────────────────────────────────────────────
# Browser renders multipart/x-mixed-replace natively → no flicker, no JS
# polling, single TCP connection. When the client disconnects, FastAPI
# raises CancelledError into our generator and we tear down.

_MJPEG_BOUNDARY = "mnexusframe"


async def _mjpeg_frame_loop(adb_path: str, serial: str, fps: int):
    interval = 1.0 / max(1, min(fps, 30))
    consecutive_failures = 0
    last_path = "exec-out"  # remember which capture path worked, skip the broken one
    try:
        while True:
            try:
                if last_path == "exec-out":
                    png, _ = await _screencap_exec_out(adb_path, serial)
                    if not png:
                        last_path = "temp-file"
                        png, _ = await _screencap_temp_file(adb_path, serial)
                else:
                    png, _ = await _screencap_temp_file(adb_path, serial)
                    if not png:
                        last_path = "exec-out"
                        png, _ = await _screencap_exec_out(adb_path, serial)
            except FileNotFoundError:
                # adb itself isn't on PATH — no point looping. Headers were
                # already written by StreamingResponse; just close the stream.
                return

            if not png:
                consecutive_failures += 1
                if consecutive_failures > 6:
                    return  # >5s of failures → close the stream so the client falls back to polling
                await asyncio.sleep(0.5)
                continue
            consecutive_failures = 0

            header = (
                f"--{_MJPEG_BOUNDARY}\r\n"
                f"Content-Type: image/png\r\n"
                f"Content-Length: {len(png)}\r\n\r\n"
            ).encode()
            yield header
            yield png
            yield b"\r\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        return


@app.get("/v1/devices/{serial}/screen.mjpeg")
async def device_screen_mjpeg(serial: str, fps: int = 6) -> StreamingResponse:
    """Live screen as multipart/x-mixed-replace — point an `<img src=…>` at it.

    Default 6 fps because PNG frames at 1080×2400 are ~1 MB each. The browser
    paints each frame atomically so there is no flicker. Set ?fps=12 for
    smoother motion at 2× bandwidth, or ?fps=2 for low-power preview.
    """
    nexus: MedusaNexus = app.state.nexus
    return StreamingResponse(
        _mjpeg_frame_loop(nexus.config.adb_path, serial, fps),
        media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY}",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-MNexus-Stream": "mjpeg-png",
        },
    )


@app.post("/v1/devices/{serial}/frida-server")
async def device_frida_per_device(serial: str) -> dict[str, Any]:
    """Start frida-server on a specific device (multi-device variant of /v1/device/frida/start)."""
    nexus: MedusaNexus = app.state.nexus
    cmd = "su -c '/data/local/tmp/frida-server &' 2>/dev/null || /data/local/tmp/frida-server &"
    try:
        await nexus.engines["adb"]._run([nexus.config.adb_path, "-s", serial, "shell", cmd])  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"adb shell failed: {exc}") from exc
    await asyncio.sleep(1.5)
    ps = await nexus.engines["adb"]._run([nexus.config.adb_path, "-s", serial, "shell", "pgrep", "-f", "frida-server"])  # type: ignore[attr-defined]
    return {"serial": serial, "running": bool(ps.strip()), "pid": ps.strip().splitlines()[0] if ps.strip() else None}


# ─── ADB control panel (audited single-shot ADB calls) ───────────────────
# Every command that the UI launches goes through `_adb_log` so the SPA can
# render an ADBugger-style "command log" — the most useful pedagogical feature
# of those tools is letting you *see what's actually being run*.

import collections

# Bounded ring buffer. 500 entries is plenty for an interactive session.
_ADB_LOG: "collections.deque[dict[str, Any]]" = collections.deque(maxlen=500)


async def _adb(
    args: list[str],
    *,
    serial: str | None = None,
    note: str = "",
    decode: bool = True,
) -> tuple[int, str]:
    """Run `adb [...]` with full audit trail. Returns (returncode, output)."""
    nexus: MedusaNexus = app.state.nexus
    full = [nexus.config.adb_path]
    if serial:
        full += ["-s", serial]
    full += args
    started = datetime.now(UTC).isoformat()
    proc = await asyncio.create_subprocess_exec(
        *full,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    text = stdout.decode("utf-8", errors="replace") if decode else ""
    entry = {
        "ts": started,
        "transport": "adb",
        "serial": serial or "—",
        "command": " ".join(full),
        "exit": proc.returncode,
        "output": text[:4000],  # cap so we never blow up the log
        "note": note,
    }
    _ADB_LOG.append(entry)
    return proc.returncode, text


async def _record_external_run(
    argv: list[str],
    rc: int,
    output: str,
    *,
    note: str,
    transport: str,
    serial: str | None = None,
) -> None:
    """Append an audit-log entry for a run that happened outside `_adb`.

    Used by `VPhoneEngine.recorder` so vphone calls land in the same ring
    buffer as adb calls, with `transport="vphone"` so the UI can colour
    them differently.
    """
    _ADB_LOG.append({
        "ts": datetime.now(UTC).isoformat(),
        "transport": transport,
        "serial": serial or "—",
        "command": " ".join(argv),
        "exit": rc,
        "output": (output or "")[:4000],
        "note": note,
    })


async def _adb_or_503(args: list[str], *, serial: str | None = None, note: str = "") -> tuple[int, str]:
    """Like `_adb` but converts FileNotFoundError into a clean 503."""
    nexus: MedusaNexus = app.state.nexus
    if not shutil.which(nexus.config.adb_path):
        raise HTTPException(503, "adb not on PATH")
    try:
        return await _adb(args, serial=serial, note=note)
    except FileNotFoundError:
        raise HTTPException(503, "adb not on PATH") from None


@app.get("/v1/adb/log")
async def adb_log(limit: int = 100) -> dict[str, Any]:
    """Recent adb invocations + their output — the audit trail."""
    limit = max(1, min(limit, 500))
    rows = list(_ADB_LOG)[-limit:]
    return {"count": len(rows), "log": rows}


@app.post("/v1/adb/log/clear")
async def adb_log_clear() -> dict[str, Any]:
    n = len(_ADB_LOG)
    _ADB_LOG.clear()
    return {"cleared": n}


@app.get("/v1/adb/help")
async def adb_help() -> dict[str, Any]:
    """Catalog of supported ADB categories — drives the control panel sidebar."""
    return {
        "categories": [
            {"id": "server",   "label": "ADB Server",     "blurb": "start / kill / root"},
            {"id": "reboot",   "label": "Reboot",         "blurb": "normal / recovery / bootloader / fastboot"},
            {"id": "devices",  "label": "Devices",        "blurb": "list / connect / disconnect / tcpip"},
            {"id": "apps",     "label": "Apps",           "blurb": "install / uninstall / clear / list packages"},
            {"id": "activity", "label": "Activity",       "blurb": "am start · broadcast · home · phone · sms"},
            {"id": "perms",    "label": "Permissions",    "blurb": "grant / revoke / reset"},
            {"id": "display",  "label": "Display",        "blurb": "wm size / density · reset"},
            {"id": "input",    "label": "Input",          "blurb": "keyevent / tap / swipe / text"},
            {"id": "screen",   "label": "Screen",         "blurb": "screencap / screenrecord"},
            {"id": "files",    "label": "Files",          "blurb": "push / pull / ls / rm"},
            {"id": "logcat",   "label": "Logcat",         "blurb": "tail / clear / filter"},
            {"id": "dumpsys",  "label": "Dumpsys",        "blurb": "battery · window · wifi · package"},
            {"id": "monkey",   "label": "Monkey",         "blurb": "stress test"},
            {"id": "sharedprefs","label": "Shared Prefs", "blurb": "PUT / REMOVE / CLEAR via broadcast"},
            {"id": "device-info","label": "Device Info",  "blurb": "getprop / wm size / build info"},
        ],
        "keycodes": _KEYCODES,
    }


_KEYCODES = [
    {"code": 3,   "name": "HOME"},
    {"code": 4,   "name": "BACK"},
    {"code": 5,   "name": "CALL"},
    {"code": 6,   "name": "ENDCALL"},
    {"code": 24,  "name": "VOLUME_UP"},
    {"code": 25,  "name": "VOLUME_DOWN"},
    {"code": 26,  "name": "POWER"},
    {"code": 27,  "name": "CAMERA"},
    {"code": 64,  "name": "EXPLORER"},
    {"code": 66,  "name": "ENTER"},
    {"code": 67,  "name": "DEL"},
    {"code": 82,  "name": "MENU"},
    {"code": 84,  "name": "SEARCH"},
    {"code": 85,  "name": "MEDIA_PLAY_PAUSE"},
    {"code": 86,  "name": "MEDIA_STOP"},
    {"code": 87,  "name": "MEDIA_NEXT"},
    {"code": 88,  "name": "MEDIA_PREVIOUS"},
    {"code": 91,  "name": "MUTE"},
    {"code": 92,  "name": "PAGE_UP"},
    {"code": 93,  "name": "PAGE_DOWN"},
    {"code": 122, "name": "MOVE_HOME"},
    {"code": 123, "name": "MOVE_END"},
    {"code": 207, "name": "CONTACTS"},
    {"code": 220, "name": "BRIGHTNESS_DOWN"},
    {"code": 221, "name": "BRIGHTNESS_UP"},
    {"code": 277, "name": "CUT"},
    {"code": 278, "name": "COPY"},
    {"code": 279, "name": "PASTE"},
]


# ── ADB server lifecycle ────────────────────────────────────────────────

@app.post("/v1/adb/server/{action}")
async def adb_server(action: str) -> dict[str, Any]:
    """`adb start-server`, `adb kill-server`, `adb root` — host-level toggles."""
    if action not in ("start", "kill", "root", "unroot"):
        raise HTTPException(400, f"unknown action {action!r}")
    sub = {"start": "start-server", "kill": "kill-server", "root": "root", "unroot": "unroot"}[action]
    rc, out = await _adb_or_503([sub], note=f"server.{action}")
    return {"action": action, "exit": rc, "output": out}


# ── App actions ─────────────────────────────────────────────────────────

@app.post("/v1/devices/{serial}/uninstall")
async def device_uninstall(serial: str, package: str = Form(...), keep_data: str = Form(default="")) -> dict[str, Any]:
    """`adb uninstall [-k] <pkg>` — pass keep_data=yes to retain data dir."""
    args = ["uninstall"]
    if keep_data == "yes":
        args.append("-k")
    args.append(package)
    rc, out = await _adb_or_503(args, serial=serial, note=f"uninstall {package}")
    return {"serial": serial, "package": package, "exit": rc, "output": out, "success": "Success" in out}


@app.post("/v1/devices/{serial}/clear")
async def device_clear(serial: str, package: str = Form(...)) -> dict[str, Any]:
    """`pm clear <pkg>` — wipes app data without uninstalling."""
    rc, out = await _adb_or_503(["shell", "pm", "clear", package], serial=serial, note=f"clear {package}")
    return {"serial": serial, "package": package, "exit": rc, "output": out, "success": "Success" in out}


@app.get("/v1/devices/{serial}/packages")
async def device_packages_per(serial: str, scope: str = "all", filter: str = "") -> list[dict[str, Any]]:
    """List packages on a specific device. scope ∈ {all,3rd,system,uninstalled,with-paths}."""
    arg = {"all": "", "3rd": "-3", "system": "-s", "uninstalled": "-u", "with-paths": "-r"}.get(scope, "")
    cmd = ["shell", "pm", "list", "packages"]
    if arg:
        cmd.append(arg)
    if filter:
        cmd.append(filter)
    _, out = await _adb_or_503(cmd, serial=serial, note=f"packages.{scope}")
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        rest = line[len("package:"):]
        if "=" in rest:
            apk_path, _, name = rest.partition("=")
            rows.append({"package": name, "apk_path": apk_path})
        else:
            rows.append({"package": rest})
    return rows


@app.post("/v1/devices/{serial}/start")
async def device_app_start(serial: str, package: str = Form(...), activity: str = Form(default="")) -> dict[str, Any]:
    """`am start -n <pkg>/<activity>` — launch the app's main activity by default."""
    if activity:
        target = f"{package}/{activity}"
    else:
        # Resolve the launcher activity via dumpsys; fall back to a generic launcher intent.
        _, raw = await _adb_or_503(
            ["shell", "cmd", "package", "resolve-activity", "--brief", package],
            serial=serial, note=f"resolve-activity {package}",
        )
        line = next((l for l in raw.splitlines() if "/" in l and not l.startswith("priority")), "")
        target = line.strip() if line else ""
    if target:
        rc, out = await _adb_or_503(["shell", "am", "start", "-n", target], serial=serial, note=f"start {target}")
    else:
        rc, out = await _adb_or_503(
            ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
            serial=serial, note=f"monkey-launch {package}",
        )
    return {"serial": serial, "target": target or f"monkey:{package}", "exit": rc, "output": out}


@app.post("/v1/devices/{serial}/stop")
async def device_app_stop(serial: str, package: str = Form(...)) -> dict[str, Any]:
    """`am force-stop <pkg>` — terminate all processes for the package."""
    rc, out = await _adb_or_503(["shell", "am", "force-stop", package], serial=serial, note=f"force-stop {package}")
    return {"serial": serial, "package": package, "exit": rc, "output": out}


# ── Activity Manager ────────────────────────────────────────────────────

@app.post("/v1/devices/{serial}/intent")
async def device_intent(
    serial: str,
    action: str = Form(...),
    data: str = Form(default=""),
    extras: str = Form(default=""),
    component: str = Form(default=""),
    mode: str = Form(default="start"),
) -> dict[str, Any]:
    """Generic `am start|broadcast` with an action + optional data + component."""
    if mode not in ("start", "broadcast", "startservice"):
        raise HTTPException(400, "mode must be start|broadcast|startservice")
    cmd = ["shell", "am", mode, "-a", action]
    if data:
        cmd += ["-d", data]
    if component:
        cmd += ["-n", component]
    if extras:
        # Each extra is "k=v" — types not supported (UI uses --es by default).
        for kv in extras.split(","):
            if "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            cmd += ["--es", k.strip(), v.strip()]
    rc, out = await _adb_or_503(cmd, serial=serial, note=f"{mode} {action}")
    return {"serial": serial, "exit": rc, "output": out}


@app.post("/v1/devices/{serial}/home")
async def device_home(serial: str) -> dict[str, Any]:
    rc, out = await _adb_or_503(
        ["shell", "am", "start", "-W", "-c", "android.intent.category.HOME", "-a", "android.intent.action.MAIN"],
        serial=serial, note="home",
    )
    return {"serial": serial, "exit": rc, "output": out}


@app.post("/v1/devices/{serial}/url")
async def device_open_url(serial: str, url: str = Form(...)) -> dict[str, Any]:
    rc, out = await _adb_or_503(
        ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url],
        serial=serial, note=f"url {url}",
    )
    return {"serial": serial, "exit": rc, "output": out}


# ── Permissions ─────────────────────────────────────────────────────────

@app.post("/v1/devices/{serial}/permissions/{op}")
async def device_permissions(serial: str, op: str, package: str = Form(...), permission: str = Form(default="")) -> dict[str, Any]:
    """grant / revoke / reset permissions for a package."""
    if op not in ("grant", "revoke", "reset"):
        raise HTTPException(400, "op must be grant|revoke|reset")
    if op == "reset":
        rc, out = await _adb_or_503(["shell", "pm", "reset-permissions", "-p", package], serial=serial, note=f"perm.reset {package}")
    else:
        if not permission:
            raise HTTPException(400, "permission is required for grant/revoke")
        rc, out = await _adb_or_503(["shell", "pm", op, package, permission], serial=serial, note=f"perm.{op} {package}")
    return {"serial": serial, "op": op, "exit": rc, "output": out}


# ── Display (size + density) ───────────────────────────────────────────

@app.post("/v1/devices/{serial}/wm")
async def device_wm(
    serial: str,
    op: str = Form(...),
    value: str = Form(default=""),
) -> dict[str, Any]:
    """op ∈ {size,size-reset,density,density-reset}; value e.g. 1080x1920 or 320."""
    if op == "size":
        if not value:
            raise HTTPException(400, "value required (e.g. 1080x1920)")
        cmd = ["shell", "wm", "size", value]
    elif op == "size-reset":
        cmd = ["shell", "wm", "size", "reset"]
    elif op == "density":
        if not value:
            raise HTTPException(400, "value required (e.g. 320)")
        cmd = ["shell", "wm", "density", value]
    elif op == "density-reset":
        cmd = ["shell", "wm", "density", "reset"]
    else:
        raise HTTPException(400, "op must be size|size-reset|density|density-reset")
    rc, out = await _adb_or_503(cmd, serial=serial, note=f"wm.{op} {value}")
    return {"serial": serial, "op": op, "value": value, "exit": rc, "output": out}


# ── Monkey ──────────────────────────────────────────────────────────────

@app.post("/v1/devices/{serial}/monkey")
async def device_monkey(
    serial: str,
    package: str = Form(...),
    events: int = Form(default=500),
    seed: int = Form(default=42),
) -> dict[str, Any]:
    events = max(1, min(events, 100000))
    rc, out = await _adb_or_503(
        ["shell", "monkey", "-p", package, "-v", str(events), "-s", str(seed)],
        serial=serial, note=f"monkey {package} {events}",
    )
    return {"serial": serial, "package": package, "events": events, "exit": rc, "output": out}


# ── Screen recording ────────────────────────────────────────────────────

@app.post("/v1/devices/{serial}/screenrecord/start")
async def device_screenrecord_start(serial: str, seconds: int = Form(default=60)) -> dict[str, Any]:
    """Start `screenrecord` on-device. Caps at 180s (Android's own limit)."""
    seconds = max(5, min(seconds, 180))
    remote = "/sdcard/mnexus-record.mp4"
    # Fire and forget — the UI polls /screenrecord/status afterwards.
    nexus: MedusaNexus = app.state.nexus
    if not shutil.which(nexus.config.adb_path):
        raise HTTPException(503, "adb not on PATH")
    proc = await asyncio.create_subprocess_exec(
        nexus.config.adb_path, "-s", serial, "shell",
        "screenrecord", "--time-limit", str(seconds), remote,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    _ADB_LOG.append({
        "ts": datetime.now(UTC).isoformat(), "serial": serial,
        "command": f"adb -s {serial} shell screenrecord --time-limit {seconds} {remote}",
        "exit": "running", "output": f"started pid={proc.pid}",
        "note": f"screenrecord.start {seconds}s",
    })
    return {"serial": serial, "remote": remote, "pid": proc.pid, "seconds": seconds}


@app.post("/v1/devices/{serial}/screenrecord/pull")
async def device_screenrecord_pull(serial: str) -> dict[str, Any]:
    """Pull the most recent recording into the workspace."""
    nexus: MedusaNexus = app.state.nexus
    out_dir = nexus.config.workspace / "screenrecords"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    local = out_dir / f"record-{serial}-{stamp}.mp4"
    rc, out = await _adb_or_503(["pull", "/sdcard/mnexus-record.mp4", str(local)], serial=serial, note="screenrecord.pull")
    if not local.exists():
        raise HTTPException(404, "no recording on device — start one first")
    return {"serial": serial, "local": str(local), "size_bytes": local.stat().st_size, "output": out}


# ── Shared preferences (the broadcast trick) ────────────────────────────

@app.post("/v1/devices/{serial}/sharedprefs")
async def device_sharedprefs(
    serial: str,
    package: str = Form(...),
    op: str = Form(...),
    name: str = Form(default=""),
    key: str = Form(default=""),
    value: str = Form(default=""),
    type: str = Form(default="string"),
) -> dict[str, Any]:
    """Hits the canonical SharedPreferences debug receiver — only works in debug
    builds that registered <package>.sp.{PUT,REMOVE,CLEAR}.

    type ∈ {string, boolean, float, int, long}.
    """
    if op not in ("PUT", "REMOVE", "CLEAR"):
        raise HTTPException(400, "op must be PUT|REMOVE|CLEAR")
    type_flag = {"string": "--es", "boolean": "--ez", "float": "--ef", "int": "--ei", "long": "--el"}.get(type, "--es")
    cmd = ["shell", "am", "broadcast", "-a", f"{package}.sp.{op}"]
    if name:
        cmd += ["--es", "name", name]
    if key:
        cmd += ["--es", "key", key]
    if op == "PUT" and value:
        cmd += [type_flag, "value", value]
    rc, out = await _adb_or_503(cmd, serial=serial, note=f"sp.{op} {package}/{key}")
    return {"serial": serial, "exit": rc, "output": out, "command": " ".join(cmd)}


# ── dumpsys topical wrappers ────────────────────────────────────────────

_DUMPSYS_TOPICS = ("battery", "wifi", "window", "package", "activity", "cpuinfo", "meminfo", "media_session")


@app.get("/v1/devices/{serial}/dumpsys/{topic}")
async def device_dumpsys(serial: str, topic: str, target: str = "") -> dict[str, Any]:
    if topic not in _DUMPSYS_TOPICS:
        raise HTTPException(400, f"topic must be one of {_DUMPSYS_TOPICS}")
    args = ["shell", "dumpsys", topic]
    if target:
        args.append(target)
    rc, out = await _adb_or_503(args, serial=serial, note=f"dumpsys.{topic}")
    return {"serial": serial, "topic": topic, "target": target, "exit": rc, "output": out}


# ── Device-info convenience: `getprop ro.build.version.release` ─────────

@app.get("/v1/devices/{serial}/version")
async def device_version(serial: str) -> dict[str, Any]:
    _, out = await _adb_or_503(["shell", "getprop", "ro.build.version.release"], serial=serial, note="version")
    return {"serial": serial, "android": out.strip()}


# ── Logcat per-device (parallels /v1/device/logcat singleton) ───────────

@app.get("/v1/devices/{serial}/logcat")
async def device_logcat_per(serial: str, lines: int = 200, level: str = "V", filter: str = "") -> dict[str, Any]:
    lines = max(1, min(lines, 5000))
    level = level.upper().strip() if level else "V"
    if level not in ("V", "D", "I", "W", "E", "F", "S"):
        level = "V"
    cmd = ["shell", "logcat", "-d", "-t", str(lines), f"*:{level}"]
    rc, out = await _adb_or_503(cmd, serial=serial, note=f"logcat -t {lines} *:{level}")
    if filter:
        flow = [ln for ln in out.splitlines() if filter.lower() in ln.lower()]
    else:
        flow = out.splitlines()
    return {"serial": serial, "lines": flow, "count": len(flow), "level": level, "filter": filter, "exit": rc}


@app.post("/v1/devices/{serial}/logcat/clear")
async def device_logcat_clear(serial: str) -> dict[str, Any]:
    rc, out = await _adb_or_503(["shell", "logcat", "-c"], serial=serial, note="logcat -c")
    return {"serial": serial, "exit": rc, "output": out}


# ─── vphone (super-tart-vphone — research-only iOS VM) ───────────────────
# Same shape as `/v1/devices/{serial}/...` but powered by the VPhoneEngine
# instead of adb. Audit-log rows from these endpoints carry `transport="vphone"`
# so the Command Log can colour them differently from ADB rows.

def _vphone_engine() -> "VPhoneEngine":  # noqa: F821
    nexus: MedusaNexus = app.state.nexus
    eng = nexus.engines.get("vphone")
    if eng is None:
        raise HTTPException(503, "vphone engine not registered")
    return eng  # type: ignore[return-value]


@app.get("/v1/vphones")
async def vphones_list() -> list[dict[str, Any]]:
    """List super-tart VMs. Empty list when the binary isn't configured yet."""
    return await _vphone_engine().list_vms()


@app.get("/v1/vphones/{name}")
async def vphones_info(name: str) -> dict[str, Any]:
    return await _vphone_engine().vm_info(name)


@app.post("/v1/vphones/{name}/start")
async def vphones_start(name: str, extra_args: str = Form(default="")) -> dict[str, Any]:
    """Start a VM in the background. `extra_args` is split on whitespace and
    forwarded as additional `tart run` flags (e.g. `--no-graphics`)."""
    extras = [tok for tok in (extra_args or "").split() if tok]
    try:
        return await _vphone_engine().start(name, extra_args=extras)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/vphones/{name}/stop")
async def vphones_stop(name: str) -> dict[str, Any]:
    try:
        return await _vphone_engine().stop(name)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/vphones/{name}/ssh")
async def vphones_ssh(name: str, command: str = Form(...)) -> dict[str, Any]:
    """Run a one-shot shell command over SSH inside the VM.

    No blocklist here — the user has already accepted research-mode
    posture on the host. Every command is recorded in the audit log."""
    if not command.strip():
        raise HTTPException(400, "empty command")
    return await _vphone_engine().ssh(name, command)


@app.post("/v1/vphones/{name}/install")
async def vphones_install(name: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Push an IPA into the VM, ldid-resign, register with SpringBoard."""
    if not file.filename:
        raise HTTPException(400, "no filename on upload")
    nexus: MedusaNexus = app.state.nexus
    staging = nexus.config.workspace / "vphone-stage"
    staging.mkdir(parents=True, exist_ok=True)
    local = staging / Path(file.filename).name
    with local.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
    try:
        return await _vphone_engine().install_ipa(name, local)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/v1/vphones/{name}/file")
async def vphones_file_get(name: str, path: str) -> Response:
    """Pull a file out of the VM via scp."""
    if not path or path.startswith(("|", "&", ";")):
        raise HTTPException(400, "bad path")
    nexus: MedusaNexus = app.state.nexus
    local_dir = nexus.config.workspace / "vphone-pulled"
    local_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(path).name or "file"
    local = local_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
    res = await _vphone_engine().pull(name, path, local)
    if res["exit"] != 0 or not local.exists():
        raise HTTPException(500, f"scp failed: {res['output'][:200]}")
    return FileResponse(str(local), filename=safe_name)


@app.post("/v1/vphones/{name}/file/upload")
async def vphones_file_upload(
    name: str,
    file: UploadFile = File(...),
    dest: str = Form(default="/var/mobile/Media"),
) -> dict[str, Any]:
    """Push an arbitrary file into the VM under `dest`."""
    if not file.filename:
        raise HTTPException(400, "no filename")
    nexus: MedusaNexus = app.state.nexus
    staging = nexus.config.workspace / "vphone-push"
    staging.mkdir(parents=True, exist_ok=True)
    local = staging / Path(file.filename).name
    with local.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
    remote = dest.rstrip("/") + "/" + Path(file.filename).name
    return await _vphone_engine().push(name, local, remote)


@app.post("/v1/vphones/{name}/screenshot")
async def vphones_screenshot(name: str) -> dict[str, Any]:
    """Capture the VM's VNC screen as PNG. Returns a 501 envelope when
    no VNC client (vncsnapshot/vncdotool) is on the host PATH."""
    res = await _vphone_engine().screenshot(name)
    if not res.get("ok"):
        raise HTTPException(501, detail=res)
    return res


# ─── recipes (Medusa / Stheno on disk) ───────────────────────────────────

@app.get("/v1/recipes")
async def list_recipes(platform: str | None = None) -> list[dict[str, Any]]:
    """Enumerate built-in + Medusa/Stheno recipes on disk.

    `platform` filters to "android" / "ios" / "both" — defaults to all.
    Built-ins always carry a `platform` field; Medusa modules default to
    "android" since that's where Medusa originated.
    """
    from mnexus.recipes import BUILTIN_RECIPES
    nexus: MedusaNexus = app.state.nexus
    recipes: list[dict[str, Any]] = []

    # Built-in recipes always available — same shape as the disk ones, minus the script.
    for r in BUILTIN_RECIPES:
        item = {k: v for k, v in r.items() if k != "script"}
        recipes.append(item)

    if nexus.config.medusa_path and nexus.config.medusa_path.exists():
        modules_dir = nexus.config.medusa_path / "modules"
        if modules_dir.exists():
            # Medusa organises modules hierarchically under modules/<category>/<name>.med.
            # rglob (recursive) catches the whole tree — modules.glob picks up
            # only top-level files, which historically meant we exposed 1 of 124.
            for path in sorted(modules_dir.rglob("*.med")):
                rel = path.relative_to(modules_dir)
                # Stable id used both for display and as the slug /v1/recipes/{name}/script
                # consumes — never collides because it carries the category prefix.
                slug = str(rel.with_suffix("")).replace("\\", "/")
                # Category = the immediate parent dir, uppercased. Top-level
                # files (e.g. `scratchpad.med`) fall back to a heuristic on
                # the filename so they still get a reasonable badge.
                if rel.parent == Path("."):
                    category = _guess_category(rel.stem)
                else:
                    category = rel.parent.parts[0].upper().replace("_", " ")
                recipes.append({
                    "name": slug,
                    "origin": "medusa",
                    "category": category,
                    "platform": "android",
                    "description": _medusa_recipe_blurb(path),
                    "compatibility": "frida ≥ 16",
                    "path": str(path),
                })

    if nexus.config.stheno_path and nexus.config.stheno_path.exists():
        recipes.append({
            "name": "inject_frida_gadget",
            "origin": "stheno",
            "category": "PATCH",
            "platform": "android",
            "description": "Stheno patches the APK with frida-gadget. No root? No problem.",
            "compatibility": "non-rooted · re-sign required",
        })

    if platform and platform.lower() not in ("all", ""):
        wanted = platform.lower()
        recipes = [r for r in recipes if r.get("platform", "android") in (wanted, "both")]
    return recipes


def _guess_category(name: str) -> str:
    n = name.lower()
    if "ssl" in n or "pin" in n:
        return "SSL"
    if "root" in n:
        return "ROOT"
    if "crypto" in n or "cipher" in n:
        return "CRYPTO"
    if "intent" in n:
        return "IPC"
    if "prefs" in n or "storage" in n or "file" in n:
        return "STORAGE"
    return "MISC"


def _medusa_recipe_blurb(path: Path) -> str:
    """Pull a one-line description out of a Medusa .med file.

    Medusa modules conventionally start with a banner comment. We grab the
    first non-empty line of leading `// …` comments — falls back to a
    filename-based blurb when the module has no header.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("//"):
                    cleaned = line.lstrip("/").strip()
                    if cleaned and not cleaned.startswith(("=", "─", "—")):
                        return cleaned[:160]
                    continue
                # First non-comment, non-blank line → stop scanning. We don't
                # want to leak the actual script body.
                break
    except OSError:
        pass
    return f"Medusa recipe loaded from {path.relative_to(path.parents[1])}"


@app.get("/v1/recipes/{name:path}/script")
async def recipe_script(name: str) -> dict[str, Any]:
    """Return the Frida script text for a recipe (unevaluated)."""
    from mnexus.recipes import BUILTIN_RECIPES
    # Built-in recipes first — guaranteed to exist.
    for r in BUILTIN_RECIPES:
        if r["name"] == name:
            return {"name": name, "script": r["script"], "platform": r.get("platform", "both")}

    # Fall through to Medusa modules on disk.
    nexus: MedusaNexus = app.state.nexus
    frida = nexus.engines.get("frida")
    try:
        script = frida.load_medusa_module(name) if frida else None  # type: ignore[attr-defined]
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not script:
        raise HTTPException(404, f"recipe not found: {name}")
    return {"name": name, "script": script}


# ─── settings ─────────────────────────────────────────────────────────────

@app.get("/v1/settings")
async def get_settings() -> dict[str, Any]:
    """Expose the NexusConfig so the Settings screen can render the real paths."""
    nexus: MedusaNexus = app.state.nexus
    cfg = nexus.config
    return {
        "paths": {
            "adb": cfg.adb_path,
            "jadx": cfg.jadx_path,
            "apktool": cfg.apktool_path,
            "ghidra": str(cfg.ghidra_path) if cfg.ghidra_path else None,
            "medusa": str(cfg.medusa_path) if cfg.medusa_path else None,
            "stheno": str(cfg.stheno_path) if cfg.stheno_path else None,
        },
        "services": {
            "mobsf_url": cfg.mobsf_url,
            "mobsf_has_api_key": bool(cfg.mobsf_api_key),
            "burp_url": cfg.burp_url,
            "burp_has_api_key": bool(cfg.burp_api_key),
            "caido_url": cfg.caido_url,
            "caido_has_api_key": bool(cfg.caido_api_key),
            "proxy_flavor": cfg.proxy_flavor,
        },
        "workspace": str(cfg.workspace),
        "db_path": str(cfg.db_path),
        "parallel_engines": cfg.parallel_engines,
        "default_dynamic_duration_s": cfg.default_dynamic_duration_s,
    }


# ─── exports: API collections + deeplink probe script ───────────────────

@app.get("/v1/projects/{project_id}/export/{fmt}")
async def export_project(project_id: str, fmt: str) -> Response:
    """Export the recovered endpoints + deeplinks in the chosen format.

    Formats:
      - postman   — Postman v2.1 collection (JSON)
      - caido     — Caido import bundle (JSON)
      - burp      — Burp Suite items file (XML)
      - moxy      — Moxy ruleset (YAML)
      - deeplinks — bash probe script (am start loop)
    """
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project:
        raise HTTPException(404, f"no project with id {project_id}")

    from mnexus.exporters import (
        to_burp_items,
        to_caido,
        to_deeplink_script,
        to_moxy_config,
        to_postman,
    )

    fmt_l = fmt.lower()
    media: str
    suffix: str
    body: str

    if fmt_l == "postman":
        body = to_postman(project)
        media = "application/json"
        suffix = "postman_collection.json"
    elif fmt_l == "caido":
        body = to_caido(project)
        media = "application/json"
        suffix = "caido.json"
    elif fmt_l in ("burp", "burp-items"):
        body = to_burp_items(project)
        media = "application/xml"
        suffix = "burp-items.xml"
    elif fmt_l == "moxy":
        body = to_moxy_config(project)
        media = "application/yaml"
        suffix = "moxy.yml"
    elif fmt_l in ("deeplinks", "deeplink"):
        body = to_deeplink_script(project)
        media = "application/x-sh"
        suffix = "deeplink-probe.sh"
    else:
        raise HTTPException(400, f"unsupported format '{fmt}' — pick postman / caido / burp / moxy / deeplinks")

    fname = f"{project_id}-{suffix}"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Mnexus-Project": project_id,
        },
    )


# ─── reports ──────────────────────────────────────────────────────────────

@app.post("/v1/projects/{project_id}/report")
async def generate_report(
    project_id: str,
    template: str = Form(default="technical"),
    fmt: str = Form(default="markdown"),
) -> Response:
    """Generate a report and return it as a file download."""
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project:
        raise HTTPException(404, f"no project with id {project_id}")

    suffix = {"markdown": "md", "json": "json", "html": "html", "pdf": "pdf"}.get(fmt.lower(), "txt")
    out_path = nexus.config.workspace / "reports" / f"{project_id}.{suffix}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ReportGenerator(project).generate(
            ReportTemplate(template),
            ReportFormat(fmt.lower()),
            str(out_path),
        )
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{exc.__class__.__name__}: {exc}") from exc

    media = {
        "md": "text/markdown",
        "json": "application/json",
        "html": "text/html",
        "pdf": "application/pdf",
    }.get(suffix, "application/octet-stream")
    return FileResponse(str(out_path), media_type=media, filename=out_path.name)


# ─── project sub-views (screens 09 / 10 / 11 / 15 / 16 / 17 / 18 / 19 / 20) ─

def _require_project(project_id: str) -> Project:
    nexus: MedusaNexus = app.state.nexus
    p = nexus.db.load_project(project_id)
    if not p:
        raise HTTPException(404, f"no project with id {project_id}")
    return p


@app.get("/v1/projects/{project_id}/secrets")
async def project_secrets(project_id: str) -> dict[str, Any]:
    """Screen 09 — secrets + crypto audit.

    Returns crypto operations + storage/crypto-category findings, ready for the
    table + heatmap renderers.
    """
    p = _require_project(project_id)
    surface = p.attack_surface
    crypto_ops = [op.model_dump(mode="json") for op in (surface.crypto_operations if surface else [])]
    secrets_findings = []
    if surface:
        for f in surface.findings:
            if f.category in (FindingCategory.CRYPTO, FindingCategory.STORAGE):
                secrets_findings.append(f.model_dump(mode="json"))

    # Aggregate algorithm × file heatmap from crypto_operations.
    heatmap: dict[str, dict[str, int]] = {}
    for op in surface.crypto_operations if surface else []:
        algo = op.algorithm or "unknown"
        file = (op.location or "—").split(":")[0]
        heatmap.setdefault(algo, {})
        heatmap[algo][file] = heatmap[algo].get(file, 0) + 1
    return {
        "project_id": p.id,
        "crypto_operations": crypto_ops,
        "findings": secrets_findings,
        "heatmap": heatmap,
        "weak_algorithms": sorted({op.algorithm for op in (surface.crypto_operations if surface else []) if _is_weak_algo(op.algorithm)}),
    }


def _is_weak_algo(algo: str | None) -> bool:
    if not algo:
        return False
    a = algo.lower()
    return any(token in a for token in ("ecb", "des", "md5", "sha1", "rc2", "rc4", "/cbc/"))


@app.get("/v1/projects/{project_id}/components")
async def project_components(project_id: str) -> dict[str, Any]:
    """Screen 10 — exported components + deeplinks."""
    p = _require_project(project_id)
    surface = p.attack_surface
    if not surface:
        return {"project_id": p.id, "components": [], "deeplinks": [], "by_type": {}}
    components = [c.model_dump(mode="json") for c in surface.exported_components]
    by_type: dict[str, int] = {}
    for c in surface.exported_components:
        by_type[c.component_type] = by_type.get(c.component_type, 0) + 1
    return {
        "project_id": p.id,
        "components": components,
        "deeplinks": surface.deeplinks,
        "permissions": surface.permissions,
        "by_type": by_type,
        "unprotected_count": sum(1 for c in surface.exported_components if c.unprotected),
    }


@app.get("/v1/projects/{project_id}/native")
async def project_native(project_id: str) -> dict[str, Any]:
    """Screen 11 — Ghidra native analysis output."""
    p = _require_project(project_id)
    surface = p.attack_surface
    libs = [n.model_dump(mode="json") for n in (surface.native_libraries if surface else [])]
    native_findings = []
    if surface:
        for f in surface.findings:
            if f.category is FindingCategory.NATIVE:
                native_findings.append(f.model_dump(mode="json"))
    return {
        "project_id": p.id,
        "native_libraries": libs,
        "findings": native_findings,
        "abis": sorted({lib["arch"] for lib in libs}),
    }


async def _gather_live_evidence(
    project_id: str,
    package_name: str | None,
    window_s: int = 60,
) -> dict[str, Any]:
    """Pool every real-time SSL/host signal we can find into one dict.

    Returns::

        {
          "moxy": {host: {"hits": int, "last_status": int|None, "last_ts": str|None,
                          "tls_intercepted": bool, "paths": {path: count}}},
          "pin_events": {host: {"events": int, "last_outcome": str|None, "last_ts": str|None}},
          "moxy_workspace": {"id": int, "name": str} | None,
          "moxy_error": str | None,
          "polled_at": iso8601,
          "window_s": int,
        }

    Source 1 — live Moxy flows (last ``window_s`` seconds). Hosts with a
        decoded HTTP response are proof TLS broke, so anything pinned on
        that host has either been bypassed or wasn't really pinned.

    Source 2 — dynamic_events with ``channel='ssl_pin'``. Emitted by the
        auto-generated SSL bypass hook every time a pinning callback
        fires — gives us per-callback granularity the proxy can't see.

    Every section degrades to empty silently. We never want the SSL map
    to 500 because one source is unreachable.
    """
    nexus: MedusaNexus = app.state.nexus
    out: dict[str, Any] = {
        "moxy": {},
        "pin_events": {},
        "moxy_workspace": None,
        "moxy_error": None,
        "polled_at": datetime.now(UTC).isoformat(),
        "window_s": window_s,
    }

    # 1) Moxy flows.
    moxy = nexus.engines.get("moxy")
    if moxy is not None:
        try:
            picked = await moxy.pick_project(package_name)  # type: ignore[attr-defined]
            if picked:
                out["moxy_workspace"] = {"id": int(picked["id"]), "name": picked.get("name")}
                flows = await moxy.fetch_flows(int(picked["id"]), limit=1000)  # type: ignore[attr-defined]
                # Filter to the window if ts present, else accept everything.
                cutoff = datetime.now(UTC).timestamp() - window_s
                for f in flows:
                    host = f.get("host") or ""
                    if not host:
                        continue
                    ts = f.get("ts") or ""
                    try:
                        flow_t = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                        if flow_t < cutoff:
                            continue
                    except (TypeError, ValueError):
                        # No parsable ts → keep the row (better to over-report).
                        pass
                    bucket = out["moxy"].setdefault(host, {
                        "hits": 0, "last_status": None, "last_ts": None,
                        "tls_intercepted": False, "paths": {},
                    })
                    bucket["hits"] += 1
                    bucket["last_status"] = f.get("status")
                    bucket["last_ts"] = ts or bucket["last_ts"]
                    if isinstance(f.get("status"), int):
                        bucket["tls_intercepted"] = True
                    path = f.get("path") or "/"
                    bucket["paths"][path] = bucket["paths"].get(path, 0) + 1
            else:
                out["moxy_error"] = "no Moxy workspace matched — run scripts/setup.sh --moxy"
        except Exception as exc:  # noqa: BLE001 - never let the SSL map crash on Moxy
            out["moxy_error"] = f"moxy fetch failed: {exc.__class__.__name__}"

    # 2) dynamic_events ssl_pin channel.
    try:
        rows = nexus.db._conn.execute(  # noqa: SLF001
            "SELECT ts, payload FROM dynamic_events "
            "WHERE project_id = ? AND channel = 'ssl_pin' "
            "ORDER BY id DESC LIMIT 500",
            (project_id,),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except Exception:  # noqa: BLE001
                continue
            host = payload.get("host") or ""
            if not host:
                continue
            bucket = out["pin_events"].setdefault(host, {
                "events": 0, "last_outcome": None, "last_ts": None, "library": None,
            })
            bucket["events"] += 1
            bucket["last_outcome"] = bucket["last_outcome"] or payload.get("outcome")
            bucket["last_ts"] = bucket["last_ts"] or row["ts"]
            bucket["library"] = bucket["library"] or payload.get("lib")
    except sqlite3.Error:
        pass

    return out


def _host_status(static_pinned: bool, moxy: dict[str, Any] | None, pin: dict[str, Any] | None) -> str:
    """Collapse three signals into one label the UI paints.

    Order of precedence:
      1. Live Frida pin event with outcome=bypassed → 'bypassed' (we see the
         callback firing AND traffic is flowing, so pinning is neutered).
      2. Moxy flows with decoded responses → 'intercepted' (TLS broke, no
         pinning is preventing the proxy).
      3. Static pinning detected AND no Moxy hits → 'blocked' (best guess:
         pinning is doing its job).
      4. Static pinning detected AND no live data either way → 'static-pinned'.
      5. Nothing observed → 'unknown'.
      6. No pinning detected statically and no live evidence → 'clear'.
    """
    pin_events = (pin or {}).get("events", 0)
    pin_outcome = (pin or {}).get("last_outcome")
    moxy_hits = (moxy or {}).get("hits", 0)
    tls_broken = (moxy or {}).get("tls_intercepted", False)

    if pin_events and pin_outcome in ("bypassed", "neutered"):
        return "bypassed"
    if moxy_hits and tls_broken:
        return "intercepted"
    if static_pinned and not moxy_hits:
        return "blocked"
    if static_pinned:
        return "static-pinned"
    if moxy_hits:
        return "clear"
    return "unknown"


@app.get("/v1/projects/{project_id}/api-map")
async def project_api_map(project_id: str, window_s: int = 60) -> dict[str, Any]:
    """Screen 15 — API endpoint tree (host → path → methods) + live hit counters.

    Static tree comes from ``AttackSurface.api_endpoints`` (jadx/apktool URL
    extraction). When Moxy is up, each (host, path) gains a ``hits`` counter
    over the last ``window_s`` seconds so the engineer sees what the app
    actually touched while they poked around the UI. Hosts the proxy saw but
    the static surface never claimed land under ``discovered_hosts`` so they
    don't get lost.
    """
    p = _require_project(project_id)
    surface = p.attack_surface
    endpoints = surface.api_endpoints if surface else []

    # Group by host. Each endpoint string is a URL or "METHOD url" or "host/path".
    tree: dict[str, dict[str, dict[str, Any]]] = {}
    for ep in endpoints:
        method, url = _split_method_url(ep)
        host, path = _split_host_path(url)
        node = tree.setdefault(host, {}).setdefault(path, {"methods": [], "hits": 0, "last_status": None})
        if method not in node["methods"]:
            node["methods"].append(method)

    live = await _gather_live_evidence(p.id, p.package_name, window_s=window_s)
    discovered: dict[str, dict[str, int]] = {}
    for host, info in live["moxy"].items():
        for path, count in (info.get("paths") or {}).items():
            if host in tree and path in tree[host]:
                tree[host][path]["hits"] = count
                tree[host][path]["last_status"] = info.get("last_status")
            else:
                # New host or path the static analysis missed.
                discovered.setdefault(host, {})[path] = count

    flagged = [
        f.model_dump(mode="json")
        for f in (surface.findings if surface else [])
        if f.category is FindingCategory.NETWORK
    ]
    return {
        "project_id": p.id,
        "tree": tree,
        "endpoints": endpoints,
        "flagged": flagged,
        "discovered_hosts": discovered,
        "live": {
            "polled_at": live["polled_at"],
            "window_s": live["window_s"],
            "moxy_workspace": live["moxy_workspace"],
            "moxy_error": live["moxy_error"],
        },
    }


def _split_method_url(ep: str) -> tuple[str, str]:
    parts = ep.split(" ", 1)
    if len(parts) == 2 and parts[0].upper() in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
        return parts[0].upper(), parts[1]
    return "GET", ep


def _split_host_path(url: str) -> tuple[str, str]:
    if "://" in url:
        rest = url.split("://", 1)[1]
    else:
        rest = url
    if "/" in rest:
        host, path = rest.split("/", 1)
        return host, "/" + path
    return rest, "/"


@app.get("/v1/projects/{project_id}/ssl-map")
async def project_ssl_map(project_id: str, window_s: int = 60) -> dict[str, Any]:
    """Screen 16 — SSL pinning map: domains × library × bypass strategy × LIVE.

    Three signal sources, merged per host:

      1. *Static* (jadx + apktool): ``ssl_pinning_detected`` flag + library
         hint. This is what shipped in v0.
      2. *Moxy* (passive): if Moxy is up, the engine pulls flows from the
         last ``window_s`` seconds. A flow with a decoded HTTP response on
         host H proves TLS was broken — either nothing was pinning that
         host, or pinning has been bypassed.
      3. *Frida ssl_pin events*: the auto-bypass hook emits
         ``send({channel:'ssl_pin', host, lib, outcome})`` on every pinning
         callback intercept. Stored under channel='ssl_pin' in
         ``dynamic_events``; consumed here for per-callback granularity.

    Each row resolves to one of: ``bypassed`` · ``intercepted`` · ``blocked``
    · ``static-pinned`` · ``clear`` · ``unknown`` (see ``_host_status``).
    The UI paints the badge accordingly and polls this endpoint every few
    seconds while the screen is mounted.
    """
    p = _require_project(project_id)
    surface = p.attack_surface
    live = await _gather_live_evidence(p.id, p.package_name, window_s=window_s)

    static_pinned = bool(surface and surface.ssl_pinning_detected)
    library = (surface.ssl_pinning_library if surface else None) or "unknown"
    bypass = {
        "okhttp": "okhttp_certificate_pinner_bypass",
        "trustmanager": "trustmanager_neuter",
        "custom": "ssl_universal_bypass",
    }.get(library, "ssl_universal_bypass")

    # Union of statically-known hosts + hosts we've actually seen live.
    static_hosts = (
        {_split_host_path(_split_method_url(ep)[1])[0] for ep in surface.api_endpoints}
        if surface else set()
    )
    live_hosts = set(live["moxy"].keys()) | set(live["pin_events"].keys())
    all_hosts = sorted({h for h in static_hosts | live_hosts if h})

    rows: list[dict[str, Any]] = []
    for host in all_hosts:
        moxy = live["moxy"].get(host)
        pin = live["pin_events"].get(host)
        status = _host_status(static_pinned, moxy, pin)
        rows.append({
            "host": host,
            "library": (pin and pin.get("library")) or (library if static_pinned else "—"),
            "pinned": static_pinned,
            "bypass_recipe": bypass if static_pinned else None,
            "status": status,
            "in_static_surface": host in static_hosts,
            "moxy_hits": (moxy or {}).get("hits", 0),
            "moxy_last_status": (moxy or {}).get("last_status"),
            "moxy_last_ts": (moxy or {}).get("last_ts"),
            "pin_events": (pin or {}).get("events", 0),
            "pin_last_outcome": (pin or {}).get("last_outcome"),
            "pin_last_ts": (pin or {}).get("last_ts"),
        })
    return {
        "project_id": p.id,
        "pinning_detected": static_pinned,
        "library": library,
        "rows": rows,
        "live": {
            "polled_at": live["polled_at"],
            "window_s": live["window_s"],
            "moxy_workspace": live["moxy_workspace"],
            "moxy_error": live["moxy_error"],
            "pin_event_count": sum(b["events"] for b in live["pin_events"].values()),
        },
    }


@app.get("/v1/projects/{project_id}/owasp")
async def project_owasp(project_id: str) -> dict[str, Any]:
    """Screen 20 — OWASP MASVS compliance matrix derived from findings.

    Uses the `masvs` (preferred) or `owasp_mobile` field on each Finding to
    decide which control failed. Cells without findings are PASS.
    """
    p = _require_project(project_id)
    surface = p.attack_surface
    findings = list(surface.findings) if surface else []

    # MASVS top-level domains we care about for a v0 matrix.
    domains = ["MSTG-ARCH", "MSTG-STORAGE", "MSTG-CRYPTO", "MSTG-AUTH", "MSTG-NETWORK", "MSTG-PLATFORM", "MSTG-CODE", "MSTG-RESILIENCE"]
    matrix: dict[str, dict[str, list[str]]] = {d: {"L1": [], "L2": [], "R": []} for d in domains}
    for f in findings:
        tag = f.masvs or _category_to_masvs(f.category)
        if not tag:
            continue
        domain = next((d for d in domains if tag.startswith(d)), None)
        if not domain:
            continue
        bucket = "L2" if f.severity in (Severity.CRITICAL, Severity.HIGH) else "L1"
        matrix[domain][bucket].append(f.id)
    summary = {
        "total_controls": len(domains) * 3,
        "failing_controls": sum(1 for d in matrix.values() for v in d.values() if v),
    }
    return {"project_id": p.id, "matrix": matrix, "summary": summary, "domains": domains}


def _category_to_masvs(cat: FindingCategory) -> str | None:
    return {
        FindingCategory.CRYPTO: "MSTG-CRYPTO",
        FindingCategory.STORAGE: "MSTG-STORAGE",
        FindingCategory.NETWORK: "MSTG-NETWORK",
        FindingCategory.AUTH: "MSTG-AUTH",
        FindingCategory.NATIVE: "MSTG-CODE",
        FindingCategory.OBFUSCATION: "MSTG-RESILIENCE",
        FindingCategory.IPC: "MSTG-PLATFORM",
        FindingCategory.WEBVIEW: "MSTG-PLATFORM",
        FindingCategory.PRIVACY: "MSTG-STORAGE",
        FindingCategory.CODE: "MSTG-CODE",
    }.get(cat)


@app.get("/v1/projects/{project_id}/attack-tree")
async def project_attack_tree(project_id: str) -> dict[str, Any]:
    """Screen 19 — attack tree per high-severity finding.

    For every CRIT/HIGH finding we synthesize a 3-step chain:
    prerequisite → exploitation → impact. Cheap, deterministic, useful.
    """
    p = _require_project(project_id)
    surface = p.attack_surface
    if not surface:
        return {"project_id": p.id, "trees": []}
    trees = []
    for f in surface.findings:
        if f.severity not in (Severity.CRITICAL, Severity.HIGH):
            continue
        trees.append({
            "finding_id": f.id,
            "title": f.title,
            "severity": f.severity.value,
            "nodes": [
                {"step": 1, "label": "Prerequisite", "detail": _prereq_for(f)},
                {"step": 2, "label": "Exploitation", "detail": _exploit_for(f)},
                {"step": 3, "label": "Impact", "detail": _impact_for(f)},
            ],
            "cvss_estimate": 9.1 if f.severity is Severity.CRITICAL else 7.4,
        })
    return {"project_id": p.id, "trees": trees}


def _prereq_for(f) -> str:  # type: ignore[no-untyped-def]
    if f.category is FindingCategory.CRYPTO:
        return "Inspect APK locally; pull binary or shared prefs."
    if f.category is FindingCategory.NETWORK:
        return "MITM-capable network position (rogue Wi-Fi, custom CA)."
    if f.category is FindingCategory.IPC:
        return "Any installed app with no special permission."
    return "App installed on attacker-controlled device."


def _exploit_for(f) -> str:  # type: ignore[no-untyped-def]
    return f"Trigger via {f.location or 'declared entry point'} — leverage {f.title.lower()}."


def _impact_for(f) -> str:  # type: ignore[no-untyped-def]
    return {
        FindingCategory.CRYPTO: "Key recovery → ciphertext decryption → data exfil.",
        FindingCategory.NETWORK: "Traffic decryption + replay; credential capture.",
        FindingCategory.STORAGE: "Direct read of secrets/PII at rest.",
        FindingCategory.IPC: "Privilege escalation via exposed component.",
        FindingCategory.WEBVIEW: "RCE / token theft via JS bridge.",
    }.get(f.category, "Confidentiality / integrity loss.")


# ─── Mango integration (ch0pin) — only the deltas Nexus doesn't already do ───────
#
# Anything Mango ships that Nexus already covers (pull, install, playstore,
# proxy, logcat, search, session, screencap, …) stays where it is. The
# endpoints below cover the three Mango commands that have no Nexus equivalent
# yet: decodeflag, diff, deeplink (+ --poc).


@app.post("/v1/mango/decode-flags")
async def mango_decode_flags(request: Request) -> dict[str, Any]:
    """Decode an Android flag integer against Intent / Receiver / PendingIntent /
    Content-resolver namespaces — Mango's ``decodeflag``.

    Body::
        {"value": "0x10000000", "namespaces": ["intent", "receiver"]}

    ``value`` accepts hex (``0x…``), decimal, or octal/binary literals (``0o…``/``0b…``).
    ``namespaces`` is optional; default returns every interpretation so the
    analyst sees the contextual ambiguity (``0x00000001`` is
    ``FLAG_GRANT_READ_URI_PERMISSION`` *and* ``QUERY_SORT_DESCENDING``).
    """
    from mnexus.intelligence import android_flags

    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be an object")
    try:
        value = android_flags.parse_flag_value(body.get("value"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, f"bad value: {exc}") from exc

    ns_param = body.get("namespaces")
    namespaces: list[str] | None = None
    if ns_param is not None:
        if not isinstance(ns_param, list) or not all(isinstance(n, str) for n in ns_param):
            raise HTTPException(400, "namespaces must be a list of strings")
        unknown = [n for n in ns_param if n not in android_flags.supported_namespaces()]
        if unknown:
            raise HTTPException(400, f"unknown namespace(s): {unknown}")
        namespaces = ns_param

    decoded = android_flags.decode(value, namespaces)
    return {
        "value": value,
        "hex": f"0x{value:X}",
        "namespaces": namespaces or android_flags.supported_namespaces(),
        "decoded": decoded,
    }


@app.get("/v1/projects/{project_id}/manifest-diff")
async def project_manifest_diff(project_id: str, against: str | None = None) -> dict[str, Any]:
    """Diff this project's AttackSurface against another scan of the
    *same* package — Mango's ``diff`` command, with structured data
    instead of plain-text manifest comparison.

    Picks ``against`` automatically when omitted: the most recent prior
    Project (different id) that shares the same ``package_name``. Returns
    a 404-flavoured stub (``base=null``) when no prior scan exists rather
    than a 404 so the UI can render an empty-state without flapping.
    """
    from mnexus.intelligence.manifest_diff import diff_surfaces

    p = _require_project(project_id)
    nexus: MedusaNexus = app.state.nexus
    head_surface = p.attack_surface.model_dump(mode="json") if p.attack_surface else None

    base_project: Project | None = None
    if against:
        base_project = nexus.db.load_project(against)
        if base_project is None:
            raise HTTPException(404, f"no project with id '{against}'")
        if base_project.id == p.id:
            raise HTTPException(400, "cannot diff a project against itself")
    else:
        # Most recent prior scan of the same package, excluding self.
        # list_projects returns lightweight dicts ordered by updated_at desc;
        # walk them in order until we find a matching package, then materialise
        # the full Project via load_project to get the attack_surface.
        for row in nexus.db.list_projects():
            if row.get("id") == p.id:
                continue
            if (row.get("package_name") or "") != (p.package_name or ""):
                continue
            base_project = nexus.db.load_project(row["id"])
            if base_project is not None:
                break

    if base_project is None:
        return {
            "project_id": p.id,
            "package": p.package_name,
            "base": None,
            "head": {"id": p.id, "version_name": p.version_name},
            "diff": diff_surfaces(None, head_surface),
            "note": "no prior scan of this package — diff renders 'all added' against an empty base.",
        }

    base_surface = base_project.attack_surface.model_dump(mode="json") if base_project.attack_surface else None
    return {
        "project_id": p.id,
        "package": p.package_name,
        "base": {
            "id": base_project.id,
            "version_name": base_project.version_name,
            "version_code": base_project.version_code,
            "created_at": base_project.created_at.isoformat(),
        },
        "head": {
            "id": p.id,
            "version_name": p.version_name,
            "version_code": p.version_code,
            "created_at": p.created_at.isoformat(),
        },
        "diff": diff_surfaces(base_surface, head_surface),
    }


@app.post("/v1/projects/{project_id}/mango/deeplink/fire")
async def mango_deeplink_fire(project_id: str, uri: str = Form(...)) -> dict[str, Any]:
    """Fire a deeplink intent on the connected device — Mango's ``deeplink``.

    Runs ``adb shell am start -W -a android.intent.action.VIEW -d <uri>``
    against the bridged device. Returns the raw output + the resolved
    activity (parsed out of ``am start``'s ``Activity:`` line). 503 when
    no device is connected, 400 when the URI is empty.
    """
    if not uri.strip():
        raise HTTPException(400, "uri is empty")
    p = _require_project(project_id)
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not await adb.is_device_connected():  # type: ignore[attr-defined]
        raise HTTPException(503, "no device connected — plug a device in and authorise USB debugging")
    out = await adb._run([  # type: ignore[attr-defined]
        nexus.config.adb_path, "shell", "am", "start", "-W",
        "-a", "android.intent.action.VIEW", "-d", uri,
    ])
    # Parse the resolved Activity line — when am can't resolve the deeplink
    # the line is missing and the analyst gets a stronger signal than 'I dunno'.
    activity = ""
    for line in out.splitlines():
        if line.startswith("Activity:"):
            activity = line.split(":", 1)[1].strip()
            break
    return {
        "project_id": p.id,
        "uri": uri,
        "activity": activity,
        "raw": out.strip(),
        "fired": activity != "",
    }


@app.get("/v1/projects/{project_id}/mango/deeplink/poc")
async def mango_deeplink_poc(project_id: str, uri: str) -> Response:
    """Generate an HTML PoC for a deeplink — Mango's ``deeplink --poc``.

    Returns an ``Content-Type: text/html`` body with a single anchor
    that fires ``uri`` when clicked. Useful for demonstrating that the
    deeplink can be triggered from a hostile page the user lands on —
    cross-app drive-by. The page is dumb on purpose; the value is the
    repro, not the UI.
    """
    if not uri.strip():
        raise HTTPException(400, "uri is empty")
    p = _require_project(project_id)
    # Escape the uri once for the href, once for the visible text. We
    # render through html.escape rather than rolling our own so a uri
    # with quotes or '<' doesn't break out of the attribute.
    import html as _html
    safe_href = _html.escape(uri, quote=True)
    safe_text = _html.escape(uri, quote=False)
    body = (
        "<!doctype html>\n"
        f"<html><head><meta charset=\"utf-8\"><title>Deeplink PoC — {_html.escape(p.package_name)}</title></head>\n"
        "<body style=\"font-family:system-ui,sans-serif;padding:32px;background:#111;color:#0ff\">\n"
        f"  <h1>Deeplink PoC</h1>\n"
        f"  <p>Target package: <code>{_html.escape(p.package_name)}</code></p>\n"
        f"  <p><a href=\"{safe_href}\" "
        "id=\"deeplink\" "
        "style=\"font-family:monospace;color:#0ff;font-size:18px;display:inline-block;padding:10px 16px;border:1px solid #0ff;border-radius:2px\">"
        f"{safe_text}</a></p>\n"
        f"  <p style=\"color:#888;font-size:12px\">Click the link from a browser running on the device — "
        "if the targeted app handles the URI without prompting, the deeplink is exploitable from any web page.</p>\n"
        "</body></html>\n"
    )
    return Response(body, media_type="text/html; charset=utf-8")


@app.post("/v1/projects/{project_id}/runtime/script")
async def project_runtime_script(
    project_id: str,
    request: Request,
) -> dict[str, Any]:
    """Generate a Medusa-flavoured Frida script for one runtime action.

    The Project's ``package_name`` is auto-bound everywhere — the analyst
    never types it. Body shape::

        {
            "action": "enumerate_classes" | "describe_class" |
                       "jtrace_method" | "enumerate_modules" |
                       "spawn_log",
            "params": { … action-specific … }
        }

    Returns::

        {
            "action":   "<echoed action>",
            "package":  "<project's package_name>",
            "channel":  "runtime",           # send() events land here
            "script":   "<full frida JS>",
            "hint":     "<one-liner of how to run it>",
        }

    The generated scripts all ``send({channel:'runtime', …})`` so the
    existing /v1/projects/{id}/dynamic/events ingest captures their
    output without a separate transport.

    Reuses Nexus primitives instead of duplicating Medusa's REPL:

      * Recipes library (built-in + ch0pin/medusa modules) is still the
        catalogue for stable hooks — this endpoint is for ad-hoc Medusa
        commands (`enumerate`, `describe_java_class`, `jtrace`, `libs`)
        that don't ship as recipes.
      * Frida-server lifecycle stays at /v1/device/frida/start.
      * The Dynamic tab still owns the long-lived session + console;
        this endpoint just emits the script for it to load.
    """
    p = _require_project(project_id)
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "expected an object body")
    action = (body.get("action") or "").strip()
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise HTTPException(400, "params must be an object")

    from mnexus.intelligence.runtime_scripts import generate_runtime_script

    try:
        out = generate_runtime_script(action, p.package_name or "", params)
    except KeyError as exc:
        raise HTTPException(400, f"unknown action: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "project_id": p.id,
        "package": p.package_name,
        "action": action,
        **out,
    }


@app.get("/v1/projects/{project_id}/dataflow")
async def project_dataflow(project_id: str) -> dict[str, Any]:
    """Screen 18 — sources/sinks for the data-flow swimlanes."""
    p = _require_project(project_id)
    surface = p.attack_surface
    sources = ["user-input", "remote-api", "device-sensor", "deeplink", "ipc"]
    sinks = ["disk", "log", "network", "clipboard", "webview"]
    flows = []
    if surface:
        for f in surface.findings:
            cat = f.category
            if cat is FindingCategory.STORAGE:
                flows.append({"source": "user-input", "sink": "disk", "finding_id": f.id, "severity": f.severity.value})
            elif cat is FindingCategory.NETWORK:
                flows.append({"source": "remote-api", "sink": "network", "finding_id": f.id, "severity": f.severity.value})
            elif cat is FindingCategory.WEBVIEW:
                flows.append({"source": "deeplink", "sink": "webview", "finding_id": f.id, "severity": f.severity.value})
            elif cat is FindingCategory.IPC:
                flows.append({"source": "ipc", "sink": "log", "finding_id": f.id, "severity": f.severity.value})
            elif cat is FindingCategory.PRIVACY:
                flows.append({"source": "device-sensor", "sink": "log", "finding_id": f.id, "severity": f.severity.value})
    return {"project_id": p.id, "sources": sources, "sinks": sinks, "flows": flows}


@app.get("/v1/projects/{project_id}/surface")
async def project_surface_graph(project_id: str) -> dict[str, Any]:
    """Screen 17 — attack surface graph (nodes + edges for force-directed layout)."""
    p = _require_project(project_id)
    surface = p.attack_surface
    nodes: list[dict[str, Any]] = [{"id": "app", "kind": "app", "label": p.package_name, "severity": "info"}]
    edges: list[dict[str, Any]] = []
    if surface:
        for c in surface.exported_components:
            sev = "high" if c.unprotected else "info"
            nid = f"comp:{c.name}"
            nodes.append({"id": nid, "kind": c.component_type, "label": c.name, "severity": sev, "exported": True, "unprotected": c.unprotected})
            edges.append({"from": "app", "to": nid, "kind": "exports"})
        for d in surface.deeplinks:
            did = f"deep:{d}"
            nodes.append({"id": did, "kind": "deeplink", "label": d, "severity": "med"})
            edges.append({"from": "app", "to": did, "kind": "deeplink"})
        for n in surface.native_libraries:
            nid = f"native:{n.path}"
            nodes.append({"id": nid, "kind": "native", "label": n.path, "severity": "med", "arch": n.arch})
            edges.append({"from": "app", "to": nid, "kind": "links"})
    return {"project_id": p.id, "nodes": nodes, "edges": edges}


# ─── correlator + hook generator (intelligence layer) ─────────────────────

@app.get("/v1/projects/{project_id}/correlations")
async def project_correlations(project_id: str) -> list[dict[str, Any]]:
    """Run the correlator against the project's findings."""
    p = _require_project(project_id)
    if not p.attack_surface:
        return []
    chains = FindingCorrelator().correlate(p.attack_surface.findings)
    return [
        {
            "finding_ids": [f.id for f in c.findings],
            "confidence": c.confidence,
            "narrative": c.attack_narrative,
            "combined_severity": c.combined_severity.value,
        }
        for c in chains
    ]


@app.get("/v1/projects/{project_id}/hooks")
async def project_hooks(project_id: str) -> list[dict[str, Any]]:
    """Auto-hooks generated from the project's static surface (platform-aware)."""
    p = _require_project(project_id)
    if not p.attack_surface:
        return []
    try:
        hooks = HookGenerator().for_attack_surface(p.attack_surface, platform=p.platform)
    except TypeError:
        # Back-compat — older signature without `platform`.
        hooks = HookGenerator().for_attack_surface(p.attack_surface)
    return [
        {
            "name": h.name,
            "description": h.description,
            "script": h.script,
            "source_finding_id": h.source_finding_id,
        }
        for h in hooks
    ]


# ─── traffic + dynamic events (screens 12 / 13 / 14) ──────────────────────

@app.get("/v1/projects/{project_id}/traffic")
async def project_traffic(project_id: str, limit: int = 200) -> dict[str, Any]:
    """Screen 14 — captured traffic, joined with sensitive-flag findings.

    Reads from the dynamic_events SQLite table (channel='net') populated by the
    Frida + Burp engines. Returns sample fixtures when the project has no
    captured traffic yet so the UI has something to render.
    """
    nexus: MedusaNexus = app.state.nexus
    p = _require_project(project_id)
    rows = nexus.db._conn.execute(  # noqa: SLF001 - intentional thin wrapper
        "SELECT ts, channel, payload FROM dynamic_events WHERE project_id = ? AND channel = 'net' ORDER BY id DESC LIMIT ?",
        (p.id, limit),
    ).fetchall()
    captured: list[dict[str, Any]] = []
    for row in rows:
        try:
            captured.append({"ts": row["ts"], **json.loads(row["payload"])})
        except Exception:  # noqa: BLE001
            continue
    return {"project_id": p.id, "captured": captured, "count": len(captured)}


@app.get("/v1/projects/{project_id}/moxy-traffic")
async def project_moxy_traffic(
    project_id: str,
    limit: int = 1000,
    moxy_project: int | None = None,
    match_only: bool = False,
) -> dict[str, Any]:
    """Pull live HTTP flows from a Moxy workspace and tag them for this APK.

    Strategy:
      * If ``moxy_project`` is given, fetch from that workspace verbatim.
      * Otherwise let MoxyEngine.pick_project pick by name (package_name match
        → updated_at fallback). The picked workspace id round-trips in the
        response so the UI can show it / let the user override.
      * ``match_only=true`` filters server-side to flows whose host is in the
        project's discovered API map (handy when Moxy is collecting ambient
        traffic and you only want this APK's). Default is false so the UI can
        show everything and just *highlight* matches.

    Returns the same shape as /traffic so the SPA renders both in one table.
    """
    nexus: MedusaNexus = app.state.nexus
    p = _require_project(project_id)
    moxy = nexus.engines.get("moxy")
    if moxy is None:
        raise HTTPException(503, "moxy engine not registered")

    # Build the project's known-host set from the api-map (URL endpoints
    # extracted statically + dynamic captures from prior runs).
    surface = p.attack_surface
    hosts: set[str] = set()
    if surface:
        for ep in surface.api_endpoints:
            _, url = _split_method_url(ep)
            host, _ = _split_host_path(url)
            if host:
                hosts.add(host)

    # Resolve the Moxy workspace.
    if moxy_project is not None:
        picked = {"id": int(moxy_project), "name": f"#{moxy_project}"}
    else:
        picked = await moxy.pick_project(p.package_name)  # type: ignore[attr-defined]
        if not picked:
            return {
                "project_id": p.id,
                "moxy_project": None,
                "captured": [],
                "count": 0,
                "available_projects": [],
                "hosts": sorted(hosts),
                "error": "moxy unreachable or no workspaces — run scripts/setup.sh --moxy",
            }

    flows = await moxy.fetch_flows(  # type: ignore[attr-defined]
        int(picked["id"]),
        limit=limit,
        hosts=hosts if match_only and hosts else None,
    )
    if match_only and hosts:
        flows = [f for f in flows if f.get("matches_project")]

    available = await moxy.list_projects()  # type: ignore[attr-defined]
    return {
        "project_id": p.id,
        "moxy_project": picked,
        "captured": flows,
        "count": len(flows),
        "available_projects": available,
        "hosts": sorted(hosts),
    }


# ─── dynamic session control (screen 12) ──────────────────────────────────

# In-memory session state — process-local. Survives within one uvicorn run only.
_SESSIONS: dict[str, dict[str, Any]] = {}


@app.post("/v1/projects/{project_id}/dynamic/start")
async def dynamic_start(
    project_id: str,
    hooks: str = Form(default=""),
) -> dict[str, Any]:
    """Spin up a (mock) Frida session for this project.

    `hooks` is a comma-separated list of hook names from /v1/projects/{id}/hooks.
    Returns a session id the UI can use for /events polling.
    """
    p = _require_project(project_id)
    hook_names = [h.strip() for h in hooks.split(",") if h.strip()]
    sid = uuid.uuid4().hex[:8]
    now = datetime.now(UTC).isoformat()
    _SESSIONS[sid] = {
        "session_id": sid,
        "project_id": p.id,
        "package": p.package_name,
        "hooks": hook_names,
        "status": "attached",
        "started_at": now,
        "log": [
            {"ts": now, "channel": "nexus", "line": f"[NEXUS] attaching to {p.package_name}"},
            {"ts": now, "channel": "nexus", "line": f"[NEXUS] hooks loaded: {len(hook_names)}"},
            {"ts": now, "channel": "nexus", "line": "[NEXUS] session active · spawn resumed"},
        ],
    }
    return _SESSIONS[sid]


@app.post("/v1/projects/{project_id}/dynamic/stop")
async def dynamic_stop(project_id: str, session_id: str = Form(...)) -> dict[str, Any]:
    sess = _SESSIONS.get(session_id)
    if not sess or sess["project_id"] != project_id:
        raise HTTPException(404, f"no session {session_id} for project {project_id}")
    sess["status"] = "detached"
    sess["log"].append({"ts": datetime.now(UTC).isoformat(), "channel": "nexus", "line": "[NEXUS] detached cleanly"})
    return sess


@app.post("/v1/projects/{project_id}/dynamic/events")
async def dynamic_events_ingest(project_id: str, request: Request) -> dict[str, Any]:
    """Frida hooks POST event batches here.

    Body: ``{"events": [{"channel": "ssl_pin", "payload": {...}}, …]}``

    Channels we know how to read on the other side:
      * ``ssl_pin``   — pinning-callback intercepts; powers Screen 16's
                        live status badges.
      * ``net``       — request/response summaries (older Frida + Burp
                        history both feed this).
      * ``crypto`` / ``intent`` / ``fs`` / ``clip`` — Dynamic console.

    The endpoint never validates the channel name; it's free-form on
    purpose so new hooks can introduce channels without a server-side
    rev. Timestamps are stamped here if the event didn't carry one.
    """
    p = _require_project(project_id)
    nexus: MedusaNexus = app.state.nexus
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid JSON: {exc}") from exc
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list):
        raise HTTPException(400, "missing 'events' array")
    stamped = 0
    now_iso = datetime.now(UTC).isoformat()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        channel = str(ev.get("channel") or "raw")[:32]
        ts = str(ev.get("ts") or now_iso)
        payload = ev.get("payload") or {k: v for k, v in ev.items() if k not in ("channel", "ts")}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        nexus.db.append_dynamic_event(p.id, ts, channel, payload)
        stamped += 1
    return {"ingested": stamped, "project_id": p.id}


@app.get("/v1/projects/{project_id}/dynamic/events")
async def dynamic_events(project_id: str, session_id: str | None = None) -> dict[str, Any]:
    """Poll endpoint for the live console.

    Returns existing session log if `session_id` is given, otherwise synthesizes
    a sample feed so the screen looks alive even before a real session runs.
    """
    p = _require_project(project_id)
    if session_id:
        sess = _SESSIONS.get(session_id)
        if not sess or sess["project_id"] != p.id:
            raise HTTPException(404, f"unknown session {session_id}")
        return sess
    # No session: synthesize. Stable across calls so the UI doesn't strobe.
    sample_lines = [
        {"channel": "nexus", "line": f"[NEXUS] no live session for {p.package_name}"},
        {"channel": "meta", "line": "[META  ] start a session via POST /dynamic/start"},
        {"channel": "meta", "line": "[META  ] hooks available at GET /hooks"},
    ]
    return {"session_id": None, "project_id": p.id, "status": "idle", "log": sample_lines}


# ─── pipelines (screen 24) ────────────────────────────────────────────────

_BUILTIN_PIPELINES = [
    {
        "name": "full_assessment",
        "title": "Full Security Assessment",
        "description": "Static fan-out → correlate → hook gen → dynamic → report.",
        "yaml": (
            "name: Full Security Assessment\n"
            "version: 1\n"
            "stages:\n"
            "  - name: intake\n    engine: apktool\n    action: decode\n"
            "  - name: static_scan\n    parallel: true\n    steps:\n"
            "      - { engine: jadx,   action: decompile }\n"
            "      - { engine: mobsf,  action: full_scan }\n"
            "      - { engine: ghidra, action: analyze_native_libs }\n"
            "  - name: dynamic_prep\n    engine: stheno\n    action: patch\n"
            "  - name: dynamic_analysis\n    engine: frida\n    action: run_session\n    duration: 300\n"
            "  - name: report\n    engine: reporter\n    action: generate\n    formats: [pdf, json]\n"
            "    mitigation_playbook: true\n"
        ),
    },
    {
        "name": "static_only",
        "title": "Static-only sweep",
        "description": "Cheap pass: decode + jadx + mobsf + secrets scan.",
        "yaml": (
            "name: Static Only\n"
            "version: 1\n"
            "stages:\n"
            "  - { engine: apktool, action: decode }\n"
            "  - { engine: jadx,    action: decompile }\n"
            "  - { engine: mobsf,   action: full_scan }\n"
            "  - { engine: reporter, action: generate, formats: [markdown] }\n"
        ),
    },
    {
        "name": "diff_run",
        "title": "Version diff",
        "description": "Re-run on a new APK build; emit a diff report only.",
        "yaml": (
            "name: Diff Run\n"
            "version: 1\n"
            "stages:\n"
            "  - { engine: apktool, action: decode }\n"
            "  - { engine: jadx,    action: decompile }\n"
            "  - { engine: reporter, action: generate, template: diff }\n"
        ),
    },
]


@app.get("/v1/pipelines")
async def list_pipelines() -> list[dict[str, Any]]:
    return _BUILTIN_PIPELINES


@app.get("/v1/pipelines/{name}")
async def get_pipeline(name: str) -> dict[str, Any]:
    for p in _BUILTIN_PIPELINES:
        if p["name"] == name:
            return p
    raise HTTPException(404, f"no pipeline named {name}")


@app.post("/v1/pipelines/{name}/run")
async def run_pipeline(name: str, project_id: str = Form(...)) -> dict[str, Any]:
    """Pretend to run the pipeline. Returns a manifest of what would happen.

    Real execution is wired in iteration 3 (orchestrator already runs the
    static fan-out — the rest is plumbing).
    """
    pipeline = next((p for p in _BUILTIN_PIPELINES if p["name"] == name), None)
    if not pipeline:
        raise HTTPException(404, f"no pipeline named {name}")
    p = _require_project(project_id)
    return {
        "pipeline": pipeline["name"],
        "project_id": p.id,
        "status": "queued",
        "message": "pipeline scheduling stubbed — orchestrator already ran on upload.",
    }


# ─── finding actions (screen 21) ──────────────────────────────────────────

@app.post("/v1/findings/{finding_id}/dismiss")
async def dismiss_finding(finding_id: str) -> dict[str, Any]:
    return _flip_finding(finding_id, confirmed=False, dismissed=True)


@app.post("/v1/findings/{finding_id}/confirm")
async def confirm_finding(finding_id: str) -> dict[str, Any]:
    return _flip_finding(finding_id, confirmed=True, dismissed=False)


def _flip_finding(finding_id: str, *, confirmed: bool, dismissed: bool) -> dict[str, Any]:
    """Rewrite a single finding inside its project payload."""
    nexus: MedusaNexus = app.state.nexus
    for row in nexus.db.list_projects():
        proj = nexus.db.load_project(row["id"])
        if not proj or not proj.attack_surface:
            continue
        for f in proj.attack_surface.findings:
            if f.id == finding_id:
                f.confirmed = confirmed
                # Persist. Note: dismissed isn't a model field; we record a
                # marker in the description for now (iteration 2 would split
                # this into its own column).
                if dismissed and "[dismissed]" not in (f.description or ""):
                    f.description = f"[dismissed] {f.description}"
                if not dismissed and (f.description or "").startswith("[dismissed] "):
                    f.description = f.description[len("[dismissed] "):]
                nexus.db.save_project(proj)
                return {"finding_id": finding_id, "confirmed": confirmed, "dismissed": dismissed}
    raise HTTPException(404, f"no finding with id {finding_id}")


# ─── tools / device actions (screen 26 + 06) ──────────────────────────────

@app.post("/v1/tools/run")
async def run_tool(action: str = Form(...), payload: str = Form(default="")) -> dict[str, Any]:
    """Generic trigger for the Tools page action buttons.

    Supported actions:
    - `frida.start`   — launch frida-server (delegates to /v1/device/frida/start)
    - `device.refresh` — re-probe device info
    - `doctor.recheck` — re-run health checks
    """
    nexus: MedusaNexus = app.state.nexus
    if action == "frida.start":
        return await device_frida_start()
    if action == "device.refresh":
        return await device_info()
    if action == "doctor.recheck":
        return {"engines": await nexus.doctor()}
    if action == "noop":
        return {"action": action, "payload": payload, "status": "ok"}
    raise HTTPException(400, f"unknown action: {action}")


# ─── helpers ──────────────────────────────────────────────────────────────

def _worst_severity(counts: dict[str, int]) -> str:
    for sev in ("critical", "high", "medium", "low", "info"):
        if counts.get(sev, 0) > 0:
            return sev
    return "info"
