"""FastAPI surface for the web UI.

Local-first: bound to 127.0.0.1 by default. Don't expose this to the internet.
You are holding APKs, keys, and traffic captures. Act accordingly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus
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
    app.state.nexus = MedusaNexus(NexusConfig.from_env())
    yield
    app.state.nexus.db.close()


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


# ─── shell + favicon ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    html = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


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


# ─── upload ───────────────────────────────────────────────────────────────

@app.post("/v1/apks/upload")
async def upload_apk(
    file: UploadFile = File(...),
    package: str | None = Form(default=None),
    version: str | None = Form(default=None),
) -> dict[str, Any]:
    """Receive an APK, detect package+version if absent, run ingest_apk.

    Returns the stored Project JSON. The SPA redirects to
    /#/project/{project_id}/overview on success.
    """
    nexus: MedusaNexus = app.state.nexus
    workspace = nexus.config.workspace
    workspace.mkdir(parents=True, exist_ok=True)

    if not file.filename:
        raise HTTPException(400, "no filename on upload")

    upload_id = uuid.uuid4().hex[:8]
    safe_name = Path(file.filename).name
    apk_path = workspace / f"upload-{upload_id}-{safe_name}"
    digest = hashlib.sha256()
    size = 0
    with apk_path.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            fh.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        apk_path.unlink(missing_ok=True)
        raise HTTPException(400, "uploaded file was empty")

    # Detect package + version if the caller didn't supply them.
    if not package or not version:
        detected = await _detect_manifest(nexus, apk_path)
        package = package or detected.get("package") or ""
        version = version or detected.get("version_name") or "unknown"

    if not package:
        apk_path.unlink(missing_ok=True)
        raise HTTPException(
            400,
            "could not auto-detect package name — pass `package` form field "
            "(or install apktool so the detection path works)",
        )

    try:
        project = await nexus.ingest_apk(apk_path, package_name=package, version=version)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"ingest failed: {exc.__class__.__name__}: {exc}") from exc

    return {
        "project_id": project.id,
        "apk_size_bytes": size,
        "apk_sha256": digest.hexdigest(),
        "package": project.package_name,
        "version": project.version_name,
        "project": project.model_dump(mode="json"),
    }


async def _detect_manifest(nexus: MedusaNexus, apk_path: Path) -> dict[str, str]:
    """Run apktool to extract the manifest. Empty dict on any failure."""
    engine = nexus.engines.get("apktool")
    if engine is None:
        return {}
    try:
        return await engine.extract_manifest(apk_path)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return {}


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
async def device_packages(filter: str = "") -> list[dict[str, Any]]:
    """List installed packages on the connected device. `filter` is a grep-string."""
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not shutil.which(nexus.config.adb_path) or not await adb.is_device_connected():  # type: ignore[attr-defined]
        return []
    packages = await adb.list_packages(filter)  # type: ignore[attr-defined]
    return [{"package": p} for p in packages]


@app.post("/v1/device/pull")
async def device_pull(package: str = Form(...)) -> dict[str, Any]:
    """Pull the APK(s) for a package off the device into the workspace."""
    nexus: MedusaNexus = app.state.nexus
    adb = nexus.engines["adb"]
    if not await adb.is_device_connected():  # type: ignore[attr-defined]
        raise HTTPException(503, "no device connected")
    out_dir = nexus.config.workspace / "pulled" / package
    pulled = await adb.pull_apk(package, out_dir)  # type: ignore[attr-defined]
    return {"package": package, "files": [str(p) for p in pulled], "count": len(pulled)}


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
        "serial": serial or "—",
        "command": " ".join(full),
        "exit": proc.returncode,
        "output": text[:4000],  # cap so we never blow up the log
        "note": note,
    }
    _ADB_LOG.append(entry)
    return proc.returncode, text


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


# ─── recipes (Medusa / Stheno on disk) ───────────────────────────────────

@app.get("/v1/recipes")
async def list_recipes() -> list[dict[str, Any]]:
    """Enumerate Medusa/Stheno modules on disk + the always-there auto ones."""
    nexus: MedusaNexus = app.state.nexus
    recipes: list[dict[str, Any]] = []

    if nexus.config.medusa_path and nexus.config.medusa_path.exists():
        modules_dir = nexus.config.medusa_path / "modules"
        if modules_dir.exists():
            for path in sorted(modules_dir.glob("*.med")):
                recipes.append({
                    "name": path.stem,
                    "origin": "medusa",
                    "category": _guess_category(path.stem),
                    "description": f"Medusa recipe loaded from {path.name}",
                    "compatibility": "frida ≥ 16",
                    "path": str(path),
                })

    if nexus.config.stheno_path and nexus.config.stheno_path.exists():
        recipes.append({
            "name": "inject_frida_gadget",
            "origin": "stheno",
            "category": "PATCH",
            "description": "Stheno patches the APK with frida-gadget. No root? No problem.",
            "compatibility": "non-rooted · re-sign required",
        })

    # Always-on auto recipes, generated from findings at runtime.
    recipes.append({
        "name": "cipher_key_leak",
        "origin": "auto",
        "category": "CRYPTO",
        "description": "Logs SecretKeySpec ctor args + Cipher.doFinal in/out. Bring popcorn.",
        "compatibility": "auto-generated from findings",
    })
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


@app.get("/v1/recipes/{name}/script")
async def recipe_script(name: str) -> dict[str, Any]:
    """Return the Frida script text for a recipe (unevaluated)."""
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
        },
        "workspace": str(cfg.workspace),
        "db_path": str(cfg.db_path),
        "parallel_engines": cfg.parallel_engines,
        "default_dynamic_duration_s": cfg.default_dynamic_duration_s,
    }


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


@app.get("/v1/projects/{project_id}/api-map")
async def project_api_map(project_id: str) -> dict[str, Any]:
    """Screen 15 — API endpoint tree (host → path → methods)."""
    p = _require_project(project_id)
    surface = p.attack_surface
    endpoints = surface.api_endpoints if surface else []

    # Group by host. Each endpoint string is a URL or "METHOD url" or "host/path".
    tree: dict[str, dict[str, list[str]]] = {}
    for ep in endpoints:
        method, url = _split_method_url(ep)
        host, path = _split_host_path(url)
        tree.setdefault(host, {})
        tree[host].setdefault(path, [])
        if method not in tree[host][path]:
            tree[host][path].append(method)
    flagged = [
        f.model_dump(mode="json")
        for f in (surface.findings if surface else [])
        if f.category is FindingCategory.NETWORK
    ]
    return {"project_id": p.id, "tree": tree, "endpoints": endpoints, "flagged": flagged}


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
async def project_ssl_map(project_id: str) -> dict[str, Any]:
    """Screen 16 — SSL pinning map: domains × library × bypass strategy."""
    p = _require_project(project_id)
    surface = p.attack_surface
    if not surface:
        return {"project_id": p.id, "rows": [], "pinning_detected": False}

    # Hosts pulled from api_endpoints.
    hosts = sorted({_split_host_path(_split_method_url(ep)[1])[0] for ep in surface.api_endpoints})
    library = surface.ssl_pinning_library or "unknown"
    bypass = {
        "okhttp": "okhttp_certificate_pinner_bypass",
        "trustmanager": "trustmanager_neuter",
        "custom": "ssl_universal_bypass",
    }.get(library, "ssl_universal_bypass")
    rows = [
        {
            "host": host,
            "library": library if surface.ssl_pinning_detected else "—",
            "pinned": surface.ssl_pinning_detected,
            "bypass_recipe": bypass if surface.ssl_pinning_detected else None,
        }
        for host in hosts
    ]
    return {
        "project_id": p.id,
        "pinning_detected": surface.ssl_pinning_detected,
        "library": library,
        "rows": rows,
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
    """Auto-hooks generated from the project's static surface."""
    p = _require_project(project_id)
    if not p.attack_surface:
        return []
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
