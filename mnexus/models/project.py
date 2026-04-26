"""Project — one mobile artifact (APK or IPA), one timeline, one risk score."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from mnexus.models.attack_surface import AttackSurface
from mnexus.models.finding import Finding


Platform = Literal["android", "ios"]


class Project(BaseModel):
    """A unit of work. Spawned by an APK or IPA drop, lives forever in SQLite.

    `package_name` is reverse-DNS for both platforms — Android calls it the
    "package name", iOS calls it the "bundle id". The field name stays
    `package_name` for backward compatibility with stored payloads; access
    `bundle_id` on iOS projects via the property below for clarity.
    """

    id: str = Field(default_factory=lambda: f"PRJ-{uuid4().hex[:8].upper()}")
    name: str
    apk_path: Path  # kept generic — points to the .apk OR the .ipa file
    apk_sha256: str
    package_name: str
    version_name: str
    version_code: int | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    platform: Platform = "android"

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    attack_surface: AttackSurface | None = None
    suggested_hooks: list[str] = Field(default_factory=list, description="Auto-generated Frida scripts.")
    dynamic_results: list[Finding] = Field(default_factory=list)

    @property
    def bundle_id(self) -> str:
        """iOS-flavoured alias for `package_name`. Same value, clearer name."""
        return self.package_name

    @property
    def artifact_path(self) -> Path:
        """Platform-agnostic alias for `apk_path` — points at the .apk or .ipa."""
        return self.apk_path

    @classmethod
    def from_apk(cls, apk_path: Path, package_name: str, version: str, **kwargs: object) -> Project:
        """Hash the artifact and mint a project. SHA-256 because it's 2026.

        Defaults `platform` based on the file suffix; pass `platform=` explicitly
        to override (the orchestrator does this once detection runs).
        """
        sha256 = hashlib.sha256(apk_path.read_bytes()).hexdigest()
        platform: Platform = kwargs.pop("platform", None) or _platform_from_suffix(apk_path)  # type: ignore[assignment]
        return cls(
            name=f"{package_name}_{version}",
            apk_path=apk_path,
            apk_sha256=sha256,
            package_name=package_name,
            version_name=version,
            platform=platform,
            **kwargs,  # type: ignore[arg-type]
        )


def _platform_from_suffix(path: Path) -> Platform:
    s = path.suffix.lower()
    if s == ".ipa":
        return "ios"
    return "android"
