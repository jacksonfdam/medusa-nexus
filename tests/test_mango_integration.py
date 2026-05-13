"""Mango deltas — flag decoder, manifest diff, deeplink fire/PoC.

Mango overlaps with Nexus on most fronts (pull, install, playstore,
proxy, logcat, search, session). The endpoints under test are the
three commands Nexus didn't already have:

  * /v1/mango/decode-flags                    (decodeflag)
  * /v1/projects/{id}/manifest-diff           (diff)
  * /v1/projects/{id}/mango/deeplink/fire     (deeplink)
  * /v1/projects/{id}/mango/deeplink/poc      (deeplink --poc)
"""

from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient

from mnexus.intelligence.android_flags import (
    INTENT_FLAGS,
    PENDING_INTENT_FLAGS,
    decode,
    decode_one,
    parse_flag_value,
    supported_namespaces,
)
from mnexus.intelligence.manifest_diff import diff_surfaces


# ─── android_flags unit tests ─────────────────────────────────────────


def test_parse_flag_value_accepts_hex_decimal_octal_binary() -> None:
    assert parse_flag_value("0x10000000") == 0x10000000
    assert parse_flag_value("268435456") == 0x10000000
    assert parse_flag_value("0o2000000000") == 0x10000000
    assert parse_flag_value(0x80) == 0x80
    assert parse_flag_value("0b101") == 0b101


def test_parse_flag_value_rejects_garbage() -> None:
    for bad in ("", "   ", "not-a-number", "0xZZ"):
        with pytest.raises(ValueError):
            parse_flag_value(bad)


def test_decode_one_picks_only_set_bits() -> None:
    val = INTENT_FLAGS["FLAG_ACTIVITY_NEW_TASK"] | INTENT_FLAGS["FLAG_FROM_BACKGROUND"]
    names = decode_one(val, INTENT_FLAGS)
    assert "FLAG_ACTIVITY_NEW_TASK" in names
    assert "FLAG_FROM_BACKGROUND" in names
    # FLAG_ACTIVITY_NO_HISTORY (0x40000000) isn't set — must not appear.
    assert "FLAG_ACTIVITY_NO_HISTORY" not in names


def test_decode_returns_one_namespace_when_specified() -> None:
    result = decode(0x04000000, namespaces=["pending_intent"])
    assert list(result.keys()) == ["pending_intent"]
    assert "FLAG_IMMUTABLE" in result["pending_intent"]


def test_decode_all_namespaces_returns_intent_and_receiver_simultaneously() -> None:
    # 0x10000000 is FLAG_ACTIVITY_NEW_TASK on Intents, FLAG_RECEIVER_FOREGROUND on
    # Receivers, FLAG_CANCEL_CURRENT on PendingIntents — Mango's classic example
    # of why a single integer needs the namespace prompt.
    out = decode(0x10000000)
    assert "FLAG_ACTIVITY_NEW_TASK" in out["intent"]
    assert "FLAG_RECEIVER_FOREGROUND" in out["receiver"]
    assert "FLAG_CANCEL_CURRENT" in out["pending_intent"]


def test_supported_namespaces_contract() -> None:
    assert set(supported_namespaces()) == {"intent", "receiver", "pending_intent", "content"}


# ─── manifest_diff unit tests ─────────────────────────────────────────


def _surface(**kw):
    return {
        "exported_components": kw.get("components", []),
        "deeplinks":            kw.get("deeplinks", []),
        "permissions":          kw.get("permissions", []),
        "url_schemes":          kw.get("url_schemes", []),
        "native_libraries":     kw.get("natives", []),
        "ssl_pinning_detected": kw.get("ssl", False),
        "ssl_pinning_library":  kw.get("ssl_lib"),
    }


def test_diff_surfaces_marks_added_and_removed_components() -> None:
    before = _surface(components=[
        {"name": "Main", "component_type": "activity", "exported": True, "unprotected": False},
    ])
    after = _surface(components=[
        {"name": "Main", "component_type": "activity", "exported": True, "unprotected": False},
        {"name": "Pay",  "component_type": "activity", "exported": True, "unprotected": True},
    ])
    d = diff_surfaces(before, after)
    assert d["summary"]["components_added"] == 1
    assert d["summary"]["components_removed"] == 0
    assert d["components"]["added"][0]["name"] == "Pay"


def test_diff_surfaces_detects_flipped_export_flag_as_changed() -> None:
    before = _surface(components=[
        {"name": "Main", "component_type": "activity", "exported": True, "unprotected": False},
    ])
    after = _surface(components=[
        {"name": "Main", "component_type": "activity", "exported": True, "unprotected": True},
    ])
    d = diff_surfaces(before, after)
    assert d["summary"]["components_changed"] == 1
    change = d["components"]["changed"][0]
    assert change["name"] == "Main"
    assert "unprotected" in change["fields"]


def test_diff_surfaces_marks_ssl_pinning_change() -> None:
    before = _surface(ssl=False)
    after = _surface(ssl=True, ssl_lib="okhttp")
    d = diff_surfaces(before, after)
    assert d["summary"]["ssl_pinning_changed"] is True
    assert d["ssl_pinning"]["detected_before"] is False
    assert d["ssl_pinning"]["detected_after"] is True
    assert d["ssl_pinning"]["library_after"] == "okhttp"


def test_diff_surfaces_against_empty_base_marks_everything_added() -> None:
    # No prior scan exists → diff_surfaces(None, head) shows the head as
    # 'all added'. The UI's empty-state copy depends on this.
    head = _surface(
        components=[{"name": "Main", "component_type": "activity", "exported": True, "unprotected": False}],
        deeplinks=["myapp://login"],
        permissions=["INTERNET"],
    )
    d = diff_surfaces(None, head)
    assert d["summary"]["any_changes"] is True
    assert d["summary"]["components_added"] == 1
    assert d["summary"]["deeplinks_added"] == 1
    assert d["summary"]["permissions_added"] == 1


