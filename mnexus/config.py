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
    vphone_path: Path | None = Field(default=None, description="wh1te4ever/super-tart-vphone checkout (research only).")
    tart_bin: Path | None = Field(default=None, description="Built `tart` binary from super-tart-vphone (set by scripts/setup-vphone.sh).")
    playintel_credentials: Path | None = Field(
        default=None,
        description="Override path to playintel credentials INI (default: ~/.config/mnexus/playintel.ini, falls back to ~/.config/apkeep/apkeep.ini).",
    )

    # ─── external services ───
    mobsf_url: str = Field(default="http://localhost:8000", description="MobSF REST base URL.")
    mobsf_api_key: str | None = Field(default=None, description="MobSF API key. Yes, it's required.")
    burp_url: str = Field(default="http://localhost:1337", description="Burp REST API base URL.")
    burp_api_key: str | None = Field(default=None)
    caido_url: str = Field(default="http://localhost:8080", description="Caido (https://caido.io) REST API base URL — alternative to Burp.")
    caido_api_key: str | None = Field(default=None, description="Caido API token. Generate at Workbench → Settings → Tokens.")
    moxy_url: str = Field(default="http://localhost:5000", description="Moxy (https://github.com/matank001/Moxy) web UI base URL.")
    moxy_proxy_host: str = Field(default="localhost", description="Hostname the device should point at for Moxy's MITM proxy.")
    moxy_proxy_port: int = Field(default=8081, description="Port the device should point at for Moxy's MITM proxy.")
    moxy_ca_path: Path | None = Field(default=None, description="Path to mitmproxy CA cert extracted from the Moxy container (.cer).")
    proxy_flavor: str = Field(default="burp", description="Which intercepting proxy to drive: 'burp' (default) | 'caido' | 'moxy'.")

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
