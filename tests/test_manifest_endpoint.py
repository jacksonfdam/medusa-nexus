"""Manifest viewer feature — endpoint, CLI flat command, and cache semantics.

Three surfaces share one decode path:
  * ``GET /v1/projects/{id}/manifest?fmt=xml|json``
  * ``mnexus manifest <id> [--output] [--json]`` (Click flat command)
  * The REPL ``/manifest`` slash command (driven by the same HTTP endpoint)

These tests cover the HTTP endpoint contract + the flat CLI command's
exit-code matrix. The REPL slash is a thin client over the HTTP layer
and inherits the coverage transparently.
"""

from __future__ import annotations

import importlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from mnexus.cli import cli as mnexus_cli


def _build_minimal_apk() -> bytes:
    """Same minimal-zip-as-APK trick test_apk_ingest_e2e uses.

    Zero-byte AndroidManifest forces the engine's apktool-or-fallback
    path; the built-in AXML parser still emits a structured shape we
    can serialise back to XML.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", b"")
        zf.writestr("classes.dex", b"dex\n035\x00")
        zf.writestr("resources.arsc", b"")
    return buf.getvalue()


@pytest.fixture
def manifest_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Fresh workspace + DB + TestClient. One scanned project at PRJ-..."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    client = TestClient(api_main.app)
    with client:
        # Ingest the fixture so we have a project to query.
        apk_bytes = _build_minimal_apk()
        r = client.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield client, pid


# ─── /v1/projects/{id}/manifest ───────────────────────────────────────


def test_manifest_endpoint_returns_xml_by_default(manifest_client) -> None:
    client, pid = manifest_client
    r = client.get(f"/v1/projects/{pid}/manifest")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/xml")
    body = r.text
    # Either real apktool output or the synth fallback — both start with
    # the standard XML prolog.
    assert body.lstrip().startswith("<?xml") or body.lstrip().startswith("<manifest")
    assert "com.target.app" in body


def test_manifest_endpoint_fmt_json_returns_structured(manifest_client) -> None:
    client, pid = manifest_client
    r = client.get(f"/v1/projects/{pid}/manifest?fmt=json")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["project_id"] == pid
    assert "manifest" in payload
    m = payload["manifest"]
    # The structured parser puts package + version on the root keys.
    assert m.get("package") == "com.target.app"


def test_manifest_endpoint_caches_after_first_call(manifest_client, tmp_path) -> None:
    """Second call must read from the on-disk cache, not re-decode.

    We can't easily distinguish a cache hit from a decode at the unit
    level without mocking, so the contract test is: the cache file
    exists on disk after the first call.
    """
    client, pid = manifest_client
    r1 = client.get(f"/v1/projects/{pid}/manifest")
    assert r1.status_code == 200

    workspace = Path(client.app.state.nexus.config.workspace)
    cache = workspace / pid / "apktool-manifest" / "AndroidManifest.xml"
    assert cache.exists(), "first call should have populated the cache"

    # Second call must succeed and produce identical bytes.
    r2 = client.get(f"/v1/projects/{pid}/manifest")
    assert r2.status_code == 200
    assert r1.content == r2.content


def test_manifest_endpoint_unknown_project_returns_404(manifest_client) -> None:
    client, _ = manifest_client
    r = client.get("/v1/projects/PRJ-DOESNOTEXIST/manifest")
    assert r.status_code == 404
    assert "no project" in r.text.lower()


def test_manifest_endpoint_invalid_format_returns_400(manifest_client) -> None:
    client, pid = manifest_client
    r = client.get(f"/v1/projects/{pid}/manifest?fmt=yaml")
    assert r.status_code == 400
    assert "unknown format" in r.text.lower()


def test_manifest_endpoint_missing_apk_returns_422(manifest_client) -> None:
    """If the source artefact got deleted off disk after ingest, we
    surface 422 rather than crashing the request.

    The upload handler writes to ``<workspace>/upload-<random>-<name>``
    (mnexus/api/main.py:1098). We can't touch the SQLite store from the
    test thread, so we discover the file via glob on the upload prefix
    rather than reconstructing the path.
    """
    client, pid = manifest_client
    workspace = Path(client.app.state.nexus.config.workspace)
    # Wipe the cache first so the endpoint actually has to look at the apk.
    cache = workspace / pid / "apktool-manifest" / "AndroidManifest.xml"
    if cache.exists():
        cache.unlink()
    uploads = list(workspace.glob("upload-*-target.apk"))
    assert uploads, f"upload landed somewhere unexpected; workspace: {list(workspace.iterdir())}"
    for f in uploads:
        f.unlink()
    r = client.get(f"/v1/projects/{pid}/manifest")
    assert r.status_code == 422
    assert "missing" in r.text.lower()


# ─── mnexus manifest <project_id> (flat CLI) ──────────────────────────


def test_flat_manifest_command_prints_xml_to_stdout(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    # Build + ingest via the same client harness so the project exists.
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as client:
        r = client.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(_build_minimal_apk()),
                            "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0.0"},
        )
        pid = r.json()["project_id"]

    runner = CliRunner()
    result = runner.invoke(mnexus_cli, ["manifest", pid], standalone_mode=False)
    assert result.exit_code == 0, result.output
    # XML output: either real apktool or the synth fallback.
    assert "com.target.app" in result.output


def test_flat_manifest_command_writes_to_output_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as client:
        r = client.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(_build_minimal_apk()),
                            "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0.0"},
        )
        pid = r.json()["project_id"]

    out = tmp_path / "captured.xml"
    runner = CliRunner()
    result = runner.invoke(mnexus_cli, ["manifest", pid, "--output", str(out)], standalone_mode=False)
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "com.target.app" in out.read_text(encoding="utf-8")


def test_flat_manifest_command_json_flag_emits_structured(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as client:
        r = client.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(_build_minimal_apk()),
                            "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0.0"},
        )
        pid = r.json()["project_id"]

    runner = CliRunner()
    result = runner.invoke(mnexus_cli, ["manifest", pid, "--json"], standalone_mode=False)
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["project_id"] == pid
    assert parsed["manifest"]["package"] == "com.target.app"


def test_flat_manifest_command_unknown_project_exits_2(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    # Importing api_main triggers DB creation; we don't need a project.
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    runner = CliRunner()
    result = runner.invoke(mnexus_cli, ["manifest", "PRJ-DOESNOTEXIST"], standalone_mode=False)
    assert result.exit_code == 2
    assert "no project" in result.output.lower()
