"""Analyzer integration test against a synthetic APK.

Builds a minimal zip that the analyzer's whitelist will pick up, runs
the full pipeline through :class:`LocalAPKSource`, and verifies that:

* The Firebase config is recovered.
* The Google API key from a fake google-services.json is propagated.
* A confirmed credential pattern produces a hit.
* Active probes are *not* run when ``run_active_probes=False`` (no
  outbound traffic from a unit test).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from mnexus.playintel.analyzer import analyze_package
from mnexus.playintel.apk_source import LocalAPKSource


@pytest.fixture()
def synthetic_apk(tmp_path: Path) -> Path:
    """Build a tiny APK fixture with one google-services.json entry."""
    apk = tmp_path / "fake.apk"
    google_services = {
        "project_info": {
            "project_id": "test-project",
            "project_number": "9999",
            "firebase_url": "https://test-project.firebaseio.com",
            "storage_bucket": "test-project.appspot.com",
        },
        "client": [
            {
                "client_info": {"mobilesdk_app_id": "1:9999:android:abc"},
                "api_key": [{"current_key": "AIzaSyTestKey00000000000000000000000000000"}],
                "oauth_client": [
                    {"client_id": "9999-web.apps.googleusercontent.com", "client_type": 3}
                ],
            }
        ],
    }
    # A confirmed-pattern credential we expect the detector to flag.
    secrets_payload = "github_token=ghp_0123456789abcdefABCDEFghijklmnoPQRST\n"

    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"<manifest package='com.test'/>")
        zf.writestr("assets/google-services.json", json.dumps(google_services))
        # .pem suffix → enters the scan whitelist; PEM-style content
        # ensures multi-line patterns get exercised even without a real key.
        zf.writestr("assets/secrets.pem", secrets_payload)
    return apk


def test_analyze_local_apk_recovers_firebase_config(synthetic_apk: Path, tmp_path: Path) -> None:
    source = LocalAPKSource(synthetic_apk)
    outcome = analyze_package(
        source,
        "com.test",
        workspace=tmp_path / "workspace",
        run_active_probes=False,
    )

    configs = outcome.report.get_firebase_configs()
    assert any(c.project_id == "test-project" for c in configs)
    test_cfg = next(c for c in configs if c.project_id == "test-project")
    assert test_cfg.api_key == "AIzaSyTestKey00000000000000000000000000000"
    assert test_cfg.database_url == "https://test-project.firebaseio.com"


def test_analyze_local_apk_finds_confirmed_secret(synthetic_apk: Path, tmp_path: Path) -> None:
    source = LocalAPKSource(synthetic_apk)
    outcome = analyze_package(
        source,
        "com.test",
        workspace=tmp_path / "workspace",
        run_active_probes=False,
    )
    confirmed = outcome.report.confirmed_secrets()
    assert any(s.type == "GitHub Token" for s in confirmed)


def test_analyze_local_apk_skips_active_probes_when_disabled(
    synthetic_apk: Path, tmp_path: Path
) -> None:
    source = LocalAPKSource(synthetic_apk)
    outcome = analyze_package(
        source,
        "com.test",
        workspace=tmp_path / "workspace",
        run_active_probes=False,
    )
    assert outcome.rtdb_results == []
    assert outcome.firestore_results == []
    assert outcome.storage_results == []


def test_analyze_local_apk_persists_saved_files(synthetic_apk: Path, tmp_path: Path) -> None:
    source = LocalAPKSource(synthetic_apk)
    outcome = analyze_package(
        source,
        "com.test",
        workspace=tmp_path / "workspace",
        run_active_probes=False,
    )
    # google-services.json contains an AIza* key → must be saved.
    assert outcome.saved_files_dir is not None
    assert outcome.saved_files_dir.exists()
    saved = list(outcome.saved_files_dir.iterdir())
    assert any("google-services" in p.name for p in saved)
