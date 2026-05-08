"""Scan-target selection — which zip entries actually get read.

Reading every entry in a 100 MB APK would defeat the point of
streaming. The whitelist below is deliberately narrow and matches the
Go reference scanner (``pkg/googleplay/scan_targets.go``):

* ``resources.arsc`` and ``AndroidManifest.xml`` — always.
* Firebase / AWS / Amplify config files — by basename.
* JS bundles (``.bundle``, ``.jsbundle``, ``index.android.bundle``) —
  React Native apps tend to ship secrets there.
* Cordova / Ionic web bundles (``www/*.js``, ``www/config.xml``).
* .NET ``assemblies/*.dll`` — Xamarin / MAUI bundle CIL there.
* Service-account-shaped JSON files.
* Any ``*.pem`` — usually only test certs, but cheap to verify.
"""

from __future__ import annotations

from mnexus.playintel.firebase_config import is_google_services_json

# Files we always read. Lower-cased path comparison.
_ALWAYS_READ = (
    "resources.arsc",
    "google_services.xml",
    "awsconfiguration.json",
    "amplifyconfiguration.json",
    "androidmanifest.xml",
)

_ALWAYS_READ_SUFFIXES = (
    "/google_services.xml",
    "/awsconfiguration.json",
    "/amplifyconfiguration.json",
)


def is_high_value_scan_file(lower_name: str) -> bool:
    """Return ``True`` for files known to carry credentials."""
    if lower_name in _ALWAYS_READ:
        return True
    if any(lower_name.endswith(s) for s in _ALWAYS_READ_SUFFIXES):
        return True
    if is_google_services_json(lower_name):
        return True
    if lower_name.endswith((".bundle", ".jsbundle")):
        return True
    if lower_name == "assets/index.android.bundle":
        return True
    if "/www/" in lower_name and lower_name.endswith(".js"):
        return True
    if lower_name.endswith("/www/config.xml"):
        return True
    if lower_name.startswith("assemblies/") and lower_name.endswith(".dll"):
        return True
    return False


def is_service_account_json_candidate(lower_name: str, size: int) -> bool:
    """Cheap pre-filter for service-account JSON files.

    Real Google service-account JSONs are 1.5–3 KB. Files that are
    much larger or much smaller almost never contain one, so we use
    size as a first cut before opening them.
    """
    return lower_name.endswith(".json") and 256 <= size <= 8192


def should_scan_zip_entry(lower_name: str, size: int) -> bool:
    """Final whitelist check used by the scanner."""
    return (
        is_high_value_scan_file(lower_name)
        or is_service_account_json_candidate(lower_name, size)
        or lower_name.endswith(".pem")
    )
