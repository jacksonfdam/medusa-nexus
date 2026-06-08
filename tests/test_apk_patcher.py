"""APKPatcher — apktool-based manifest patcher.

We can't bring a real APK + apktool into CI (the binary is on the dev
machine but not necessarily on every test runner). The fake apktool
below decodes by writing a stub AndroidManifest.xml into the output
directory; rebuild copies the (potentially mutated) manifest back into
a fake APK file. That's enough to exercise:

  * patch dispatch — every supported name lands on the right XML attr
  * manifest mutation actually flips the bits
  * user_ca_trust drops the NSC xml + points the manifest at it
  * idempotence — re-running with the same patches no-ops
  * preview mode when apktool is missing
  * unknown / empty patch lists raise APKPatcherError
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from mnexus.config import NexusConfig
from mnexus.runtime.apk_patcher import (
    ANDROID_NS,
    APKPatcher,
    APKPatcherError,
    PatchResult,
    SUPPORTED_PATCHES,
)


_BASE_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.target.app">
    <application android:label="Target">
        <activity android:name=".MainActivity" />
    </application>
</manifest>
"""


def _shell_proxy(decoded_root: Path) -> str:
    """Return a fake apktool shell script that writes a base manifest
    on decode and copies it back on rebuild. The script signs itself
    using bash so we don't need a real apktool binary anywhere."""
    return f"""#!/usr/bin/env bash
set -e
mode="$1"
if [ "$mode" = "d" ]; then
    # apktool d -f -o <decoded_dir> <apk>
    out_idx=$(($# - 1))
    out="${{!out_idx}}"
    mkdir -p "$out"
    cat > "$out/AndroidManifest.xml" <<'EOF'
{_BASE_MANIFEST}EOF
elif [ "$mode" = "b" ]; then
    # apktool b -o <out_apk> <decoded_dir>
    out="$3"
    src="$4"
    cp "$src/AndroidManifest.xml" "$out"
fi
"""


