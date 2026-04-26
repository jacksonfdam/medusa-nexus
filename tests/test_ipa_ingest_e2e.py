"""End-to-end iOS ingest tests.

Builds a synthetic IPA in-memory (zip with Info.plist + Mach-O magic bytes
+ entitlements via embedded.mobileprovision), uploads it through the API,
and asserts: platform = "ios", findings populate, every project sub-view
returns 200.
"""

from __future__ import annotations

import io
import plistlib
import struct
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ─── synthetic IPA builder ──────────────────────────────────────────────

_MACHO_64_LE = b"\xcf\xfa\xed\xfe"          # MH_MAGIC_64 (LE)
_CPU_TYPE_ARM64 = (0x01000000 | 0x0C)        # ARM64 cputype


def _macho_arm64_blob(extra: bytes = b"") -> bytes:
    """Bare-minimum Mach-O 64 header so our format detector says 'macho'."""
    # mach_header_64: magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved
    header = (
        _MACHO_64_LE
        + struct.pack("<I", _CPU_TYPE_ARM64)
        + struct.pack("<I", 0)          # cpusubtype
        + struct.pack("<I", 2)          # MH_EXECUTE
        + struct.pack("<I", 0)          # ncmds
        + struct.pack("<I", 0)          # sizeofcmds
        + struct.pack("<I", 0)          # flags
        + struct.pack("<I", 0)          # reserved
    )
    return header + extra


def _provisioning_blob(get_task_allow: bool, expired: bool = False) -> bytes:
    """Build a CMS-ish provisioning profile: just a plist sandwich is enough
    for our regex-based parser."""
    plist = {
        "AppIDName": "Test Bank",
        "TeamIdentifier": ["A1B2C3D4E5"],
        "TeamName": "Test Team",
        "CreationDate": "2025-01-01T00:00:00Z",
        "ExpirationDate": "2020-01-01T00:00:00Z" if expired else "2030-01-01T00:00:00Z",
        "Entitlements": {
            "application-identifier": "A1B2C3D4E5.com.target.bank",
            "get-task-allow": get_task_allow,
            "com.apple.developer.associated-domains": ["applinks:bank.example.com"],
        },
    }
    inner = plistlib.dumps(plist, fmt=plistlib.FMT_XML)
    # Wrap with bogus CMS bytes — our parser greps for `<?xml` / `</plist>`.
    return b"\x30\x82\x00\x00fake-cms-prefix-" + inner + b"-fake-cms-suffix"


def _info_plist_blob() -> bytes:
    info = {
        "CFBundleIdentifier": "com.target.bank",
        "CFBundleShortVersionString": "4.12.0",
        "CFBundleVersion": "412",
        "CFBundleExecutable": "TargetBank",
        "MinimumOSVersion": "13.0",
        "NSAppTransportSecurity": {
            "NSAllowsArbitraryLoads": True,
            "NSExceptionDomains": {
                "legacy.target.com": {"NSExceptionAllowsInsecureHTTPLoads": True},
            },
        },
        "CFBundleURLTypes": [
            {"CFBundleURLSchemes": ["bankapp", "https"]},
        ],
        "NSCameraUsageDescription": "We need the camera to scan checks.",
        "NSContactsUsageDescription": "We need contacts for transfers.",
    }
    return plistlib.dumps(info, fmt=plistlib.FMT_XML)


def _build_fake_ipa() -> bytes:
    # Strings the Mach-O scanner picks up: CommonCrypto + NSLog + jailbreak paths.
    binary_strings = (
        b"_CCCryptCallback\x00"
        b"kSecAttrAccessibleAlwaysThisDeviceOnly\x00"
        b"NSLog format token=%@ password=%@\x00"
        b"PT_DENY_ATTACH\x00"
        b"/Applications/Cydia.app\x00"
        b"AES_encrypt\x00"
        b"OpenSSL 1.1.1k\x00"
    )
    main_bin = _macho_arm64_blob(extra=binary_strings)

    # Embedded framework — gives us a non-empty native_libraries listing.
    fw_bin = _macho_arm64_blob(extra=b"NSURLSession\x00FirebaseCore\x00")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Payload/TargetBank.app/Info.plist", _info_plist_blob())
        z.writestr("Payload/TargetBank.app/embedded.mobileprovision", _provisioning_blob(get_task_allow=True))
        z.writestr("Payload/TargetBank.app/TargetBank", main_bin)
        z.writestr("Payload/TargetBank.app/Frameworks/FirebaseCore.framework/FirebaseCore", fw_bin)
        z.writestr("Payload/TargetBank.app/PlugIns/ShareExt.appex/Info.plist", _info_plist_blob())
    return buf.getvalue()


# ─── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    import importlib

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


# ─── tests ───────────────────────────────────────────────────────────────

