"""REPL wiring for the code-navigation commands.

Thin guard: the three new slash commands resolve to their handlers and
the handlers proxy the right API routes. The endpoints themselves are
covered in test_project_lifecycle; here we only pin the REPL plumbing so
a rename or a dispatch-table typo can't silently unwire them.
"""

from __future__ import annotations

import pytest

from mnexus import cli


@pytest.mark.parametrize("name", ["decompile", "source", "classes"])
def test_command_resolves(name: str) -> None:
    resolved = cli._resolve_slash(name)
    assert resolved is not None
    assert resolved[0] == name
    assert resolved[1] is cli.SLASH_COMMANDS[name]


@pytest.mark.parametrize("cmd", ["/decompile", "/source", "/classes"])
def test_command_listed_in_help(cmd: str) -> None:
    # The help table is built inside _help; scan the source rows instead of
    # rendering. Cheap contract: every wired command is discoverable.
    import inspect
    src = inspect.getsource(cli._help)
    assert cmd in src


class _Recorder:
    """Minimal ReplState stand-in + API recorder."""

    def __init__(self) -> None:
        self.active_project_id = "PRJ-1"
        self.calls: list[tuple[str, str]] = []


@pytest.fixture
def repl(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(cli, "_require_server", lambda _state: True)

    def fake_api(_state, method, path, **_kw):
        rec.calls.append((method, path))
        return 200, {"cached": False, "class_count": 3, "fqcn": "com.a.B",
                     "file": "jadx/sources/com/a/B.java", "lang": "java",
                     "source": "class B {}", "truncated": False, "classes": []}

    monkeypatch.setattr(cli, "_api_request", fake_api)
    return rec


def test_decompile_posts_engine(repl: _Recorder) -> None:
    cli._decompile(repl, ["apktool"])  # type: ignore[arg-type]
    method, path = repl.calls[-1]
    assert method == "POST"
    assert path == "/v1/projects/PRJ-1/decompile?engine=apktool"


def test_source_gets_class(repl: _Recorder) -> None:
    cli._source(repl, ["com.a.B", "--smali"])  # type: ignore[arg-type]
    method, path = repl.calls[-1]
    assert method == "GET"
    assert path == "/v1/projects/PRJ-1/source?fqcn=com.a.B&fmt=smali"


def test_classes_lists(repl: _Recorder) -> None:
    cli._classes(repl, ["auth"])  # type: ignore[arg-type]
    method, path = repl.calls[-1]
    assert method == "GET"
    assert "/v1/projects/PRJ-1/classes?q=auth&fmt=java" in path


# ─── /mcp control plane ─────────────────────────────────────────────────


@pytest.fixture
def mcp_repl(monkeypatch: pytest.MonkeyPatch):
    rec = _Recorder()
    rec.puts = []  # type: ignore[attr-defined]
    monkeypatch.setattr(cli, "_require_server", lambda _state: True)

    catalogue = [
        {"name": "doctor", "group": "read", "route": "GET /v1/doctor", "enabled": True},
        {"name": "scan_apk", "group": "write", "route": "POST /v1/apks/upload", "enabled": True},
    ]

    def fake_api(_state, method, path, *, body=None, form=None):
        rec.calls.append((method, path))
        if method == "PUT":
            rec.puts.append(body)  # type: ignore[attr-defined]
            return 200, {"enabled": True, "allowed_tools": None, "tools": catalogue, "status": {}}
        if path.startswith("/v1/mcp/setup/"):
            return 200, {"agent": "cursor", "config_file": "~/.cursor/mcp.json", "snippet": "{}"}
        return 200, {"enabled": True, "allowed_tools": None, "tools": catalogue,
                     "status": {"connected": True, "client": "cursor", "last_seen_ts": 1, "last_seen_ago_s": 2.0}}

    monkeypatch.setattr(cli, "_api_request", fake_api)
    return rec


def test_mcp_status_gets_config(mcp_repl) -> None:
    cli._mcp(mcp_repl, [])  # type: ignore[arg-type]
    assert mcp_repl.calls[-1] == ("GET", "/v1/mcp/config")


def test_mcp_enable_puts_true(mcp_repl) -> None:
    cli._mcp(mcp_repl, ["enable"])  # type: ignore[arg-type]
    assert mcp_repl.puts[-1] == {"enabled": True}  # type: ignore[attr-defined]


def test_mcp_disable_puts_false(mcp_repl) -> None:
    cli._mcp(mcp_repl, ["disable"])  # type: ignore[arg-type]
    assert mcp_repl.puts[-1] == {"enabled": False}  # type: ignore[attr-defined]


def test_mcp_allow_all_sends_null(mcp_repl) -> None:
    cli._mcp(mcp_repl, ["allow", "all"])  # type: ignore[arg-type]
    assert mcp_repl.puts[-1] == {"allowed_tools": None}  # type: ignore[attr-defined]


def test_mcp_block_all_sends_empty(mcp_repl) -> None:
    cli._mcp(mcp_repl, ["block", "all"])  # type: ignore[arg-type]
    assert mcp_repl.puts[-1] == {"allowed_tools": []}  # type: ignore[attr-defined]


def test_mcp_block_one_computes_list(mcp_repl) -> None:
    # Current allowlist is None (=all); blocking scan_apk leaves doctor.
    cli._mcp(mcp_repl, ["block", "scan_apk"])  # type: ignore[arg-type]
    assert mcp_repl.puts[-1] == {"allowed_tools": ["doctor"]}  # type: ignore[attr-defined]


def test_mcp_setup_hits_agent_route(mcp_repl) -> None:
    cli._mcp(mcp_repl, ["setup", "cursor"])  # type: ignore[arg-type]
    assert mcp_repl.calls[-1] == ("GET", "/v1/mcp/setup/cursor")
