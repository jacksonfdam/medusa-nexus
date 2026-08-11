"""MCP control-plane config — allowlist resolution + persistence + catalogue."""

from __future__ import annotations

from pathlib import Path

from mnexus import mcp_config as mc
from mnexus.mcp_config import McpConfig


def test_default_is_open() -> None:
    cfg = McpConfig()
    assert cfg.enabled is True
    assert cfg.allowed_tools is None
    assert cfg.is_allowed("scan_apk") is True


def test_master_switch_off_blocks_everything() -> None:
    cfg = McpConfig(enabled=False, allowed_tools=["list_projects"])
    assert cfg.is_allowed("list_projects") is False
    assert cfg.effective_allowed(["list_projects", "doctor"]) == []


def test_explicit_allowlist_gates() -> None:
    cfg = McpConfig(allowed_tools=["list_findings", "get_finding"])
    assert cfg.is_allowed("list_findings") is True
    assert cfg.is_allowed("scan_apk") is False
    assert cfg.effective_allowed(["list_findings", "scan_apk", "get_finding"]) == \
        ["list_findings", "get_finding"]


def test_empty_allowlist_means_none() -> None:
    cfg = McpConfig(allowed_tools=[])
    assert cfg.is_allowed("list_projects") is False


def test_load_absent_file_is_open_default(tmp_path: Path) -> None:
    cfg = mc.load_config(tmp_path)
    assert cfg.enabled is True
    assert cfg.allowed_tools is None


def test_save_then_load_roundtrips(tmp_path: Path) -> None:
    mc.save_config(tmp_path, McpConfig(enabled=False, allowed_tools=["doctor"]))
    cfg = mc.load_config(tmp_path)
    assert cfg.enabled is False
    assert cfg.allowed_tools == ["doctor"]


def test_corrupt_config_fails_open(tmp_path: Path) -> None:
    mc.config_path(tmp_path).write_text("{not json", encoding="utf-8")
    cfg = mc.load_config(tmp_path)
    assert cfg.enabled is True  # never brick the driver on a bad file


def test_catalogue_merges_group_route_enabled() -> None:
    tools = [
        {"name": "list_findings", "description": "list them"},
        {"name": "scan_apk", "description": "scan it"},
    ]
    cfg = McpConfig(allowed_tools=["list_findings"])
    cat = {c["name"]: c for c in mc.catalogue(tools, cfg)}
    assert cat["list_findings"]["group"] == "read"
    assert cat["list_findings"]["enabled"] is True
    assert cat["scan_apk"]["group"] == "write"
    assert cat["scan_apk"]["enabled"] is False
    assert cat["list_findings"]["route"].startswith("GET /v1/projects")


def test_every_tool_has_a_group_and_route() -> None:
    # Contract: every tool the driver ships must be classified, or the panel
    # renders a blank group / route for it.
    from mnexus import mcp_server
    names = {t["name"] for t in mcp_server.TOOLS}
    assert names <= set(mc.TOOL_GROUPS), f"ungrouped: {names - set(mc.TOOL_GROUPS)}"
    assert names <= set(mc.TOOL_ROUTES), f"routeless: {names - set(mc.TOOL_ROUTES)}"


def test_setup_snippet_carries_api_base() -> None:
    snip = mc.setup_snippet("cursor", "http://127.0.0.1:8765")
    assert snip["agent"] == "cursor"
    assert ".cursor/mcp.json" in snip["config_file"]
    assert "http://127.0.0.1:8765" in snip["snippet"]
    assert "mcp-serve" in snip["snippet"]
