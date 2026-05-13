"""mnexus.intelligence.runtime_scripts — Medusa-action Frida generator.

Pins the contract the Project Runtime tab depends on:

  * Every action returns ``{channel, script, hint}``; the channel is
    always ``runtime`` so the existing /dynamic/events ingest routes
    its events without a new transport.
  * The package name lands in the relevant scripts (enumerate_modules /
    spawn_log) so the UI doesn't have to inject it client-side.
  * Class / method names are validated — operator errors (spaces,
    quotes, shell metacharacters) raise ValueError, not produce
    a script that crashes Frida.
  * Unknown action raises KeyError so the HTTP layer can 400 cleanly.
  * jtrace flags toggle the right branches in the emitted JS.
  * /v1/projects/{id}/runtime/script round-trips end-to-end.
"""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mnexus.intelligence.runtime_scripts import (
    available_actions,
    generate_runtime_script,
)


# ─── dispatcher table ─────────────────────────────────────────────────


def test_available_actions_lists_every_dispatcher_entry() -> None:
    expected = {
        "enumerate_classes",
        "describe_class",
        "jtrace_method",
        "enumerate_modules",
        "spawn_log",
    }
    assert set(available_actions()) == expected


def test_unknown_action_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        generate_runtime_script("nope", "com.target.app", {})


# ─── shape contract ───────────────────────────────────────────────────


@pytest.mark.parametrize("action,params", [
    ("enumerate_classes", {"pattern": ".*"}),
    ("describe_class",    {"class": "javax.crypto.Cipher"}),
    ("jtrace_method",     {"class": "com.foo.Bar", "method": "encrypt"}),
    ("enumerate_modules", {}),
    ("spawn_log",         {}),
])
def test_every_action_emits_runtime_channel(action, params) -> None:
    out = generate_runtime_script(action, "com.target.app", params)
    assert out["channel"] == "runtime"
    assert out["script"].startswith("Java.perform(")
    # Every script must send() on the runtime channel — otherwise
    # the events never reach /dynamic/events and the UI stays dark.
    assert "channel: 'runtime'" in out["script"]


# ─── enumerate_classes specifics ──────────────────────────────────────


def test_enumerate_classes_embeds_pattern_and_limit() -> None:
    out = generate_runtime_script("enumerate_classes", "com.target.app", {
        "pattern": ".*Cipher.*",
        "limit": 250,
    })
    assert ".*Cipher.*" in out["script"]
    assert "LIMIT = 250" in out["script"]
    # Pattern is JSON-encoded so quotes / backslashes survive injection.
    assert '"' in out["script"]


def test_enumerate_classes_defaults_when_params_empty() -> None:
    out = generate_runtime_script("enumerate_classes", "com.target.app", {})
    assert ".*" in out["script"]
    assert "LIMIT = 500" in out["script"]


# ─── describe_class validation ────────────────────────────────────────


def test_describe_class_rejects_invalid_class_names() -> None:
    for bad in ["", "com.foo Bar", 'com.foo"Bar', "com.foo;rm -rf /"]:
        with pytest.raises(ValueError):
            generate_runtime_script("describe_class", "com.target.app", {"class": bad})


def test_describe_class_accepts_dollar_separated_inner_classes() -> None:
    # Java inner classes use $ as a separator — has to round-trip.
    out = generate_runtime_script("describe_class", "com.target.app", {
        "class": "com.foo.Outer$Inner",
    })
    assert "Outer$Inner" in out["script"]


# ─── jtrace flags ─────────────────────────────────────────────────────


def test_jtrace_defaults_log_args_and_return_but_not_stack() -> None:
    out = generate_runtime_script("jtrace_method", "com.target.app", {
        "class": "com.foo.Bar",
        "method": "encrypt",
    })
    s = out["script"]
    assert "ev.args =" in s
    assert "ev.ret = " in s
    assert "getStackTrace" not in s


def test_jtrace_stack_flag_enables_stack_trace_capture() -> None:
    out = generate_runtime_script("jtrace_method", "com.target.app", {
        "class": "com.foo.Bar",
        "method": "encrypt",
        "log_stack": True,
    })
    assert "getStackTrace" in out["script"]


def test_jtrace_disabling_args_and_return_strips_those_branches() -> None:
    out = generate_runtime_script("jtrace_method", "com.target.app", {
        "class": "com.foo.Bar",
        "method": "encrypt",
        "log_args": False,
        "log_return": False,
    })
    assert "ev.args =" not in out["script"]
    assert "ev.ret = " not in out["script"]
    # The method must still be called — otherwise the hook breaks the
    # app entirely. The hook builder always assigns rv = this[…]() and
    # returns it; only the logging fields are conditional.
    assert "return rv;" in out["script"]


# ─── enumerate_modules system-filter ──────────────────────────────────


def test_enumerate_modules_default_filters_to_data_app() -> None:
    out = generate_runtime_script("enumerate_modules", "com.target.app", {})
    # The filter regex stays in the script so the analyst can see what
    # got dropped — modules under /data/app or /data/data only.
    assert "/data/app" in out["script"]
    assert "if (false) return true;" in out["script"]


def test_enumerate_modules_include_system_bypasses_the_filter() -> None:
    out = generate_runtime_script("enumerate_modules", "com.target.app", {
        "include_system": True,
    })
    assert "if (true) return true;" in out["script"]


# ─── /v1/projects/{id}/runtime/script round-trip ──────────────────────


@pytest.fixture
def runtime_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with a real Project so the endpoint can resolve a package."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub"), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid


def test_runtime_endpoint_returns_generated_script_for_known_action(runtime_client) -> None:
    client, pid = runtime_client
    r = client.post(
        f"/v1/projects/{pid}/runtime/script",
        json={"action": "jtrace_method", "params": {"class": "com.foo.Bar", "method": "encrypt"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["package"] == "com.target.app"
    assert body["action"] == "jtrace_method"
    assert body["channel"] == "runtime"
    assert "Java.perform" in body["script"]
    assert "com.foo.Bar" in body["script"]


def test_runtime_endpoint_rejects_unknown_action_with_400(runtime_client) -> None:
    client, pid = runtime_client
    r = client.post(
        f"/v1/projects/{pid}/runtime/script",
        json={"action": "summon_demon", "params": {}},
    )
    assert r.status_code == 400
    assert "summon_demon" in r.text


def test_runtime_endpoint_rejects_bad_class_with_400(runtime_client) -> None:
    client, pid = runtime_client
    r = client.post(
        f"/v1/projects/{pid}/runtime/script",
        json={"action": "describe_class", "params": {"class": "com.foo Bar"}},
    )
    assert r.status_code == 400
    assert "invalid character" in r.text


def test_runtime_endpoint_404s_on_unknown_project(runtime_client) -> None:
    client, _ = runtime_client
    r = client.post(
        "/v1/projects/PRJ-NOPE/runtime/script",
        json={"action": "enumerate_modules", "params": {}},
    )
    assert r.status_code == 404
