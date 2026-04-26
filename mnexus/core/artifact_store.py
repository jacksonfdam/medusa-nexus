"""ArtifactStore — SQLite for projects, findings, dynamic session logs.

Local-first by design. If the network goes away, the platform still works.
Portable: copy the `.sqlite3` file and the `workspace/` folder, take your
assessment with you.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mnexus.models.project import Project


class ArtifactStore:
    """Thin SQLite wrapper. No ORM on purpose — three tables, zero drama."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                package_name TEXT NOT NULL,
                version_name TEXT NOT NULL,
                apk_sha256 TEXT NOT NULL,
                payload TEXT NOT NULL,          -- full Project JSON
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'android'
            );

            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                source_engine TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,          -- full Finding JSON
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dynamic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                channel TEXT NOT NULL,          -- crypto | intent | fs | clip | net | raw
                payload TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_findings_project ON findings(project_id);
            CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
            """
        )
        # Migration: add `platform` column to legacy projects tables that
        # predate the iOS work. SQLite has no `IF NOT EXISTS` for ALTER TABLE,
        # so we check pragma first.
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "platform" not in cols:
            self._conn.execute("ALTER TABLE projects ADD COLUMN platform TEXT NOT NULL DEFAULT 'android'")
        self._conn.commit()

    # ─── projects ───

    def save_project(self, project: Project) -> None:
        payload = project.model_dump_json()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO projects
                (id, name, package_name, version_name, apk_sha256, payload, created_at, updated_at, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project.id,
                project.name,
                project.package_name,
                project.version_name,
                project.apk_sha256,
                payload,
                project.created_at.isoformat(),
                project.updated_at.isoformat(),
                project.platform,
            ),
        )
        if project.attack_surface:
            for f in project.attack_surface.findings:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO findings
                        (id, project_id, severity, category, source_engine, confirmed, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f.id,
                        project.id,
                        f.severity.value,
                        f.category.value,
                        f.source_engine,
                        int(f.confirmed),
                        f.model_dump_json(),
                        f.created_at.isoformat(),
                    ),
                )
        self._conn.commit()

    def load_project(self, project_id: str) -> Project | None:
        row = self._conn.execute("SELECT payload FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return None
        return Project.model_validate_json(row["payload"])

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, name, package_name, version_name, updated_at, platform FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── dynamic events ───

    def append_dynamic_event(self, project_id: str, ts: str, channel: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO dynamic_events (project_id, ts, channel, payload) VALUES (?, ?, ?, ?)",
            (project_id, ts, channel, json.dumps(payload, default=str)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
