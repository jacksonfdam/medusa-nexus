"""MCP driver — dispatch round-trips and tool wiring.

The dispatcher is a pure function over a JSON-RPC dict: every test
here feeds it a hand-built request and checks the response shape.
The local API client (`_api`) is monkeypatched to a recording stub so
nothing actually opens a socket.
"""

from __future__ import annotations

import json

import pytest

from mnexus import mcp_server


# ─── plumbing ──────────────────────────────────────────────────────────


@pytest.fixture
def api_recorder(monkeypatch: pytest.MonkeyPatch):
    """Capture every (method, path, body, form) the handlers issue.

    Returns the calls list + a setter to control the next response.
    Pattern lifted from how the rest of the test suite mocks HTTP I/O.
    """
    calls: list[dict] = []
    response: dict = {"status": 200, "body": {"ok": True}}

    def fake_api(method, path, *, body=None, form=None, timeout=60.0):
        calls.append({"method": method, "path": path, "body": body, "form": form})
        return response["status"], response["body"]

    monkeypatch.setattr(mcp_server, "_api", fake_api)
    return calls, response


# ─── protocol handshake ────────────────────────────────────────────────


def test_initialize_returns_protocol_and_server_info() -> None:
    res = mcp_server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert res is not None
    assert res["id"] == 1
    result = res["result"]
    assert result["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "medusa-nexus"
    assert "tools" in result["capabilities"]


def test_initialized_notification_returns_none() -> None:
    # No `id` → no response. The MCP client fires this once after initialize.
    res = mcp_server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert res is None


def test_unknown_method_returns_jsonrpc_error() -> None:
    res = mcp_server.dispatch({"jsonrpc": "2.0", "id": 7, "method": "tools/garbage"})
    assert res["error"]["code"] == -32601
    assert "method not found" in res["error"]["message"]


# ─── tools/list catalogue ──────────────────────────────────────────────


def test_tools_list_exposes_every_handler() -> None:
    res = mcp_server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in res["result"]["tools"]}
    # Every declared tool needs a handler — the assistant gets confused
    # otherwise. This is the contract test for the catalogue.
    assert names == set(mcp_server._HANDLERS.keys())


def test_every_tool_descriptor_has_schema() -> None:
    """Every tool must declare an inputSchema so the assistant can build
    the call shape without guessing."""
    for tool in mcp_server.TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


# ─── tools/call dispatch ───────────────────────────────────────────────


def _call(name: str, args: dict | None = None, *, msg_id: int = 99) -> dict:
    return mcp_server.dispatch({
        "jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
        "params": {"name": name, "arguments": args or {}},
    })


def test_tools_call_unknown_tool_errors(api_recorder) -> None:
    res = _call("not_a_real_tool")
    assert res["error"]["code"] == -32602
    assert "unknown tool" in res["error"]["message"]


