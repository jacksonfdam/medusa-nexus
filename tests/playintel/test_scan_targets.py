"""Scan-target whitelist tests — the gate that decides which entries get read."""

from __future__ import annotations

from mnexus.playintel.scan_targets import (
    is_high_value_scan_file,
    is_service_account_json_candidate,
    should_scan_zip_entry,
)


def test_resources_arsc_always_scanned() -> None:
    assert is_high_value_scan_file("resources.arsc")


def test_google_services_json_always_scanned() -> None:
    assert is_high_value_scan_file("assets/google-services.json")
    assert is_high_value_scan_file("assets/google-services-desktop.json")


def test_react_native_bundle_scanned() -> None:
    assert is_high_value_scan_file("assets/index.android.bundle")
    assert is_high_value_scan_file("assets/some-other.bundle")
    assert is_high_value_scan_file("assets/main.jsbundle")


def test_cordova_www_js_scanned() -> None:
    assert is_high_value_scan_file("assets/www/js/app.js")


def test_xamarin_dll_scanned() -> None:
    assert is_high_value_scan_file("assemblies/MyApp.dll")


def test_unrelated_file_not_scanned() -> None:
    assert not is_high_value_scan_file("assets/textures/logo.png")
    assert not is_high_value_scan_file("classes.dex")


def test_service_account_json_size_filter() -> None:
    # Inside the plausible service-account JSON size band.
    assert is_service_account_json_candidate("assets/credentials.json", 2048)
    # Too small.
    assert not is_service_account_json_candidate("assets/credentials.json", 100)
    # Too large.
    assert not is_service_account_json_candidate("assets/credentials.json", 9000)


def test_pem_files_scanned_via_top_level_check() -> None:
    assert should_scan_zip_entry("assets/cert.pem", 4096)


def test_should_scan_zip_entry_combines_rules() -> None:
    # Service-account JSON candidate by size only — high-value check is false.
    assert should_scan_zip_entry("res/raw/blob.json", 1024)
    # Not whitelisted under any rule.
    assert not should_scan_zip_entry("res/drawable/icon.xml", 1024)