def test_diff_surfaces_identical_returns_no_changes() -> None:
    s = _surface(
        components=[{"name": "Main", "component_type": "activity", "exported": True, "unprotected": False}],
        deeplinks=["myapp://login"],
        permissions=["INTERNET"],
    )
    d = diff_surfaces(s, s)
    assert d["summary"]["any_changes"] is False


# ─── endpoint round-trip ──────────────────────────────────────────────


@pytest.fixture
def mango_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        # One project to anchor the project-scoped endpoints.
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub"), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid, api_main.app


def test_decode_flags_endpoint_round_trips(mango_client) -> None:
    client, _, _ = mango_client
    r = client.post("/v1/mango/decode-flags", json={"value": "0x10000004", "namespaces": ["intent", "receiver"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hex"] == "0x10000004"
    assert body["value"] == 0x10000004
    assert body["namespaces"] == ["intent", "receiver"]
    assert "FLAG_ACTIVITY_NEW_TASK" in body["decoded"]["intent"]
    assert "FLAG_RECEIVER_FOREGROUND" in body["decoded"]["receiver"]
    # 'pending_intent' wasn't requested — must not show up.
    assert "pending_intent" not in body["decoded"]


def test_decode_flags_endpoint_rejects_unknown_namespace(mango_client) -> None:
    client, _, _ = mango_client
    r = client.post("/v1/mango/decode-flags", json={"value": "0x1", "namespaces": ["bogus"]})
    assert r.status_code == 400


def test_decode_flags_endpoint_rejects_bad_value(mango_client) -> None:
    client, _, _ = mango_client
    r = client.post("/v1/mango/decode-flags", json={"value": "not-a-number"})
    assert r.status_code == 400


def test_manifest_diff_with_no_prior_scan_returns_empty_base(mango_client) -> None:
    """Single-project workspace: there's no other scan of the package, so
    the endpoint returns base=null + a 'all added' diff against an empty
    surface (rather than 404'ing — the UI renders an empty state)."""
    client, pid, _ = mango_client
    r = client.get(f"/v1/projects/{pid}/manifest-diff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base"] is None
    assert body["package"] == "com.target.app"
    assert "diff" in body


def test_manifest_diff_picks_latest_prior_scan_of_same_package(mango_client) -> None:
    """Upload a second APK with the same package_name — manifest-diff
    should auto-pick the prior one as the base."""
    client, pid, _ = mango_client
    # Second scan, same package, different bytes → different project id.
    r = client.post(
        "/v1/apks/upload",
        files={"file": ("target2.apk", io.BytesIO(b"PK\x03\x04stub-v2"), "application/vnd.android.package-archive")},
        data={"package": "com.target.app", "version": "2.0"},
    )
    second_id = r.json()["project_id"]

    diff = client.get(f"/v1/projects/{second_id}/manifest-diff").json()
    assert diff["base"] is not None
    assert diff["base"]["id"] == pid
    assert diff["head"]["id"] == second_id


def test_manifest_diff_rejects_against_self(mango_client) -> None:
    client, pid, _ = mango_client
    r = client.get(f"/v1/projects/{pid}/manifest-diff?against={pid}")
    assert r.status_code == 400


def test_manifest_diff_404s_on_unknown_against_id(mango_client) -> None:
    client, pid, _ = mango_client
    r = client.get(f"/v1/projects/{pid}/manifest-diff?against=PRJ-NOPE")
    assert r.status_code == 404


def test_deeplink_poc_returns_html_with_escaped_uri(mango_client) -> None:
    client, pid, _ = mango_client
    uri = 'myapp://login?next=<script>alert(1)</script>'
    r = client.get(f"/v1/projects/{pid}/mango/deeplink/poc", params={"uri": uri})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # The dangerous payload must be escaped — no raw <script> in the body.
    assert "<script>alert(1)</script>" not in r.text
    assert "myapp://login" in r.text
    assert "com.target.app" in r.text  # package surfaced in the page


def test_deeplink_fire_503_when_no_device(mango_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """No connected device → 503 with an actionable message."""
    client, pid, app = mango_client

    async def no_device():
        return False

    app.state.nexus.engines["adb"].is_device_connected = no_device  # type: ignore[method-assign]
    r = client.post(f"/v1/projects/{pid}/mango/deeplink/fire", data={"uri": "myapp://x"})
    assert r.status_code == 503
    assert "no device" in r.text.lower()


def test_deeplink_fire_parses_resolved_activity(mango_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, pid, app = mango_client

    async def yes_device():
        return True

    async def fake_run(cmd):
        # Echo back a realistic `am start -W` output.
        return (
            "Starting: Intent { act=android.intent.action.VIEW dat=myapp://login flg=0x10000000 }\n"
            "Status: ok\n"
            "Activity: com.target.app/.LoginActivity\n"
            "ThisTime: 142\nTotalTime: 142\nWaitTime: 188\nComplete\n"
        )

    adb = app.state.nexus.engines["adb"]
    adb.is_device_connected = yes_device  # type: ignore[method-assign]
    adb._run = fake_run                    # type: ignore[method-assign]

    r = client.post(f"/v1/projects/{pid}/mango/deeplink/fire", data={"uri": "myapp://login"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fired"] is True
    assert body["activity"] == "com.target.app/.LoginActivity"
    assert "myapp://login" in body["raw"]


def test_deeplink_fire_rejects_empty_uri(mango_client) -> None:
    client, pid, _ = mango_client
    r = client.post(f"/v1/projects/{pid}/mango/deeplink/fire", data={"uri": "   "})
    assert r.status_code == 400
