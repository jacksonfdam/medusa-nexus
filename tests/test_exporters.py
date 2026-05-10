"""Smoke + structural tests for the API-collection / deeplink exporters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnexus.exporters import (
    to_burp_items,
    to_caido,
    to_deeplink_script,
    to_moxy_config,
    to_postman,
)
from mnexus.models.attack_surface import AttackSurface, ExportedComponent
from mnexus.models.project import Project


@pytest.fixture
def project_with_surface(tmp_path: Path) -> Project:
    apk = tmp_path / "demo.apk"
    apk.write_bytes(b"PK\x03\x04smoke")
    project = Project.from_apk(apk, package_name="com.demo.app", version="1.2.3")
    project.attack_surface = AttackSurface(
        api_endpoints=[
            "https://api.demo.com/v2/login",
            "https://api.demo.com/v2/accounts/me",
            "https://api.demo.com/v2/accounts/me",  # dup → must collapse
            "https://beacon.analytics.io/collect",
            "ftp://nope.example.com/",  # non-http → drop
        ],
        deeplinks=[
            "demo://oauth/callback?token=abc",
            "https://demo.com/share/123",
        ],
        exported_components=[
            ExportedComponent(name=".ui.LoginActivity", component_type="activity", unprotected=False),
            ExportedComponent(name=".ui.SecretActivity", component_type="activity", unprotected=True),
            ExportedComponent(name=".sync.SyncService", component_type="service"),
        ],
    )
    return project


def test_postman_collection_roundtrips_as_json(project_with_surface: Project) -> None:
    payload = json.loads(to_postman(project_with_surface))
    assert payload["info"]["schema"].endswith("collection.json")
    assert "MEDUSA NEXUS" in payload["info"]["name"]
    folders = {f["name"] for f in payload["item"]}
    assert "api.demo.com" in folders
    # Duplicate endpoint must not produce a duplicate item.
    api_items = [
        i for f in payload["item"] if f["name"] == "api.demo.com" for i in f["item"]
    ]
    assert len(api_items) == 2
    # Deeplinks land in their own folder.
    assert any(f["name"].startswith("deeplinks") for f in payload["item"])


def test_caido_collection_has_request_envelope(project_with_surface: Project) -> None:
    payload = json.loads(to_caido(project_with_surface))
    assert payload["exporter"] == "medusa-nexus"
    assert payload["metadata"]["project_id"] == project_with_surface.id
    methods = {r["method"] for r in payload["requests"]}
    assert methods == {"GET"}
    # 4 valid http endpoints minus 1 duplicate = 3 unique.
    assert len(payload["requests"]) == 3


def test_burp_items_xml_is_well_formed(project_with_surface: Project) -> None:
    xml = to_burp_items(project_with_surface)
    assert xml.startswith("<?xml")
    assert "<items" in xml and "</items>" in xml
    # Each unique endpoint becomes one <item>.
    assert xml.count("<item>") == 3
    # Base64 encoding flag must be set so Burp imports raw requests correctly.
    assert 'base64="true"' in xml


def test_moxy_config_lists_unique_hosts(project_with_surface: Project) -> None:
    yml = to_moxy_config(project_with_surface)
    assert "listen: 0.0.0.0:8080" in yml
    assert yml.count("- name: log api.demo.com") == 1
    assert "log beacon.analytics.io" in yml


def test_deeplink_script_includes_deeplinks_and_activities(project_with_surface: Project) -> None:
    script = to_deeplink_script(project_with_surface)
    assert script.startswith("#!/usr/bin/env bash")
    # Both deeplinks land.
    assert "demo://oauth/callback?token=abc" in script
    # Both exported activities land.
    assert ".ui.LoginActivity" in script
    assert ".ui.SecretActivity" in script
    # The non-activity component (service) should NOT be in the activity probes.
    activities = script.split("# ─── exported activities")[1]
    assert ".sync.SyncService" not in activities


def test_deeplink_script_handles_empty_surface(tmp_path: Path) -> None:
    apk = tmp_path / "empty.apk"
    apk.write_bytes(b"PK")
    project = Project.from_apk(apk, package_name="com.empty", version="0.0.1")
    project.attack_surface = AttackSurface()
    script = to_deeplink_script(project)
    assert "(no deeplinks recovered)" in script
    assert "(no exported activities recovered)" in script
