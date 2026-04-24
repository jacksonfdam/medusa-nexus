"""Configuration — the place where paths live so the engines don't have to guess."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class NexusConfig(BaseModel):
    """Runtime configuration for the whole platform.

    Populated from environment, CLI flags, or `~/.config/mnexus/config.yaml`.
    If something here is wrong, every engine downstream will lie to you politely.
    """

    # ─── paths to external tools (absolute) ───
    adb_path: str = Field(default="adb", description="`adb` binary. The glue.")
    jadx_path: str = Field(default="jadx", description="`jadx` CLI. Decompiles things that shouldn't decompile.")
    apktool_path: str = Field(default="apktool", description="`apktool` CLI. Resource whisperer.")
    ghidra_path: Path | None = Field(default=None, description="Ghidra install dir. Headless does the dirty work.")
    medusa_path: Path | None = Field(default=None, description="ch0pin/medusa checkout. Recipes live here.")
    stheno_path: Path | None = Field(default=None, description="ch0pin/Stheno checkout. Patches APKs so you don't have to.")

    # ─── external services ───
    mobsf_url: str = Field(default="http://localhost:8000", description="MobSF REST base URL.")
    mobsf_api_key: str | None = Field(default=None, description="MobSF API key. Yes, it's required.")
    burp_url: str = Field(default="http://localhost:1337", description="Burp REST API base URL.")
    burp_api_key: str | None = Field(default=None)

    # ─── workspace ───
    workspace: Path = Field(default=Path.home() / ".mnexus" / "workspace")
    db_path: Path = Field(default=Path.home() / ".mnexus" / "nexus.sqlite3")
    scripts_path: Path = Field(default=Path(__file__).parent.parent / "scripts")
    rules_path: Path = Field(default=Path(__file__).parent.parent / "rules")

    # ─── runtime knobs ───
    parallel_engines: bool = True
    default_dynamic_duration_s: int = 300

    @classmethod
    def from_env(cls) -> NexusConfig:
        """Hydrate from `MNEXUS_*` env vars. Missing values fall back to defaults."""
        kwargs: dict[str, object] = {}
        for field_name in cls.model_fields:
            env_key = f"MNEXUS_{field_name.upper()}"
            if env_key in os.environ:
                kwargs[field_name] = os.environ[env_key]
        return cls(**kwargs)

    def ensure_workspace(self) -> None:
        """Create the workspace directory tree. Idempotent. Opinionated."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