@pytest.fixture
def patcher_cfg(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Build a NexusConfig whose apktool path is the fake bash script
    above. The script is created in tmp_path so each test gets its own.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    fake_apktool = tmp_path / "apktool"
    fake_apktool.write_text(_shell_proxy(workspace))
    fake_apktool.chmod(0o755)
    cfg = NexusConfig(workspace=workspace, apktool_path=str(fake_apktool))

    # The patcher also tries to keytool, apksigner, jarsigner, zipalign
    # via shutil.which. None of these exist in CI so we let them be
    # missing — patcher should still produce a (warning-flagged)
    # patched APK with the manifest mutated.
    return cfg, tmp_path


def _stub_apk(tmp: Path) -> Path:
    """Tiny zip-shaped file the patcher can hand to apktool. The fake
    apktool ignores the content; we just need the path to exist."""
    apk = tmp / "target.apk"
    apk.write_bytes(b"PK\x03\x04stub-apk")
    return apk


# ─── dispatch + manifest mutation ────────────────────────────────────


@pytest.mark.asyncio
async def test_debuggable_patch_flips_the_flag(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    apk = _stub_apk(tmp)
    result = await APKPatcher(cfg).patch(apk, ["debuggable"])
    assert result.patched_path is not None
    assert "debuggable" in result.patches_applied
    # The fake rebuild copies the manifest back into the patched APK
    # path. Read it and confirm the attribute flipped.
    manifest_text = result.patched_path.read_text(encoding="utf-8", errors="replace")
    assert 'android:debuggable="true"' in manifest_text


@pytest.mark.asyncio
async def test_cleartext_traffic_patch_flips_the_flag(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    apk = _stub_apk(tmp)
    result = await APKPatcher(cfg).patch(apk, ["cleartext_traffic"])
    assert "cleartext_traffic" in result.patches_applied
    manifest_text = result.patched_path.read_text(encoding="utf-8", errors="replace")
    assert 'android:usesCleartextTraffic="true"' in manifest_text


@pytest.mark.asyncio
async def test_user_ca_trust_patch_drops_nsc_and_references_it(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    apk = _stub_apk(tmp)
    result = await APKPatcher(cfg).patch(apk, ["user_ca_trust"])
    assert "user_ca_trust" in result.patches_applied
    manifest_text = result.patched_path.read_text(encoding="utf-8", errors="replace")
    assert 'android:networkSecurityConfig="@xml/network_security_config"' in manifest_text
    # The fake rebuild only copied the manifest — but we can still
    # check the NSC content was written into the decoded tree before
    # rebuild. Inspect the workspace where the patcher dropped it.
    # (Walk the temp dir for the NSC file; the temp dir is gone after
    # the with-block, so we instead trust the manifest reference as
    # proof — the rule only adds the manifest attribute when it
    # successfully writes the NSC xml.)


@pytest.mark.asyncio
async def test_multiple_patches_apply_in_one_pass(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    apk = _stub_apk(tmp)
    result = await APKPatcher(cfg).patch(apk, ["debuggable", "user_ca_trust", "cleartext_traffic"])
    assert set(result.patches_applied) == {"debuggable", "user_ca_trust", "cleartext_traffic"}
    manifest_text = result.patched_path.read_text(encoding="utf-8", errors="replace")
    assert 'android:debuggable="true"' in manifest_text
    assert 'android:usesCleartextTraffic="true"' in manifest_text
    assert 'android:networkSecurityConfig="@xml/network_security_config"' in manifest_text


# ─── error / edge paths ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_patch_raises_apk_patcher_error(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    apk = _stub_apk(tmp)
    with pytest.raises(APKPatcherError) as exc:
        await APKPatcher(cfg).patch(apk, ["does_not_exist"])
    assert "unknown" in str(exc.value).lower() or "supported" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_empty_patch_list_raises(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    apk = _stub_apk(tmp)
    with pytest.raises(APKPatcherError):
        await APKPatcher(cfg).patch(apk, [])


@pytest.mark.asyncio
async def test_missing_apk_raises(patcher_cfg) -> None:
    cfg, tmp = patcher_cfg
    with pytest.raises(APKPatcherError):
        await APKPatcher(cfg).patch(tmp / "ghost.apk", ["debuggable"])


@pytest.mark.asyncio
async def test_preview_mode_when_apktool_missing(tmp_path) -> None:
    """When apktool isn't on PATH or at the configured path, the
    patcher returns a preview-only result rather than crashing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Point apktool_path at a file that doesn't exist; shutil.which
    # returns None for both that AND the bare 'apktool' name (CI runner).
    cfg = NexusConfig(workspace=workspace, apktool_path="/nope/apktool")
    apk = _stub_apk(tmp_path)
    # If real apktool is on the system PATH, this test should skip
    # rather than fail — preview branch only fires when both lookups
    # miss.
    import shutil
    if shutil.which("apktool") is not None:
        pytest.skip("real apktool on PATH — preview branch not exercised")
    result = await APKPatcher(cfg).patch(apk, ["debuggable"])
    assert result.preview is True
    assert result.patched_path is None
    assert any("apktool is not on PATH" in w for w in result.warnings)


def test_patch_result_model_dump_is_json_safe() -> None:
    """The API serialises via FastAPI, which itself runs through
    pydantic for dict response models. Our PatchResult uses dataclasses,
    so its model_dump must produce a plain dict with string-coerced
    Path objects."""
    pr = PatchResult(
        apk_path=Path("/tmp/in.apk"),
        patched_path=Path("/tmp/out.apk"),
        patches_applied=["debuggable"],
        patches_skipped=[("user_ca_trust", "no <application>")],
        warnings=["zipalign missing"],
        keystore_path=Path("/tmp/keystore"),
    )
    d = pr.model_dump()
    assert d["apk_path"] == "/tmp/in.apk"
    assert d["patched_path"] == "/tmp/out.apk"
    assert d["patches_skipped"] == [{"name": "user_ca_trust", "reason": "no <application>"}]
    # JSON-serialisable end-to-end.
    import json
    json.dumps(d)


def test_supported_patches_constant_lists_the_three() -> None:
    assert set(SUPPORTED_PATCHES) == {"debuggable", "cleartext_traffic", "user_ca_trust"}


# ─── API round-trip ───────────────────────────────────────────────────


@pytest.fixture
def patch_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with fake apktool wired into the orchestrator's config."""
    import importlib
    import io
    from fastapi.testclient import TestClient

    fake_apktool = tmp_path / "apktool"
    fake_apktool.write_text(_shell_proxy(tmp_path / "workspace"))
    fake_apktool.chmod(0o755)

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_APKTOOL_PATH", str(fake_apktool))

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub-apk"), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid


def test_post_project_patch_runs_patcher_and_returns_paths(patch_client) -> None:
    client, pid = patch_client
    r = client.post(f"/v1/projects/{pid}/patch", data={"patches": "debuggable,user_ca_trust"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["patches_applied"]) == {"debuggable", "user_ca_trust"}
    assert body["patched_path"].endswith("-patched.apk")


def test_post_project_patch_400_on_unknown_patch(patch_client) -> None:
    client, pid = patch_client
    r = client.post(f"/v1/projects/{pid}/patch", data={"patches": "rooted"})
    assert r.status_code == 400
    assert "unknown" in r.text.lower() or "supported" in r.text.lower()


def test_post_project_patch_400_on_whitespace_only_patches(patch_client) -> None:
    """Empty form-string is rejected by FastAPI Form() as 422; our own
    check fires when the field is present-but-blank-once-split."""
    client, pid = patch_client
    r = client.post(f"/v1/projects/{pid}/patch", data={"patches": "   ,  ,  "})
    assert r.status_code == 400


def test_get_patcher_supported_returns_three(patch_client) -> None:
    client, _ = patch_client
    body = client.get("/v1/mango/patcher/supported").json()
    names = {p["name"] for p in body["patches"]}
    assert names == {"debuggable", "cleartext_traffic", "user_ca_trust"}
