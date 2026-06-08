"""PipelineExecutor — YAML → real engine calls + per-stage outcomes.

We don't bring real engines into the test (apktool / jadx / mobsf
need binaries + servers). Instead we monkeypatch the handler table
with stubs that return canned outputs / raise on demand. This pins:

  * Sequential stages run in order
  * Parallel stages all complete (output present from each)
  * A failing stage doesn't abort subsequent ones
  * Unknown engine/action → skipped, not failed
  * Frida run_session is a soft-skip on purpose
  * YAML parse errors land on run.error with a clear message
  * /v1/pipelines/{name}/run is no longer a stub — returns a real run
"""

from __future__ import annotations

import asyncio
import importlib
import io

import pytest
from fastapi.testclient import TestClient

from mnexus.runtime import pipeline_executor as pe


_TINY_PIPELINE = """\
name: tiny
stages:
  - { name: a, engine: apktool, action: decode }
  - name: parallel_block
    parallel: true
    steps:
      - { engine: jadx, action: decompile }
      - { engine: mobsf, action: full_scan }
  - { name: c, engine: ghidra, action: analyze_native_libs }
"""


@pytest.fixture
def stub_handlers(monkeypatch: pytest.MonkeyPatch):
    """Replace every handler with a deterministic stub that records its
    invocation order. Returns the call-log list for assertions."""
    calls: list[str] = []

    async def make_ok(label):
        async def _h(nexus, project, stage):  # noqa: ARG001
            calls.append(label)
            return {"label": label, "package": project.package_name}
        return _h

    async def raise_on_jadx(nexus, project, stage):  # noqa: ARG001
        calls.append("jadx (about to raise)")
        raise RuntimeError("simulated jadx failure")

    async def returns_none_skip(nexus, project, stage):  # noqa: ARG001
        calls.append("playintel (skipped)")
        return None

    # Build the table at runtime so each test pins the behaviour it cares about.
    stubs = {}
    stubs[("apktool",   "decode")] = asyncio.get_event_loop().run_until_complete(make_ok("apktool-decode")) if False else None
    # Actually it's simpler to define handlers directly:

    async def h_apktool(nexus, project, stage):  # noqa: ARG001
        calls.append("apktool-decode")
        return {"label": "apktool-decode"}

    async def h_jadx(nexus, project, stage):  # noqa: ARG001
        calls.append("jadx-decompile")
        return {"label": "jadx-decompile"}

    async def h_mobsf(nexus, project, stage):  # noqa: ARG001
        calls.append("mobsf-full_scan")
        return {"label": "mobsf-full_scan"}

    async def h_ghidra(nexus, project, stage):  # noqa: ARG001
        calls.append("ghidra-analyze")
        return {"label": "ghidra-analyze"}

    monkeypatch.setitem(pe._STAGE_HANDLERS, ("apktool", "decode"), h_apktool)
    monkeypatch.setitem(pe._STAGE_HANDLERS, ("jadx", "decompile"), h_jadx)
    monkeypatch.setitem(pe._STAGE_HANDLERS, ("mobsf", "full_scan"), h_mobsf)
    monkeypatch.setitem(pe._STAGE_HANDLERS, ("ghidra", "analyze_native_libs"), h_ghidra)

    return calls


@pytest.fixture
def project(tmp_path):
    from mnexus.models.attack_surface import AttackSurface
    from mnexus.models.project import Project

    apk = tmp_path / "target.apk"
    apk.write_bytes(b"PK\x03\x04stub")
    return Project(
        id="PRJ-PIPE00001",
        name="target",
        apk_path=apk,
        apk_sha256="ee" * 32,
        package_name="com.target.app",
        version_name="1.0",
        attack_surface=AttackSurface(),
    )


@pytest.fixture
def nexus_stub(tmp_path):
    """The handlers only touch project.* and nexus.config — minimal stub."""
    from types import SimpleNamespace
    from mnexus.config import NexusConfig
    cfg = NexusConfig(workspace=tmp_path / "workspace")
    return SimpleNamespace(config=cfg, engines={})


# ─── pure-function tests ──────────────────────────────────────────────


def test_pipeline_runs_stages_in_declared_order(stub_handlers, nexus_stub, project) -> None:
    """Sequential stages run in YAML order, parallel ones may interleave
    among themselves but stay between their siblings."""
    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, _TINY_PIPELINE, pipeline_name="tiny")
    )
    assert run.state == "ok"
    # First call is apktool, last is ghidra; the two parallel calls
    # (jadx + mobsf) land between them.
    assert stub_handlers[0] == "apktool-decode"
    assert stub_handlers[-1] == "ghidra-analyze"
    assert set(stub_handlers[1:3]) == {"jadx-decompile", "mobsf-full_scan"}


def test_pipeline_records_stage_outcomes(stub_handlers, nexus_stub, project) -> None:
    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, _TINY_PIPELINE)
    )
    assert all(s.status == "ok" for s in run.stages)
    # Outputs round-trip from the handler.
    by_name = {s.name: s for s in run.stages}
    assert by_name["a"].output["label"] == "apktool-decode"


