"""Project lifecycle — workspace locator + backup + delete (GDPR-grade).

The delete path is *destructive*; this suite is the safety net that
proves it removes exactly what it should and nothing it shouldn't.
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


def _build_minimal_apk(secret: str = "AIzaSyTESTKEY1234567890") -> bytes:
    """APK that carries a known secret in a DEX-ish blob so the locator
    has something to find. Also keeps the standard AndroidManifest +
    classes.dex + resources.arsc entries so ingest succeeds."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", b"")
        # Embed the secret in a place the workspace walker would surface
        # post-decompile. We can't easily produce real DEX bytecode, so
        # we shove it into a raw asset where apktool's extractor reaches it.
        zf.writestr("assets/config.json", json.dumps({"api_key": secret}))
        zf.writestr("classes.dex", b"dex\n035\x00" + secret.encode())
        zf.writestr("resources.arsc", b"")
    return buf.getvalue()


@pytest.fixture
def lifecycle_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Workspace + DB scoped to tmp_path. One scanned project."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    client = TestClient(api_main.app)
    with client:
        r = client.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(_build_minimal_apk()),
                            "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield client, pid, tmp_path


# ─── /find ─────────────────────────────────────────────────────────────


def test_locator_endpoint_finds_known_secret(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    # Touch the manifest to populate the apktool-manifest cache so the
    # locator has at least one tree to walk on a minimal fixture.
    client.get(f"/v1/projects/{pid}/manifest")
    # Drop a known string into the project's workspace ourselves so the
    # walker has a deterministic match (the minimal APK fixture doesn't
    # produce decompiled trees in test runs).
    workspace = Path(client.app.state.nexus.config.workspace)
    fake_jadx = workspace / pid / "jadx" / "com" / "target" / "Config.java"
    fake_jadx.parent.mkdir(parents=True, exist_ok=True)
    fake_jadx.write_text(
        "package com.target;\npublic class Config {\n    public static final String KEY = \"AIzaSyKNOWN_TEST_KEY\";\n}\n",
        encoding="utf-8",
    )

    r = client.get(f"/v1/projects/{pid}/find", params={"q": "AIzaSyKNOWN_TEST_KEY"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == pid
    assert body["query"] == "AIzaSyKNOWN_TEST_KEY"
    assert len(body["hits"]) >= 1
    hit = body["hits"][0]
    assert hit["file"].endswith("Config.java")
    assert hit["tree"] == "jadx"
    assert "AIzaSyKNOWN_TEST_KEY" in hit["snippet"]


def test_locator_endpoint_regex_mode(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    workspace = Path(client.app.state.nexus.config.workspace)
    fake_jadx = workspace / pid / "jadx" / "Config.java"
    fake_jadx.parent.mkdir(parents=True, exist_ok=True)
    fake_jadx.write_text("AIzaSyABCDEF1234 and AIzaSy_other_KEY", encoding="utf-8")
    r = client.get(f"/v1/projects/{pid}/find",
                   params={"q": r"AIzaSy[A-Za-z0-9_]+", "regex": "true"})
    assert r.status_code == 200, r.text
    assert len(r.json()["hits"]) >= 2


def test_locator_endpoint_invalid_regex_400(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    r = client.get(f"/v1/projects/{pid}/find",
                   params={"q": "([unclosed", "regex": "true"})
    assert r.status_code == 400


def test_locator_endpoint_404_for_unknown_project(lifecycle_client) -> None:
    client, _, _ = lifecycle_client
    r = client.get("/v1/projects/PRJ-DOESNOTEXIST/find", params={"q": "anything"})
    assert r.status_code == 404


# ─── source / classes / decompile ────────────────────────────────────────


def _fake_jadx(workspace: Path, pid: str) -> None:
    base = workspace / pid / "jadx" / "sources"
    for rel, body in (
        ("com/target/auth/LoginManager.java", "package com.target.auth;\nclass LoginManager {}\n"),
        ("com/target/ui/Home.java", "package com.target.ui;\nclass Home {}\n"),
    ):
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def test_source_409_before_decompile(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    r = client.get(f"/v1/projects/{pid}/source", params={"fqcn": "com.target.auth.LoginManager"})
    assert r.status_code == 409
    assert "decompile" in r.json()["detail"]


def test_source_reads_class(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    _fake_jadx(Path(client.app.state.nexus.config.workspace), pid)
    r = client.get(f"/v1/projects/{pid}/source", params={"fqcn": "com.target.auth.LoginManager"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fqcn"] == "com.target.auth.LoginManager"
    assert "class LoginManager" in body["source"]
    assert body["lang"] == "java"


def test_source_404_for_unknown_class(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    _fake_jadx(Path(client.app.state.nexus.config.workspace), pid)
    r = client.get(f"/v1/projects/{pid}/source", params={"fqcn": "com.target.Ghost"})
    assert r.status_code == 404


def test_source_rejects_hostile_fqcn(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    _fake_jadx(Path(client.app.state.nexus.config.workspace), pid)
    r = client.get(f"/v1/projects/{pid}/source", params={"fqcn": "../../../../etc/passwd"})
    assert r.status_code == 404  # resolver refuses to leave the subtree


def test_classes_lists_and_filters(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    _fake_jadx(Path(client.app.state.nexus.config.workspace), pid)
    allc = client.get(f"/v1/projects/{pid}/classes")
    assert allc.status_code == 200
    assert allc.json()["count"] == 2
    one = client.get(f"/v1/projects/{pid}/classes", params={"q": "auth"})
    assert [c["fqcn"] for c in one.json()["classes"]] == ["com.target.auth.LoginManager"]


def test_classes_409_before_decompile(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    r = client.get(f"/v1/projects/{pid}/classes", params={"fmt": "smali"})
    assert r.status_code == 409


def test_decompile_missing_tool_is_503(lifecycle_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, pid, _ = lifecycle_client
    # Force the honest "tool not on PATH" path deterministically.
    from mnexus.engines import jadx_engine
    monkeypatch.setattr(jadx_engine.shutil, "which", lambda _: None)
    r = client.post(f"/v1/projects/{pid}/decompile", params={"engine": "jadx"})
    assert r.status_code == 503
    assert "jadx" in r.json()["detail"].lower()


def test_decompile_cached_noop(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    # Pre-seed a smali tree so the endpoint takes the cached path and never
    # needs apktool on PATH.
    smali = Path(client.app.state.nexus.config.workspace) / pid / "apktool" / "smali" / "com" / "target" / "A.smali"
    smali.parent.mkdir(parents=True, exist_ok=True)
    smali.write_text(".class public Lcom/target/A;\n", encoding="utf-8")
    r = client.post(f"/v1/projects/{pid}/decompile", params={"engine": "apktool"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is True
    assert body["class_count"] == 1


# ─── backup ────────────────────────────────────────────────────────────


def test_backup_produces_valid_zip_with_manifest(lifecycle_client) -> None:
    client, pid, tmp_path = lifecycle_client
    r = client.post(f"/v1/projects/{pid}/backup")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    # Inspect the archive — must contain MANIFEST.json + project.json.
    archive_bytes = io.BytesIO(r.content)
    with zipfile.ZipFile(archive_bytes) as zf:
        names = set(zf.namelist())
        assert "MANIFEST.json" in names
        assert "project.json" in names
        manifest = json.loads(zf.read("MANIFEST.json").decode())
        assert manifest["project_id"] == pid
        assert manifest["package"] == "com.target.app"
        assert manifest["format_version"] == "1.0"


def test_backup_includes_source_artefact_and_workspace(lifecycle_client) -> None:
    client, pid, tmp_path = lifecycle_client
    # Force a workspace file to exist before the backup runs.
    workspace = Path(client.app.state.nexus.config.workspace)
    (workspace / pid / "scratch.txt").parent.mkdir(parents=True, exist_ok=True)
    (workspace / pid / "scratch.txt").write_text("test artefact")

    r = client.post(f"/v1/projects/{pid}/backup")
    archive = io.BytesIO(r.content)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        assert any(n in ("source.apk", "source.ipa") for n in names), \
            f"expected source.apk/ipa in backup; got: {names}"
        # workspace/ entries land at workspace/<rel-path>/
        assert any(n.startswith("workspace/") for n in names)


def test_backup_all_endpoint_writes_per_project_zips(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    r = client.post("/v1/projects/backup-all")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["backed_up"] >= 1
    assert any(a["project_id"] == pid for a in body["archives"])
    # The output directory must exist on the server host.
    workspace = Path(client.app.state.nexus.config.workspace)
    backups = workspace / "backups"
    assert backups.exists()
    archives = list(backups.glob(f"project-{pid}-*.zip"))
    assert archives, f"no archive for {pid} in {backups}"


# ─── delete ────────────────────────────────────────────────────────────


def test_delete_refuses_without_confirm_flag(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client
    r = client.delete(f"/v1/projects/{pid}")
    assert r.status_code == 400
    assert "confirm" in r.text.lower()


def test_delete_wipes_workspace_db_and_returns_audit(lifecycle_client) -> None:
    client, pid, _ = lifecycle_client

    # Touch the cache so there's something to wipe.
    client.get(f"/v1/projects/{pid}/manifest")
    workspace = Path(client.app.state.nexus.config.workspace)
    cache_xml = workspace / pid / "apktool-manifest" / "AndroidManifest.xml"
    assert cache_xml.exists()

    r = client.delete(f"/v1/projects/{pid}?confirm=true")
    assert r.status_code == 200, r.text
    audit = r.json()["audit"]

    # Workspace gone.
    assert audit["workspace_dir_removed"] is True
    assert audit["workspace_files_removed"] >= 1
    assert not (workspace / pid).exists()

    # DB row gone — list_projects should drop it.
    r2 = client.get("/v1/projects")
    assert pid not in {p["id"] for p in r2.json()}

    # Source artefact removed (no other project shared the SHA).
    assert audit["source_artefact_removed"] is not None
    assert not Path(audit["source_artefact_removed"]).exists()


def test_delete_keeps_secrets_dir_when_package_shared(lifecycle_client) -> None:
    """When two projects share a package name, the PlayIntel secrets
    directory is keyed by package and must not be wiped on a per-project
    delete. Critical correctness property.

    Note on artefact files: the upload handler currently writes each
    upload to its own ``upload-<uuid>-<name>`` path, so two projects of
    the same SHA-256 still have distinct on-disk files. The delete path
    walks every other project's resolved apk_path and only keeps the
    file when another row points at the identical inode — making the
    behaviour future-proof even if the upload step ever dedupes by hash.
    """
    client, pid, _ = lifecycle_client
    workspace = Path(client.app.state.nexus.config.workspace)
    # Force a second project with the same package so the secrets dir
    # would be shared if it existed.
    secrets_dir = workspace / "secrets" / "com.target.app"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "evidence.txt").write_text("known leak fixture")

    apk_bytes = _build_minimal_apk()
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0.0", "force": "true"},
    )
    second_pid = r.json()["project_id"]
    assert second_pid != pid

    # Delete only the first one.
    rdel = client.delete(f"/v1/projects/{pid}?confirm=true")
    audit = rdel.json()["audit"]
    # The shared secrets dir (keyed by package) must NOT be wiped.
    assert audit["secrets_dir_removed"] is None
    assert secrets_dir.exists()
    # The second project still loads.
    r2 = client.get(f"/v1/projects/{second_pid}")
    assert r2.status_code == 200


def test_delete_all_endpoint_wipes_every_project(lifecycle_client) -> None:
    client, _, _ = lifecycle_client
    r = client.delete("/v1/projects?confirm=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] >= 1
    # Listing returns nothing now.
    r2 = client.get("/v1/projects")
    assert r2.json() == []


def test_delete_all_refuses_without_confirm(lifecycle_client) -> None:
    client, _, _ = lifecycle_client
    r = client.delete("/v1/projects")
    assert r.status_code == 400


# ─── flat CLI ──────────────────────────────────────────────────────────


def test_flat_find_command_emits_json(lifecycle_client) -> None:
    client, pid, tmp_path = lifecycle_client
    workspace = Path(client.app.state.nexus.config.workspace)
    fake = workspace / pid / "jadx" / "X.java"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("AIzaSyHELLO_WORLD", encoding="utf-8")

    runner = CliRunner(env={"MNEXUS_WORKSPACE": str(workspace),
                            "MNEXUS_DB_PATH": str(workspace.parent / "nexus.sqlite3")})
    result = runner.invoke(mnexus_cli, ["find", pid, "AIzaSyHELLO", "--json"], standalone_mode=False)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert any("HELLO_WORLD" in h["snippet"] for h in payload["hits"])


def test_flat_project_delete_requires_yes(lifecycle_client) -> None:
    client, pid, tmp_path = lifecycle_client
    workspace = Path(client.app.state.nexus.config.workspace)
    runner = CliRunner(env={"MNEXUS_WORKSPACE": str(workspace),
                            "MNEXUS_DB_PATH": str(workspace.parent / "nexus.sqlite3")})
    result = runner.invoke(mnexus_cli, ["project", "delete", pid], standalone_mode=False)
    assert result.exit_code == 2
    assert "refusing" in result.output.lower()


def test_flat_project_backup_writes_archive(lifecycle_client) -> None:
    client, pid, tmp_path = lifecycle_client
    workspace = Path(client.app.state.nexus.config.workspace)
    runner = CliRunner(env={"MNEXUS_WORKSPACE": str(workspace),
                            "MNEXUS_DB_PATH": str(workspace.parent / "nexus.sqlite3")})
    result = runner.invoke(mnexus_cli, ["project", "backup", pid, "--json"], standalone_mode=False)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    archive_path = Path(payload["archive_path"])
    assert archive_path.exists()
    assert archive_path.stat().st_size > 0