def test_ipa_upload_creates_ios_project(isolated_client: TestClient) -> None:
    """Happy path: upload an IPA, project comes back with platform=ios."""
    apk = io.BytesIO(_build_fake_ipa())
    r = isolated_client.post(
        "/v1/ipas/upload",
        files={"file": ("target.ipa", apk, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"].startswith("PRJ-")
    assert body["platform"] == "ios"
    assert body["package"] == "com.target.bank"
    assert body["version"] == "4.12.0"


def test_ipa_via_apks_endpoint_autodetects(isolated_client: TestClient) -> None:
    """The shared `/v1/apks/upload` endpoint should sniff IPAs too."""
    apk = io.BytesIO(_build_fake_ipa())
    r = isolated_client.post(
        "/v1/apks/upload",
        files={"file": ("mystery.ipa", apk)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["platform"] == "ios"


def test_ipa_findings_cover_atss_and_debuggable_signing(isolated_client: TestClient) -> None:
    apk = io.BytesIO(_build_fake_ipa())
    r = isolated_client.post(
        "/v1/ipas/upload",
        files={"file": ("target.ipa", apk)},
    )
    pid = r.json()["project_id"]
    findings = isolated_client.get(f"/v1/projects/{pid}/findings").json()
    titles = {f["title"] for f in findings}
    # ATS arbitrary-loads is the must-have signal.
    assert any("Arbitrary" in t or "Transport Security" in t for t in titles), titles
    # Debuggable signing (get-task-allow=true) must surface.
    assert any("get-task-allow" in t or "debuggable" in t.lower() for t in titles), titles
    # `https://` registered as a URL scheme should be flagged as high-risk.
    assert any("URL scheme" in t for t in titles), titles


def test_ipa_attack_surface_populated(isolated_client: TestClient) -> None:
    apk = io.BytesIO(_build_fake_ipa())
    r = isolated_client.post(
        "/v1/ipas/upload",
        files={"file": ("target.ipa", apk)},
    )
    pid = r.json()["project_id"]
    project = isolated_client.get(f"/v1/projects/{pid}").json()
    surface = project["attack_surface"]
    assert "bankapp" in surface["url_schemes"]
    # Universal-link domain should land in deeplinks.
    assert any("bank.example.com" in d for d in surface["deeplinks"])
    # Native libs should include the main binary + framework.
    assert len(surface["native_libraries"]) >= 2
    # iOS Privacy keys → permissions.
    assert any("CameraUsageDescription" in p for p in surface["permissions"])
    # Entitlements → AttackSurface.entitlements.
    assert any("get-task-allow" in e for e in surface["entitlements"])
    # Provisioning profile parsed.
    assert surface["provisioning_profile"] is not None
    assert surface["provisioning_profile"]["team_id"] == "A1B2C3D4E5"


def test_ipa_every_subview_renders(isolated_client: TestClient) -> None:
    apk = io.BytesIO(_build_fake_ipa())
    pid = isolated_client.post(
        "/v1/ipas/upload",
        files={"file": ("target.ipa", apk)},
    ).json()["project_id"]

    for sub in (
        "secrets", "components", "native", "api-map", "ssl-map",
        "owasp", "attack-tree", "dataflow", "surface", "hooks",
        "correlations", "traffic",
    ):
        r = isolated_client.get(f"/v1/projects/{pid}/{sub}")
        assert r.status_code == 200, f"{sub} -> {r.status_code} body={r.text[:200]}"


def test_ipa_rescan_keeps_id_and_data(isolated_client: TestClient) -> None:
    """Rescanning an iOS project shouldn't change its id and should reproduce findings."""
    apk = io.BytesIO(_build_fake_ipa())
    pid = isolated_client.post(
        "/v1/ipas/upload",
        files={"file": ("target.ipa", apk)},
    ).json()["project_id"]

    before = isolated_client.get(f"/v1/projects/{pid}/findings").json()
    rescan = isolated_client.post(f"/v1/projects/{pid}/rescan")
    assert rescan.status_code == 200, rescan.text
    j = rescan.json()
    assert j["project_id"] == pid
    after = isolated_client.get(f"/v1/projects/{pid}/findings").json()
    assert len(after) == len(before)


def test_ipa_hooks_are_ios_flavoured(isolated_client: TestClient) -> None:
    """HookGenerator should emit Obj-C / NSURLConnection hooks, not Java.perform."""
    apk = io.BytesIO(_build_fake_ipa())
    pid = isolated_client.post(
        "/v1/ipas/upload",
        files={"file": ("target.ipa", apk)},
    ).json()["project_id"]

    hooks = isolated_client.get(f"/v1/projects/{pid}/hooks").json()
    assert hooks, "expected at least one auto-hook for an iOS project"
    names = [h["name"] for h in hooks]
    assert any("ios" in n.lower() or "ssl_kill" in n.lower() or "keychain" in n.lower() for n in names), names
    # No Java.perform — this would mean we fed an iOS surface into the Android branch.
    for h in hooks:
        assert "Java.perform" not in h["script"], f"{h['name']} contains Android Java hook"


def test_recipes_endpoint_exposes_ios_builtins(isolated_client: TestClient) -> None:
    recipes = isolated_client.get("/v1/recipes?platform=ios").json()
    names = [r["name"] for r in recipes]
    for required in ("ios_ssl_kill_switch", "ios_jailbreak_bypass", "ios_keychain_dump"):
        assert required in names, names


def test_recipes_script_endpoint_returns_ios_script(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/recipes/ios_ssl_kill_switch/script")
    assert r.status_code == 200
    body = r.json()
    assert "SecTrustEvaluate" in body["script"]
    assert body["platform"] == "ios"