def test_pipeline_marks_failed_stage_without_aborting_rest(monkeypatch, nexus_stub, project) -> None:
    """A handler that raises lands the stage on 'failed' but later
    stages still execute."""

    async def h_apktool_ok(nexus, project, stage):  # noqa: ARG001
        return {"ok": True}

    async def h_jadx_raises(nexus, project, stage):  # noqa: ARG001
        raise RuntimeError("boom")

    async def h_ghidra_ok(nexus, project, stage):  # noqa: ARG001
        return {"ok": True}

    monkeypatch.setitem(pe._STAGE_HANDLERS, ("apktool", "decode"), h_apktool_ok)
    monkeypatch.setitem(pe._STAGE_HANDLERS, ("jadx", "decompile"), h_jadx_raises)
    monkeypatch.setitem(pe._STAGE_HANDLERS, ("ghidra", "analyze_native_libs"), h_ghidra_ok)
    # mobsf still uses the real handler — we still want a parallel-group test;
    # replace it with a noop so the test doesn't depend on whether mobsf is up.

    async def h_mobsf_noop(nexus, project, stage):  # noqa: ARG001
        return {"ok": True}

    monkeypatch.setitem(pe._STAGE_HANDLERS, ("mobsf", "full_scan"), h_mobsf_noop)

    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, _TINY_PIPELINE)
    )
    # Overall run is failed because one stage failed.
    assert run.state == "failed"
    # But ghidra still ran — failed stage didn't abort the pipeline.
    by_name = {s.name: s for s in run.stages}
    assert by_name["c"].status == "ok"
    # The jadx stage carries the error message.
    failing = next(s for s in run.stages if s.status == "failed")
    assert "boom" in failing.error


def test_unknown_engine_action_pair_is_skipped(monkeypatch, nexus_stub, project) -> None:
    """Typo'd engine name → skipped with a clear reason, not failed."""
    pipeline = """\
name: unknown
stages:
  - { name: x, engine: zorblax, action: hyperfizzle }
"""
    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, pipeline)
    )
    assert run.state == "ok"  # no failures, just a skip
    stage = run.stages[0]
    assert stage.status == "skipped"
    assert "no handler" in stage.error


def test_handler_returning_none_marks_skipped(monkeypatch, nexus_stub, project) -> None:
    """Frida run_session and Playintel-without-APK both return None →
    skipped, not failed."""

    async def returns_none(nexus, project, stage):  # noqa: ARG001
        return None

    monkeypatch.setitem(pe._STAGE_HANDLERS, ("frida", "run_session"), returns_none)
    pipeline = """\
name: dyn
stages:
  - { name: live, engine: frida, action: run_session }
"""
    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, pipeline)
    )
    assert run.state == "ok"
    assert run.stages[0].status == "skipped"


def test_yaml_parse_error_marks_run_failed_with_clear_error(nexus_stub, project) -> None:
    bad = "stages: : not valid yaml: ["
    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, bad)
    )
    assert run.state == "failed"
    assert "YAML parse error" in run.error


def test_pipeline_with_no_stages_marks_failed(nexus_stub, project) -> None:
    bad = "name: empty\nstages: []\n"
    run = asyncio.new_event_loop().run_until_complete(
        pe.execute_pipeline(nexus_stub, project, bad)
    )
    assert run.state == "failed"
    assert "no stages" in run.error


# ─── endpoint round-trip ──────────────────────────────────────────────


@pytest.fixture
def pipe_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Real TestClient + a real project; stub the heavy engine
    handlers so the suite doesn't depend on apktool/jadx/mobsf binaries."""

    async def h_noop_ok(nexus, project, stage):  # noqa: ARG001
        return {"label": stage.get("engine") + "/" + stage.get("action"), "stub": True}

    # Replace every handler with a noop OK.
    for key in list(pe._STAGE_HANDLERS.keys()):
        monkeypatch.setitem(pe._STAGE_HANDLERS, key, h_noop_ok)

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


def test_post_named_pipeline_run_actually_runs(pipe_client) -> None:
    client, pid = pipe_client
    r = client.post("/v1/pipelines/full_assessment/run", data={"project_id": pid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"]
    assert body["state"] in ("ok", "failed")
    # Every stage in the built-in YAML produced an outcome.
    assert len(body["stages"]) >= 1


def test_run_yaml_endpoint_accepts_ad_hoc_pipeline(pipe_client) -> None:
    client, pid = pipe_client
    yaml_body = """\
name: probe
stages:
  - { name: just_a_decode, engine: apktool, action: decode }
"""
    r = client.post("/v1/pipelines/run-yaml", data={"yaml_body": yaml_body, "project_id": pid})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ok"
    assert body["stages"][0]["name"] == "just_a_decode"


def test_get_pipeline_run_returns_stored_record(pipe_client) -> None:
    client, pid = pipe_client
    run = client.post("/v1/pipelines/static_only/run", data={"project_id": pid}).json()
    fetched = client.get(f"/v1/pipelines/runs/{run['run_id']}").json()
    assert fetched["run_id"] == run["run_id"]
    assert fetched["state"] == run["state"]


def test_get_unknown_pipeline_run_returns_404(pipe_client) -> None:
    client, _ = pipe_client
    r = client.get("/v1/pipelines/runs/ghost")
    assert r.status_code == 404


def test_run_unknown_pipeline_name_returns_404(pipe_client) -> None:
    client, pid = pipe_client
    r = client.post("/v1/pipelines/nope/run", data={"project_id": pid})
    assert r.status_code == 404
