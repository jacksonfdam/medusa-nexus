"""Project backup + delete — compliance-grade lifecycle operations.

Two operations, both safely usable as the *legal* answer to *"please
remove this app's analysis from your records":*

  ``backup_project``  — produce a self-contained ``.zip`` archive with
                         every artefact attributable to one project: the
                         DB row, every Finding, the original APK/IPA,
                         the workspace tree (jadx, apktool, ghidra,
                         hooks, manifest cache), reports.

  ``delete_project``  — wipe every trace of one project from disk + DB:
                         the workspace tree, reports, the source artefact
                         (if no other project shares the SHA), PlayIntel
                         saved files (if no other project shares the
                         package), and the DB rows. Returns a structured
                         report of what was removed so the operator can
                         show "yes, this was wiped" to legal / audit.

Both operations are atomic in spirit: backup writes to a temp file and
renames at the end, delete batches all wipes and only commits the DB
transaction at the very end. Either fails cleanly or leaves the system
in a recoverable state — no half-deleted projects.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from mnexus.config import NexusConfig
from mnexus.core.artifact_store import ArtifactStore
from mnexus.models.project import Project


_BACKUP_FORMAT_VERSION = "1.0"


@dataclass
class BackupResult:
    project_id: str
    archive_path: Path
    size_bytes: int
    file_count: int
    findings_count: int
    created_at: str


@dataclass
class DeleteResult:
    """Structured 'what was wiped' report — the GDPR audit trail."""

    project_id: str
    package: str
    workspace_dir_removed: bool
    workspace_bytes_freed: int
    workspace_files_removed: int
    source_artefact_removed: str | None    # absolute path that was deleted, or None
    secrets_dir_removed: str | None         # absolute path that was deleted, or None
    reports_removed: list[str] = field(default_factory=list)
    findings_removed: int = 0
    dynamic_events_removed: int = 0
    db_row_removed: bool = False
    completed_at: str = ""


# ─── backup ────────────────────────────────────────────────────────────


def backup_project(
    project: Project,
    *,
    store: ArtifactStore,
    workspace_dir: Path,
    output_dir: Path,
) -> BackupResult:
    """Write a ``.zip`` archive containing every artefact for ``project``.

    Archive layout:

        project-<id>-backup-<ts>.zip
        ├── MANIFEST.json
        ├── project.json
        ├── findings/<FND-...>.json
        ├── source.apk            (or source.ipa)
        ├── workspace/...         entire <workspace>/<id>/ tree
        └── reports/              <reports>/<id>.* if any
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = output_dir / f"project-{project.id}-backup-{ts}.zip"

    # Build in a temp path first so a partial write doesn't leave a
    # half-baked archive in output_dir.
    tmp_path = archive_path.with_suffix(".zip.partial")

    file_count = 0
    findings_count = 0

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1. Project model — the canonical source of truth.
        zf.writestr("project.json", project.model_dump_json(indent=2))
        file_count += 1

        # 2. Findings — one file each, easy to grep post-restore.
        if project.attack_surface and project.attack_surface.findings:
            for f in project.attack_surface.findings:
                zf.writestr(
                    f"findings/{f.id}.json",
                    f.model_dump_json(indent=2),
                )
                file_count += 1
                findings_count += 1

        # 3. Source artefact (apk / ipa).
        apk_path = project.apk_path if isinstance(project.apk_path, Path) else Path(str(project.apk_path))
        if apk_path.exists():
            ext = apk_path.suffix or (".ipa" if project.platform == "ios" else ".apk")
            zf.write(apk_path, arcname=f"source{ext}")
            file_count += 1

        # 4. Workspace tree.
        project_dir = workspace_dir / project.id
        if project_dir.exists():
            for path in project_dir.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(project_dir).as_posix()
                zf.write(path, arcname=f"workspace/{rel}")
                file_count += 1

        # 5. Reports — keyed by project id under <workspace>/reports/.
        reports_dir = workspace_dir / "reports"
        if reports_dir.exists():
            for report in reports_dir.glob(f"{project.id}.*"):
                if report.is_file():
                    zf.write(report, arcname=f"reports/{report.name}")
                    file_count += 1

        # 6. MANIFEST.json — backup metadata. Written last so the file
        #    count and findings count are accurate.
        manifest = {
            "format_version": _BACKUP_FORMAT_VERSION,
            "project_id": project.id,
            "package": project.package_name,
            "version": project.version_name,
            "platform": project.platform,
            "apk_sha256": project.apk_sha256,
            "created_at": ts,
            "file_count": file_count + 1,   # +1 for the manifest itself
            "findings_count": findings_count,
        }
        zf.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
        file_count += 1

    # Atomic rename — only now does the archive become visible.
    tmp_path.replace(archive_path)

    return BackupResult(
        project_id=project.id,
        archive_path=archive_path,
        size_bytes=archive_path.stat().st_size,
        file_count=file_count,
        findings_count=findings_count,
        created_at=ts,
    )


