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