def test_tools_call_returns_text_content_envelope(api_recorder) -> None:
    """Every successful tools/call wraps the handler output in MCP's
    `content: [{type: text, text: <json>}]` shape. Without this the
    assistant can't render anything."""
    calls, _ = api_recorder
    res = _call("list_projects")
    content = res["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    payload = json.loads(content[0]["text"])
    assert payload["status"] == 200


def test_list_projects_hits_v1_projects(api_recorder) -> None:
    calls, _ = api_recorder
    _call("list_projects")
    assert calls[-1]["method"] == "GET"
    assert calls[-1]["path"] == "/v1/projects"


def test_get_project_quotes_id_into_path(api_recorder) -> None:
    calls, _ = api_recorder
    _call("get_project", {"project_id": "PRJ-DEADBEEF"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-DEADBEEF"


def test_list_findings_passes_severity_filter_as_querystring(api_recorder) -> None:
    calls, _ = api_recorder
    _call("list_findings", {"project_id": "PRJ-1", "severity": "critical"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/findings?severity=critical"


def test_list_findings_drops_empty_filters(api_recorder) -> None:
    """Empty severity/category shouldn't sneak `?severity=&category=` into
    the URL — the API takes both as None, but the noise is ugly."""
    calls, _ = api_recorder
    _call("list_findings", {"project_id": "PRJ-1", "severity": "", "category": ""})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/findings"


def test_get_finding_uses_global_lookup_route(api_recorder) -> None:
    """The API resolves a finding by id alone (no project scoping in the
    route). Project_id rides along in the response only."""
    calls, _ = api_recorder
    res = _call("get_finding", {"finding_id": "FND-1234", "project_id": "PRJ-1"})
    assert calls[-1]["path"] == "/v1/findings/FND-1234"
    payload = json.loads(res["result"]["content"][0]["text"])
    assert payload["project_id"] == "PRJ-1"


def test_get_finding_works_without_project_id(api_recorder) -> None:
    calls, _ = api_recorder
    _call("get_finding", {"finding_id": "FND-1234"})
    assert calls[-1]["path"] == "/v1/findings/FND-1234"


def test_decode_android_flag_posts_to_mango(api_recorder) -> None:
    calls, _ = api_recorder
    _call("decode_android_flag", {"value": "0x10000000", "namespaces": ["intent"]})
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["path"] == "/v1/mango/decode-flags"
    assert calls[-1]["body"] == {"value": "0x10000000", "namespaces": ["intent"]}


def test_manifest_diff_optional_against_appears_in_querystring(api_recorder) -> None:
    calls, _ = api_recorder
    _call("manifest_diff", {"project_id": "PRJ-1", "against": "PRJ-0"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/manifest-diff?against=PRJ-0"


def test_findings_diff_without_against_passes_no_querystring(api_recorder) -> None:
    calls, _ = api_recorder
    _call("findings_diff", {"project_id": "PRJ-1"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/findings-diff"


# ─── control-plane enforcement ──────────────────────────────────────────


def test_tools_list_filters_by_allowlist(api_recorder, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_allowed_tool_names", lambda: {"doctor", "list_projects"})
    res = mcp_server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in res["result"]["tools"]}
    assert names == {"doctor", "list_projects"}


def test_tools_list_open_when_policy_unreachable(api_recorder, monkeypatch) -> None:
    # None = fail open → every tool listed.
    monkeypatch.setattr(mcp_server, "_allowed_tool_names", lambda: None)
    res = mcp_server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(res["result"]["tools"]) == len(mcp_server.TOOLS)


def test_disabled_tool_is_refused(api_recorder, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_allowed_tool_names", lambda: {"doctor"})
    res = _call("list_projects")
    assert res["error"]["code"] == -32601
    assert "disabled by MedusaNexus" in res["error"]["message"]


def test_allowed_tool_dispatches(api_recorder, monkeypatch) -> None:
    calls, _ = api_recorder
    monkeypatch.setattr(mcp_server, "_allowed_tool_names", lambda: {"list_projects"})
    res = _call("list_projects")
    assert "error" not in res
    assert any(c["path"] == "/v1/projects" for c in calls)


def test_master_switch_off_refuses_all(api_recorder, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_allowed_tool_names", lambda: set())
    assert _call("doctor")["error"]["code"] == -32601


def test_tools_call_sends_heartbeat(api_recorder, monkeypatch) -> None:
    calls, _ = api_recorder
    monkeypatch.setattr(mcp_server, "_allowed_tool_names", lambda: None)
    _call("list_projects")
    assert any(c["method"] == "POST" and c["path"] == "/v1/mcp/heartbeat" for c in calls)


def test_initialize_records_client_and_heartbeats(api_recorder) -> None:
    calls, _ = api_recorder
    mcp_server.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"clientInfo": {"name": "cursor"}},
    })
    assert mcp_server._CLIENT_NAME == "cursor"
    assert any(c["path"] == "/v1/mcp/heartbeat" for c in calls)


# ─── code navigation tools ─────────────────────────────────────────────


def test_decompile_project_defaults_to_jadx(api_recorder) -> None:
    calls, _ = api_recorder
    _call("decompile_project", {"project_id": "PRJ-1"})
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/decompile?engine=jadx"


def test_decompile_project_passes_engine_and_force(api_recorder) -> None:
    calls, _ = api_recorder
    _call("decompile_project", {"project_id": "PRJ-1", "engine": "apktool", "force": True})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/decompile?engine=apktool&force=true"


def test_get_class_source_builds_source_path(api_recorder) -> None:
    calls, _ = api_recorder
    _call("get_class_source", {"project_id": "PRJ-1", "fqcn": "com.target.auth.LoginManager"})
    assert calls[-1]["method"] == "GET"
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/source?fqcn=com.target.auth.LoginManager&fmt=java"


def test_get_class_source_honours_smali_fmt(api_recorder) -> None:
    calls, _ = api_recorder
    _call("get_class_source", {"project_id": "PRJ-1", "fqcn": "com.target.A", "fmt": "smali"})
    assert calls[-1]["path"].endswith("fmt=smali")


def test_search_classes_defaults_empty_query(api_recorder) -> None:
    calls, _ = api_recorder
    _call("search_classes", {"project_id": "PRJ-1"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/classes?q=&fmt=java"


def test_search_source_maps_to_find_endpoint(api_recorder) -> None:
    calls, _ = api_recorder
    _call("search_source", {"project_id": "PRJ-1", "q": "AIzaSy", "regex": True})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/find?q=AIzaSy&regex=true"


def test_get_manifest_defaults_to_xml(api_recorder) -> None:
    calls, _ = api_recorder
    _call("get_manifest", {"project_id": "PRJ-1"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/manifest?fmt=xml"


# ─── attack engine tools ────────────────────────────────────────────────


def test_plan_attack_posts_plan(api_recorder) -> None:
    calls, _ = api_recorder
    _call("plan_attack", {"project_id": "PRJ-1"})
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/attack/plan"


def test_execute_attack_dry_run_by_default(api_recorder) -> None:
    calls, _ = api_recorder
    _call("execute_attack", {"project_id": "PRJ-1"})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/attack/execute?execute=false"


def test_execute_attack_opt_in_fires(api_recorder) -> None:
    calls, _ = api_recorder
    _call("execute_attack", {"project_id": "PRJ-1", "execute": True})
    assert calls[-1]["path"] == "/v1/projects/PRJ-1/attack/execute?execute=true"


def test_get_attack_plan_reads(api_recorder) -> None:
    calls, _ = api_recorder
    _call("get_attack_plan", {"project_id": "PRJ-1"})
    assert calls[-1] == {"method": "GET", "path": "/v1/projects/PRJ-1/attack", "body": None, "form": None}


def test_firebase_probe_strips_empty_fields_from_body(api_recorder) -> None:
    """The /v1/firebase/probe endpoint 400s when fed an empty config. We
    drop blank fields so the assistant can over-specify without errors."""
    calls, _ = api_recorder
    _call("firebase_probe", {"project_id": "myapp", "api_key": "", "database_url": "https://x.firebaseio.com"})
    body = calls[-1]["body"]
    assert "api_key" not in body
    assert body == {"project_id": "myapp", "database_url": "https://x.firebaseio.com"}


def test_list_recipes_filters_category_client_side(api_recorder) -> None:
    """Category filter happens in the handler, not via querystring — the
    API doesn't take a category param yet."""
    calls, response = api_recorder
    response["body"] = [
        {"name": "a", "category": "Bypass"},
        {"name": "b", "category": "Logging"},
        {"name": "c", "category": "Bypass Pin"},
    ]
    res = _call("list_recipes", {"category": "bypass"})
    payload = json.loads(res["result"]["content"][0]["text"])
    names = {r["name"] for r in payload["recipes"]}
    assert names == {"a", "c"}


def test_doctor_hits_v1_doctor(api_recorder) -> None:
    calls, _ = api_recorder
    _call("doctor")
    assert calls[-1]["path"] == "/v1/doctor"


# ─── write-tools — agent-drivable inspection ───────────────────────────


def test_scan_apk_posts_multipart_to_apks_upload(monkeypatch, tmp_path) -> None:
    """scan_apk uses the multipart helper, not the JSON _api(). Record
    what it sent so we know the wire shape stayed compatible with
    /v1/apks/upload."""
    apk = tmp_path / "fixture.apk"
    apk.write_bytes(b"PK\x03\x04stubapkfixture")

    sent: list[dict] = []
    def fake_upload(path, file_path, *, fields=None, timeout=600.0):
        sent.append({"path": path, "file_path": file_path, "fields": fields or {}})
        return 200, {"project_id": "PRJ-FAKE0001", "dedup": False}

    monkeypatch.setattr(mcp_server, "_api_upload", fake_upload)
    res = _call("scan_apk", {"apk_path": str(apk), "package_name": "com.x.y", "version": "1.2"})

    assert sent[-1]["path"] == "/v1/apks/upload"
    assert sent[-1]["file_path"] == str(apk)
    assert sent[-1]["fields"] == {"package": "com.x.y", "version": "1.2"}
    payload = json.loads(res["result"]["content"][0]["text"])
    assert payload["ingest"]["project_id"] == "PRJ-FAKE0001"


def test_scan_apk_force_flag_forwards(monkeypatch, tmp_path) -> None:
    apk = tmp_path / "f.apk"
    apk.write_bytes(b"x")
    sent: list[dict] = []
    monkeypatch.setattr(mcp_server, "_api_upload",
                        lambda p, fp, *, fields=None, timeout=600.0: (sent.append({"fields": fields}) or (200, {})))
    _call("scan_apk", {"apk_path": str(apk), "force": True})
    assert sent[-1]["fields"].get("force") == "true"


def test_run_pipeline_posts_to_named_route(api_recorder) -> None:
    calls, _ = api_recorder
    _call("run_pipeline", {"name": "full-static-android", "project_id": "PRJ-1"})
    assert calls[-1]["method"] == "POST"
    assert calls[-1]["path"] == "/v1/pipelines/full-static-android/run"
    assert calls[-1]["form"] == {"project_id": "PRJ-1"}


def test_analyze_native_lib_quotes_lib_path(api_recorder) -> None:
    calls, _ = api_recorder
    _call("analyze_native_lib", {"project_id": "PRJ-1", "lib_path": "lib/arm64-v8a/libtarget.so"})
    assert calls[-1]["method"] == "GET"
    assert calls[-1]["path"].startswith("/v1/projects/PRJ-1/native/analyze?")
    assert "lib%2Farm64-v8a%2Flibtarget.so" in calls[-1]["path"]


# ─── error paths ───────────────────────────────────────────────────────


def test_handler_exception_becomes_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blown-up handler must surface as JSON-RPC -32603, not a crash —
    the stdio loop dies otherwise and the assistant loses the session."""
    def boom(_):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(mcp_server._HANDLERS, "list_projects", boom)
    res = _call("list_projects")
    assert res["error"]["code"] == -32603
    assert "RuntimeError" in res["error"]["message"]


def test_missing_required_argument_returns_invalid_params(api_recorder) -> None:
    res = _call("get_project")  # no project_id
    assert res["error"]["code"] == -32602
    assert "missing argument" in res["error"]["message"]


# ─── stdio loop ────────────────────────────────────────────────────────


def test_serve_stdio_roundtrips_initialize(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Feed one initialize line through stdin → expect one JSON response on stdout."""
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    ))
    rc = mcp_server.serve_stdio()
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    response = json.loads(out[0])
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_serve_stdio_emits_parse_error_for_garbage_input(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all\n"))
    rc = mcp_server.serve_stdio()
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    response = json.loads(out[0])
    assert response["error"]["code"] == -32700


def test_serve_stdio_skips_response_for_notifications(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """notifications/initialized has no id → dispatcher returns None →
    nothing should be written to stdout."""
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    ))
    rc = mcp_server.serve_stdio()
    assert rc == 0
    assert capsys.readouterr().out == ""


# ─── env wiring ────────────────────────────────────────────────────────


def test_api_base_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEXUS_API_BASE", "https://nexus.internal:9000/")
    assert mcp_server._api_base() == "https://nexus.internal:9000"


def test_api_base_defaults_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEXUS_API_BASE", raising=False)
    assert mcp_server._api_base() == "http://127.0.0.1:8765"
