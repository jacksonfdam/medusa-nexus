"""End-to-end APK ingest + every project-level endpoint.

Mirrors what test_ipa_ingest_e2e.py does for iOS. The APK we hand
the upload is a minimal-but-structurally-valid zip — the static
engines mostly fall back to filename heuristics, but we walk every
screen's data endpoint to make sure the wiring holds end to end.

This is the test that catches integration regressions: API route
shape changes, schema migrations not running, new endpoints that
forget the 'no findings' empty state.
"""

from __future__ import annotations

import importlib
import io
import zipfile

import pytest
from fastapi.testclient import TestClient


def _build_minimal_apk() -> bytes:
    """Tiny zip-as-APK with a placeholder Mach-O-less structure.

    We can't easily hand-craft binary AndroidManifest.xml (AXML) from
    scratch without a generator, so the apktool fallback uses the
    filename stem. That's exactly the path real APKs hit when AOSP's
    AXML format moves (Android 14 compact entries, etc.) and the
    decoder can't parse — which makes this fixture realistic, not
    pathological.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Minimal entries the orchestrator looks for. Empty manifest
        # forces the filename fallback; empty classes.dex is OK because
        # the DEX-string scanner just produces zero findings.
        zf.writestr("AndroidManifest.xml", b"")
        zf.writestr("classes.dex", b"dex\n035\x00")
        zf.writestr("resources.arsc", b"")
        # A tiny ELF-shaped stub under lib/arm64-v8a/ so the native
        # tab has something to render. _binary_format sniffs '\x7fELF';
        # the scanner walks the bytes for patterns.
        elf = (
            b"\x7fELF\x02\x01\x01" + b"\x00" * 9     # e_ident
            + b"\x00" * 48                            # rest of header
            + b"\x00Java_com_target_Foo_bar\x00"      # JNI export pattern
            + b"https://api.target.com/x\x00"
        )
        zf.writestr("lib/arm64-v8a/libtarget.so", elf)
    return buf.getvalue()


@pytest.fixture
def e2e_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """TestClient backed by a fresh workspace + DB."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def test_apk_e2e_walks_every_project_subroute(e2e_client) -> None:
    """Upload a real-shaped APK, then GET every project sub-endpoint
    we ship — they should all 200 without their renderers crashing on
    empty data."""
    apk_bytes = _build_minimal_apk()
    r = e2e_client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    pid = body["project_id"]
    assert pid.startswith("PRJ-")
    assert body["package"] == "com.target.app"
    assert body["dedup"] is False

    # Every project-scoped sub-endpoint shipped in the SPA's data layer.
    for sub in (
        "",                        # project root
        "findings",
        "secrets",
        "components",
        "native",
        "api-map",
        "ssl-map",
        "owasp",
        "attack-tree",
        "dataflow",
        "surface",
        "hooks",
        "correlations",
        "traffic",
        "manifest-diff",           # auto-picks base; first scan → base=null
        "findings-diff",           # same auto-pick behavior
    ):
        path = f"/v1/projects/{pid}{('/' + sub) if sub else ''}"
        r = e2e_client.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code} body={r.text[:200]}"

    # Reports — every format renders without crashing. PDF + PNG fall
    # back to HTML when WeasyPrint / Chromium aren't on the test runner.
    # Drive through the HTTP layer (POST /v1/projects/{id}/report) so the
    # DB writes happen on the worker thread that owns the connection.
    for fmt in ("markdown", "json", "html"):
        rr = e2e_client.post(
            f"/v1/projects/{pid}/report",
            data={"template": "technical", "fmt": fmt},
        )
        assert rr.status_code == 200, f"{fmt} report → {rr.status_code}: {rr.text[:200]}"
        # Response is the file body; non-empty proves the generator ran.
        assert len(rr.content) > 0, f"{fmt} report was empty"


def test_apk_e2e_native_analyze_extracts_jni_and_urls(e2e_client) -> None:
    """The lib/arm64-v8a/libtarget.so stub carries a JNI export string +
    a hardcoded URL. /v1/projects/{id}/native/analyze should surface both."""
    apk_bytes = _build_minimal_apk()
    r = e2e_client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0.0"},
    )
    pid = r.json()["project_id"]
    rr = e2e_client.get(f"/v1/projects/{pid}/native/analyze", params={"lib": "lib/arm64-v8a/libtarget.so"})
    assert rr.status_code == 200, rr.text
    body = rr.json()
    assert body["format"] == "elf"
    assert "Java_com_target_Foo_bar" in body["jni_exports"]
    assert "https://api.target.com/x" in body["hardcoded_urls"]


def test_apk_e2e_dedup_returns_existing_project(e2e_client) -> None:
    """Two uploads of the same APK bytes → second hits dedup, no new
    project. Pins the SHA-256 contract end-to-end."""
    apk_bytes = _build_minimal_apk()
    upload = lambda: e2e_client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0.0"},
    )
    first = upload().json()
    second = upload().json()
    assert second["project_id"] == first["project_id"]
    assert second["dedup"] is True
    listing = e2e_client.get("/v1/projects").json()
    assert sum(1 for p in listing if p["id"] == first["project_id"]) == 1


def test_apk_e2e_force_rescan_creates_fresh_project(e2e_client) -> None:
    """force=true bypasses dedup and produces a new Project record with
    the same SHA but a fresh id — documented contract from /apks/upload."""
    apk_bytes = _build_minimal_apk()
    first = e2e_client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0.0"},
    ).json()
    second = e2e_client.post(
        "/v1/apks/upload",
        files={"file": ("target.apk", io.BytesIO(apk_bytes), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "1.0.0", "force": "true"},
    ).json()
    assert second["project_id"] != first["project_id"]
    assert second["apk_sha256"] == first["apk_sha256"]
    assert second["dedup"] is False
