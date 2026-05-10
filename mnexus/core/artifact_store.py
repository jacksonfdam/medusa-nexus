"""ArtifactStore — SQLite for projects, findings, dynamic session logs.

Local-first by design. If the network goes away, the platform still works.
Portable: copy the `.sqlite3` file and the `workspace/` folder, take your
assessment with you.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnexus.models.play_account import PlayAccount
from mnexus.models.play_scan import PlayScanRecord
from mnexus.models.project import Project


class ArtifactStore:
    """Thin SQLite wrapper. No ORM on purpose — three tables, zero drama."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        # Sensitive credentials live in this file; restrict perms.
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass

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

            CREATE TABLE IF NOT EXISTS play_accounts (
                name TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                aas_token TEXT NOT NULL,
                gsfid TEXT NOT NULL DEFAULT '',
                locale TEXT NOT NULL DEFAULT 'en-US',
                notes TEXT NOT NULL DEFAULT '',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            -- Enforce at most one default — the application layer also
            -- normalises this (clear-then-set) but the constraint is the
            -- belt that keeps the DB honest under concurrent writes.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_play_accounts_one_default
                ON play_accounts(is_default) WHERE is_default = 1;

            CREATE TABLE IF NOT EXISTS playintel_scans (
                id TEXT PRIMARY KEY,
                package TEXT NOT NULL,
                version_name TEXT NOT NULL DEFAULT '',
                version_code INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                source_label TEXT NOT NULL,
                apk_sha256 TEXT NOT NULL DEFAULT '',
                scanned_at TEXT NOT NULL,
                firebase_project_count INTEGER NOT NULL DEFAULT 0,
                confirmed_secrets_count INTEGER NOT NULL DEFAULT 0,
                suspected_secrets_count INTEGER NOT NULL DEFAULT 0,
                vulnerability_count INTEGER NOT NULL DEFAULT 0,
                findings_count INTEGER NOT NULL DEFAULT 0,
                saved_files_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL              -- full /scan JSON
            );
            CREATE INDEX IF NOT EXISTS idx_playintel_scans_package
                ON playintel_scans(package, scanned_at DESC);
            CREATE INDEX IF NOT EXISTS idx_playintel_scans_recent
                ON playintel_scans(scanned_at DESC);
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

    def find_by_sha256(self, apk_sha256: str) -> Project | None:
        """Return the most-recently-updated project that matches a given APK hash.

        Powers dedup on upload — if the same .apk lands twice (drag-drop, CLI,
        apkeep fetch, …) we surface the existing project instead of minting a
        new one. Same hash ⇒ same artefact ⇒ same findings.
        """
        if not apk_sha256:
            return None
        row = self._conn.execute(
            "SELECT payload FROM projects WHERE apk_sha256 = ? ORDER BY updated_at DESC LIMIT 1",
            (apk_sha256,),
        ).fetchone()
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

    # ─── play accounts ───

    def save_play_account(self, account: PlayAccount) -> None:
        """Insert or update a stored Play identity.

        If ``account.is_default`` is true, every other account is
        demoted first so the partial unique index above never gets
        violated. The ``updated_at`` is bumped to now on every write.
        """
        account.updated_at = datetime.now(UTC)
        with self._conn:
            if account.is_default:
                self._conn.execute(
                    "UPDATE play_accounts SET is_default = 0 WHERE name != ?",
                    (account.name,),
                )
            self._conn.execute(
                """
                INSERT INTO play_accounts
                    (name, email, aas_token, gsfid, locale, notes,
                     is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    email = excluded.email,
                    aas_token = excluded.aas_token,
                    gsfid = excluded.gsfid,
                    locale = excluded.locale,
                    notes = excluded.notes,
                    is_default = excluded.is_default,
                    updated_at = excluded.updated_at
                """,
                (
                    account.name,
                    account.email,
                    account.aas_token,
                    account.gsfid,
                    account.locale,
                    account.notes,
                    int(account.is_default),
                    account.created_at.isoformat(),
                    account.updated_at.isoformat(),
                ),
            )

    def get_play_account(self, name: str) -> PlayAccount | None:
        row = self._conn.execute(
            "SELECT * FROM play_accounts WHERE name = ?", (name,)
        ).fetchone()
        return _row_to_account(row) if row else None

    def get_default_play_account(self) -> PlayAccount | None:
        row = self._conn.execute(
            "SELECT * FROM play_accounts WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        return _row_to_account(row) if row else None

    def list_play_accounts(self) -> list[PlayAccount]:
        rows = self._conn.execute(
            "SELECT * FROM play_accounts ORDER BY is_default DESC, name ASC"
        ).fetchall()
        return [_row_to_account(r) for r in rows]

    def set_default_play_account(self, name: str) -> bool:
        """Promote ``name`` to default. Returns ``False`` if it doesn't exist."""
        with self._conn:
            cur = self._conn.execute(
                "SELECT 1 FROM play_accounts WHERE name = ?", (name,)
            )
            if not cur.fetchone():
                return False
            self._conn.execute("UPDATE play_accounts SET is_default = 0")
            self._conn.execute(
                "UPDATE play_accounts SET is_default = 1, updated_at = ? WHERE name = ?",
                (datetime.now(UTC).isoformat(), name),
            )
        return True

    def delete_play_account(self, name: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM play_accounts WHERE name = ?", (name,)
            )
        return cur.rowcount > 0

    def update_play_account_runtime_state(
        self, name: str, *, gsfid: str | None = None
    ) -> None:
        """Persist runtime-discovered state (currently just a freshly minted
        GSFID after /checkin). Touches updated_at so list views surface the
        change.
        """
        if gsfid is None:
            return
        with self._conn:
            self._conn.execute(
                "UPDATE play_accounts SET gsfid = ?, updated_at = ? WHERE name = ?",
                (gsfid, datetime.now(UTC).isoformat(), name),
            )

    # ─── playintel scan history ───

    def save_play_scan(self, record: PlayScanRecord) -> None:
        """Persist one PlayIntel scan run to the history table.

        The full payload is JSON-serialised once at write time so the
        list view can stick to denormalised counts and only the detail
        view pays the round-trip parse cost.
        """
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO playintel_scans
                    (id, package, version_name, version_code, source, source_label,
                     apk_sha256, scanned_at,
                     firebase_project_count, confirmed_secrets_count, suspected_secrets_count,
                     vulnerability_count, findings_count, saved_files_count,
                     payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.package,
                    record.version_name,
                    record.version_code,
                    record.source,
                    record.source_label,
                    record.apk_sha256,
                    record.scanned_at.isoformat(),
                    record.firebase_project_count,
                    record.confirmed_secrets_count,
                    record.suspected_secrets_count,
                    record.vulnerability_count,
                    record.findings_count,
                    record.saved_files_count,
                    json.dumps(record.payload),
                ),
            )

    def list_play_scans(
        self,
        *,
        package: str | None = None,
        limit: int = 100,
    ) -> list[PlayScanRecord]:
        """Recent-first scan history.

        ``package`` filters to one app's history. ``limit`` caps the
        result set so very long-running deployments don't drag the
        listing endpoint.
        """
        if package:
            rows = self._conn.execute(
                "SELECT * FROM playintel_scans WHERE package = ? "
                "ORDER BY scanned_at DESC LIMIT ?",
                (package, max(1, min(int(limit), 1000))),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM playintel_scans ORDER BY scanned_at DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [_row_to_play_scan(r) for r in rows]

    def get_play_scan(self, scan_id: str) -> PlayScanRecord | None:
        row = self._conn.execute(
            "SELECT * FROM playintel_scans WHERE id = ?", (scan_id,)
        ).fetchone()
        return _row_to_play_scan(row) if row else None

    def delete_play_scan(self, scan_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM playintel_scans WHERE id = ?", (scan_id,)
            )
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()


def _row_to_play_scan(row: sqlite3.Row) -> PlayScanRecord:
    """Adapt a sqlite Row into a PlayScanRecord; payload is rehydrated
    from JSON. Defensively tolerates malformed JSON by falling back to
    an empty dict — a poisoned row shouldn't crash the listing
    endpoint."""
    try:
        payload = json.loads(row["payload"]) if row["payload"] else {}
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return PlayScanRecord(
        id=row["id"],
        package=row["package"],
        version_name=row["version_name"] or "",
        version_code=int(row["version_code"] or 0),
        source=row["source"],
        source_label=row["source_label"],
        apk_sha256=row["apk_sha256"] or "",
        scanned_at=datetime.fromisoformat(row["scanned_at"]),
        firebase_project_count=int(row["firebase_project_count"] or 0),
        confirmed_secrets_count=int(row["confirmed_secrets_count"] or 0),
        suspected_secrets_count=int(row["suspected_secrets_count"] or 0),
        vulnerability_count=int(row["vulnerability_count"] or 0),
        findings_count=int(row["findings_count"] or 0),
        saved_files_count=int(row["saved_files_count"] or 0),
        payload=payload,
    )


def _row_to_account(row: sqlite3.Row) -> PlayAccount:
    """Adapt a sqlite Row into a PlayAccount; tolerates missing columns
    only insofar as the schema migration ran first."""
    return PlayAccount(
        name=row["name"],
        email=row["email"],
        aas_token=row["aas_token"],
        gsfid=row["gsfid"] or "",
        locale=row["locale"] or "en-US",
        notes=row["notes"] or "",
        is_default=bool(row["is_default"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
