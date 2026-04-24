"""Project — one APK, one timeline, one risk score."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from mnexus.models.attack_surface import AttackSurface
from mnexus.models.finding import Finding


class Project(BaseModel):
    """A unit of work. Spawned by an APK drop, lives forever in SQLite."""

    id: str = Field(default_factory=lambda: f"PRJ-{uuid4().hex[:8].upper()}")
    name: str
    apk_path: Path
    apk_sha256: str
    package_name: str
    version_name: str
    version_code: int | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    attack_surface: AttackSurface | None = None
    suggested_hooks: list[str] = Field(default_factory=list, description="Auto-generated Frida scripts.")
    dynamic_results: list[Finding] = Field(default_factory=list)

    @classmethod
    def from_apk(cls, apk_path: Path, package_name: str, version: str, **kwargs: object) -> Project:
        """Hash the APK and mint a project. SHA-256 because it's 2026, not 2006."""
        sha256 = hashlib.sha256(apk_path.read_bytes()).hexdigest()
        return cls(
            name=f"{package_name}_{version}",
            apk_path=apk_path,
            apk_sha256=sha256,
            package_name=package_name,
            version_name=version,
            **kwargs,  # type: ignore[arg-type]
        )
