"""Firebase config recovery tests — google-services.json + resources.arsc map."""

from __future__ import annotations

import json

from mnexus.playintel.firebase_config import (
    FirebaseConfig,
    firebase_config_from_resources,
    is_google_services_json,
    parse_google_services_json,
    regex_fallback_project_ids,
)


def test_is_google_services_json_recognizes_variants() -> None:
    assert is_google_services_json("assets/google-services.json")
    assert is_google_services_json("assets/google-services-desktop.json")
    assert is_google_services_json("assets/google-services-debug.json")
    assert not is_google_services_json("assets/firebase-other.json")
    assert not is_google_services_json("assets/google-services.txt")


def test_parse_google_services_json_full_shape() -> None:
    doc = {
        "project_info": {
            "project_id": "my-project",
            "project_number": "1234567890",
            "firebase_url": "https://my-project.firebaseio.com",
            "storage_bucket": "my-project.appspot.com",
        },
        "client": [
            {
                "client_info": {
                    "mobilesdk_app_id": "1:1234567890:android:abc",
                },
                "oauth_client": [
                    {"client_id": "1234567890-android.apps.googleusercontent.com", "client_type": 1},
                    {"client_id": "1234567890-web.apps.googleusercontent.com", "client_type": 3},
                ],
                "api_key": [
                    {"current_key": "AIzaSyExample0000000000000000000000000000"},
                    {"current_key": "AIzaSyExtra1111111111111111111111111111111"},
                ],
            },
            {
                "client_info": {"mobilesdk_app_id": "1:1234567890:ios:def"},
                "api_key": [{"current_key": "AIzaSyAnother222222222222222222222222222222"}],
            },
        ],
    }
    cfg = parse_google_services_json(json.dumps(doc).encode("utf-8"), "assets/google-services.json")
    assert cfg is not None
    assert cfg.project_id == "my-project"
    assert cfg.database_url == "https://my-project.firebaseio.com"
    assert cfg.storage_bucket == "my-project.appspot.com"
    assert cfg.sender_id == "1234567890"
    assert cfg.app_id == "1:1234567890:android:abc"
    assert cfg.api_key == "AIzaSyExample0000000000000000000000000000"
    assert cfg.web_client_id == "1234567890-web.apps.googleusercontent.com"
    # Extra keys collected from same-client AND additional client entries.
    assert "AIzaSyExtra1111111111111111111111111111111" in cfg.additional_api_keys
    assert "AIzaSyAnother222222222222222222222222222222" in cfg.additional_api_keys


def test_parse_google_services_json_returns_none_without_project_id() -> None:
    cfg = parse_google_services_json(b'{"project_info": {}}', "x.json")
    assert cfg is None


def test_parse_google_services_json_returns_none_on_garbage() -> None:
    cfg = parse_google_services_json(b"not json", "x.json")
    assert cfg is None


def test_firebase_config_from_resources_maps_known_keys() -> None:
    resources = {
        "google_api_key": "AIzaSyExample0000000000000000000000000000",
        "google_app_id": "1:1234:android:abcdef",
        "firebase_database_url": "https://my-project.firebaseio.com",
        "google_storage_bucket": "my-project.appspot.com",
        "gcm_defaultSenderId": "1234",
        "default_web_client_id": "1234-web.apps.googleusercontent.com",
        "unrelated_string": "ignore me",
    }
    cfg = firebase_config_from_resources("my-project", resources, "ROOT/resources.arsc")
    assert cfg.project_id == "my-project"
    assert cfg.api_key == "AIzaSyExample0000000000000000000000000000"
    assert cfg.app_id == "1:1234:android:abcdef"
    assert cfg.database_url == "https://my-project.firebaseio.com"
    assert cfg.storage_bucket == "my-project.appspot.com"
    assert cfg.sender_id == "1234"
    assert cfg.web_client_id == "1234-web.apps.googleusercontent.com"


def test_realtime_db_candidates_dedup() -> None:
    cfg = FirebaseConfig(
        project_id="x",
        database_url="https://x.firebaseio.com",
    )
    candidates = cfg.realtime_db_candidates
    # The explicit URL appears, plus the two derived defaults; no duplicates.
    assert candidates[0] == "https://x.firebaseio.com"
    assert "https://x-default-rtdb.firebaseio.com" in candidates
    assert len(candidates) == len(set(candidates))


def test_regex_fallback_finds_project_id_in_xml() -> None:
    content = '<resources><string name="project_id">fallback-proj</string></resources>'
    found = regex_fallback_project_ids(content, "values/strings.xml")
    assert len(found) == 1
    assert found[0].project_id == "fallback-proj"