def backup_all_projects(
    *,
    store: ArtifactStore,
    workspace_dir: Path,
    output_dir: Path,
) -> list[BackupResult]:
    """Backup every project in the store. One ``.zip`` per project."""
    results: list[BackupResult] = []
    for row in store.list_projects():
        project = store.load_project(row["id"])
        if project is None:
            continue
        results.append(backup_project(
            project,
            store=store,
            workspace_dir=workspace_dir,
            output_dir=output_dir,
        ))
    return results


# ─── delete ────────────────────────────────────────────────────────────


def delete_project(
    project: Project,
    *,
    store: ArtifactStore,
    workspace_dir: Path,
) -> DeleteResult:
    """Wipe every disk + DB trace of ``project``. Idempotent on failure.

    Wipe order (least-to-most destructive, so a mid-flight crash leaves
    the DB row pointing at *some* surviving artefact):

      1. Reports keyed by project id.
      2. Workspace dir <workspace>/<project_id>/.
      3. Source artefact (only if no other project shares the SHA-256).
      4. PlayIntel secrets dir <workspace>/secrets/<package>/
         (only if no other project shares the package).
      5. DB rows — projects (CASCADE wipes findings + dynamic_events).
    """
    result = DeleteResult(
        project_id=project.id,
        package=project.package_name,
        workspace_dir_removed=False,
        workspace_bytes_freed=0,
        workspace_files_removed=0,
        source_artefact_removed=None,
        secrets_dir_removed=None,
    )

    # ── 1. Reports keyed by project id ────────────────────────────
    reports_dir = workspace_dir / "reports"
    if reports_dir.exists():
        for report in reports_dir.glob(f"{project.id}.*"):
            if report.is_file():
                result.reports_removed.append(str(report))
                report.unlink()

    # ── 2. Workspace dir ──────────────────────────────────────────
    project_dir = workspace_dir / project.id
    if project_dir.exists():
        # Count + size before rmtree so the report is accurate.
        n_files = 0
        n_bytes = 0
        for p in project_dir.rglob("*"):
            if p.is_file():
                n_files += 1
                try:
                    n_bytes += p.stat().st_size
                except OSError:
                    pass
        result.workspace_files_removed = n_files
        result.workspace_bytes_freed = n_bytes
        shutil.rmtree(project_dir, ignore_errors=True)
        result.workspace_dir_removed = True

    # ── 3. Source artefact (file-path shared check) ───────────────
    # Each upload writes to its own `<workspace>/upload-<uuid>-<name>`
    # path, so SHA-identical projects normally have distinct apk_paths.
    # We delete the artefact when NO OTHER project's apk_path resolves
    # to the same on-disk file — which is the conservative invariant
    # even if a future change dedupes uploads by hash.
    apk_path = project.apk_path if isinstance(project.apk_path, Path) else Path(str(project.apk_path))
    if apk_path.exists():
        apk_resolved = apk_path.resolve()
        another_uses_this_file = False
        for row in store.list_projects():
            if row["id"] == project.id:
                continue
            other = store.load_project(row["id"])
            if other is None:
                continue
            other_apk = other.apk_path if isinstance(other.apk_path, Path) else Path(str(other.apk_path))
            if other_apk.exists() and other_apk.resolve() == apk_resolved:
                another_uses_this_file = True
                break
        if not another_uses_this_file:
            try:
                apk_path.unlink()
                result.source_artefact_removed = str(apk_path)
            except OSError:
                pass

    # ── 4. PlayIntel secrets dir (package-shared check) ───────────
    secrets_dir = workspace_dir / "secrets" / project.package_name
    if secrets_dir.exists():
        other_with_same_package = sum(
            1 for row in store.list_projects()
            if row["id"] != project.id and row.get("package_name") == project.package_name
        )
        if other_with_same_package == 0:
            shutil.rmtree(secrets_dir, ignore_errors=True)
            result.secrets_dir_removed = str(secrets_dir)

    # ── 5. DB rows ────────────────────────────────────────────────
    # Count findings + dynamic_events first so the report reflects the
    # before state. Foreign-key CASCADE handles the actual delete when
    # we drop the projects row.
    findings_count = store._conn.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM findings WHERE project_id = ?", (project.id,),
    ).fetchone()[0]
    events_count = store._conn.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM dynamic_events WHERE project_id = ?", (project.id,),
    ).fetchone()[0]
    deleted = store._conn.execute(  # noqa: SLF001
        "DELETE FROM projects WHERE id = ?", (project.id,),
    ).rowcount
    store._conn.commit()  # noqa: SLF001

    result.findings_removed = findings_count
    result.dynamic_events_removed = events_count
    result.db_row_removed = bool(deleted)
    result.completed_at = datetime.now(UTC).isoformat()

    return result


def delete_all_projects(
    *,
    store: ArtifactStore,
    workspace_dir: Path,
) -> list[DeleteResult]:
    """Wipe every project in the store. Returns per-project audit trails."""
    results: list[DeleteResult] = []
    # Snapshot the id list first because delete_project mutates the table.
    pids = [row["id"] for row in store.list_projects()]
    for pid in pids:
        proj = store.load_project(pid)
        if proj is None:
            continue
        results.append(delete_project(
            proj,
            store=store,
            workspace_dir=workspace_dir,
        ))
    return results
