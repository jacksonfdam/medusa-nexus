"""MCP control plane — what the assistant is allowed to touch.

The MCP driver (``mcp_server.py``) is a stdio process the *agent* spawns
(Claude Desktop / Cursor / Zed), so Nexus can't stop the client from
launching it. What Nexus CAN do is decide which tools that process is
allowed to expose and dispatch: this module is the single source of truth
for that allowlist plus the tool catalogue the settings panel renders.

Persistence is a small JSON at ``<workspace>/mcp_config.json``. Absent
file = wide open (every tool enabled), which is the historical default —
turning the panel on never silently locks anything the user relied on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Tool → group. The panel colour-codes by group and the write set is the
# one a cautious analyst most often wants to gate.
TOOL_GROUPS: dict[str, str] = {
    # read — inspect what's already in the workspace
    "list_projects": "read",
    "get_project": "read",
    "list_findings": "read",
    "get_finding": "read",
    "list_recipes": "read",
    "decode_android_flag": "read",
    "manifest_diff": "read",
    "findings_diff": "read",
    "firebase_probe": "read",
    "doctor": "read",
    # nav — read the decompiled source
    "decompile_project": "nav",
    "get_class_source": "nav",
    "search_classes": "nav",
    "search_source": "nav",
    "get_manifest": "nav",
    # write — mutate workspace state / run pipelines
    "scan_apk": "write",
    "run_pipeline": "write",
    "analyze_native_lib": "write",
    # attack — proactive exploitation
    "get_attack_plan": "read",
    "plan_attack": "write",
    "execute_attack": "write",
}

# Short human label of the underlying route, for the panel (not wire-load).
TOOL_ROUTES: dict[str, str] = {
    "list_projects": "GET /v1/projects",
    "get_project": "GET /v1/projects/{id}",
    "list_findings": "GET /v1/projects/{id}/findings",
    "get_finding": "GET /v1/findings/{fid}",
    "list_recipes": "GET /v1/recipes",
    "decode_android_flag": "POST /v1/mango/decode-flags",
    "manifest_diff": "GET /v1/projects/{id}/manifest-diff",
    "findings_diff": "GET /v1/projects/{id}/findings-diff",
    "firebase_probe": "POST /v1/firebase/probe",
    "doctor": "GET /v1/doctor",
    "decompile_project": "POST /v1/projects/{id}/decompile",
    "get_class_source": "GET /v1/projects/{id}/source",
    "search_classes": "GET /v1/projects/{id}/classes",
    "search_source": "GET /v1/projects/{id}/find",
    "get_manifest": "GET /v1/projects/{id}/manifest",
    "scan_apk": "POST /v1/apks/upload",
    "run_pipeline": "POST /v1/pipelines/{name}/run",
    "analyze_native_lib": "GET /v1/projects/{id}/native/analyze",
    "get_attack_plan": "GET /v1/projects/{id}/attack",
    "plan_attack": "POST /v1/projects/{id}/attack/plan",
    "execute_attack": "POST /v1/projects/{id}/attack/execute",
}

_CONFIG_FILENAME = "mcp_config.json"


class McpConfig(BaseModel):
    """The allowlist state. ``allowed_tools=None`` means *every* tool — the
    open default that keeps a fresh install behaving exactly as before."""

    enabled: bool = Field(default=True, description="Master switch. When false the driver exposes nothing.")
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Explicit allowlist. None = all tools. Empty list = none.",
    )

    def is_allowed(self, tool_name: str) -> bool:
        """Is ``tool_name`` dispatchable right now?"""
        if not self.enabled:
            return False
        if self.allowed_tools is None:
            return True
        return tool_name in self.allowed_tools

    def effective_allowed(self, all_names: list[str]) -> list[str]:
        """Resolve the allowlist against the known tool names."""
        if not self.enabled:
            return []
        if self.allowed_tools is None:
            return list(all_names)
        return [n for n in all_names if n in self.allowed_tools]


def config_path(workspace: Path) -> Path:
    return workspace / _CONFIG_FILENAME


def load_config(workspace: Path) -> McpConfig:
    """Read the persisted config, or hand back the open default."""
    path = config_path(workspace)
    if not path.exists():
        return McpConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt config must not brick the driver — fail open, loudly
        # enough that /v1/mcp/config still renders the default state.
        return McpConfig()
    return McpConfig.model_validate(raw)


def save_config(workspace: Path, cfg: McpConfig) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    config_path(workspace).write_text(
        json.dumps(cfg.model_dump(), indent=2), encoding="utf-8"
    )


def catalogue(tools: list[dict[str, Any]], cfg: McpConfig) -> list[dict[str, Any]]:
    """Merge the live TOOLS descriptors with group/route/enabled metadata."""
    out: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")
        out.append({
            "name": name,
            "group": TOOL_GROUPS.get(name, "read"),
            "description": tool.get("description", ""),
            "route": TOOL_ROUTES.get(name, ""),
            "enabled": cfg.is_allowed(name),
        })
    return out


# ─── agent setup snippets ───────────────────────────────────────────────


def setup_snippet(agent: str, api_base: str, *, command: str = "mnexus") -> dict[str, Any]:
    """Return the config the user pastes into their MCP client.

    Every supported client uses the same stdio shape — a command, args, and
    an ``MNEXUS_API_BASE`` env var — so this is one JSON with a per-agent
    file hint on top.
    """
    server_block = {
        "command": command,
        "args": ["mcp-serve"],
        "env": {"MNEXUS_API_BASE": api_base},
    }
    files = {
        "claude": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "cursor": "~/.cursor/mcp.json",
        "zed": "~/.config/zed/settings.json (context_servers)",
    }
    agent_norm = agent.lower()
    config = {"mcpServers": {"medusa-nexus": server_block}}
    return {
        "agent": agent_norm,
        "config_file": files.get(agent_norm, files["claude"]),
        "snippet": json.dumps(config, indent=2),
    }
