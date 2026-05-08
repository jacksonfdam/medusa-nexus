"""Zip-entry scanner — route each whitelisted entry to the right parser.

For every entry that :func:`scan_targets.should_scan_zip_entry` allows
through, this module decides which structured parser to apply
(``resources.arsc``, ``google-services.json``, generic regex sweep) and
folds the per-entry result into a :class:`ScanZipResult`.

Persistence policy: a file's raw bytes are saved into the result's
``saved_files`` dict if any of these are true:

* It contains at least one ``AIza*`` Google API key.
* It's a ``resources.arsc`` whose parse yielded a Firebase project ID.
* It's a ``resources.arsc`` containing at least one *confirmed*
  secret-pattern hit.
* A confirmed multi-line pattern (e.g. PEM private key) matched.

Suspected-only matches are not enough to save the file — they're high
false-positive shapes and we want to keep the secrets/ directory tight.
"""

from __future__ import annotations

import zipfile

from mnexus.playintel.firebase_config import (
    GOOGLE_API_KEY_RE,
    FirebaseConfig,
    firebase_config_from_resources,
    is_google_services_json,
    parse_google_services_json,
    regex_fallback_project_ids,
)
from mnexus.playintel.scan_report import ScanZipResult
from mnexus.playintel.scan_targets import should_scan_zip_entry
from mnexus.playintel.secret_detector import (
    SecretMatch,
    match_secrets_multiline,
    match_secrets_with_decode,
)


def scan_zip(zr, prefix: str) -> ScanZipResult:  # type: ignore[no-untyped-def]
    """Scan every whitelisted entry in ``zr`` (a :class:`RemoteZip` or
    :class:`LocalZip`).

    ``prefix`` is prepended to the display path of each entry so a
    finding from the base APK can be distinguished from one in a split
    (``"split_arm64-v8a.apk"``).
    """
    result = ScanZipResult()
    all_api_keys: set[str] = set()

    # Decide entries up-front so we can prefetch in parallel.
    targets: list[zipfile.ZipInfo] = []
    for info in zr.infos():
        lower = info.filename.lower()
        if should_scan_zip_entry(lower, info.file_size):
            targets.append(info)

    zr.prefetch_entries(t.filename for t in targets)

    for info in targets:
        try:
            data = zr.open_entry(info.filename)
        except (KeyError, zipfile.BadZipFile, RuntimeError):
            continue
        display = _display_name(prefix, info.filename)
        scan = _scan_entry(display, info.filename.lower(), data)
        _merge(result, scan, all_api_keys)

    _attach_additional_api_keys(result.firebase_configs, all_api_keys)
    return result


def _display_name(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


# ─── per-entry routing ────────────────────────────────────────────────────


def _scan_entry(display: str, lower_name: str, data: bytes) -> ScanZipResult:
    """Dispatch one entry's bytes to the appropriate parser."""
    scan = ScanZipResult()
    content = data.decode("utf-8", errors="replace")

    api_key_hits = GOOGLE_API_KEY_RE.findall(content)
    api_keys: set[str] = set(api_key_hits)
    if api_keys:
        scan.saved_files[display] = data

    # resources.arsc — full structured parse.
    if lower_name.endswith("resources.arsc"):
        secrets, fb = _scan_arsc(data, display)
        scan.secrets.extend(secrets)
        if fb.project_id:
            scan.firebase_configs.append(fb)
            scan.saved_files[display] = data
        if _contains_confirmed_secret(secrets):
            scan.saved_files[display] = data
        # Stash any AIza keys we saw in the arsc string pool too. Done
        # via the api_keys set — caller will attach them as additional
        # keys to every Firebase config.
        for k in GOOGLE_API_KEY_RE.findall(content):
            api_keys.add(k)
        scan.techs["resources.arsc"] = display
        # Bail early — arsc files are often tens of MB and the
        # structured parser already covers them.
        # Still propagate api_keys via the closure variable below.
        scan = _attach_keys(scan, api_keys)
        return scan

    # AndroidManifest.xml — used as a Firestore presence marker.
    if lower_name == "androidmanifest.xml" and "firebase.firestore" in content:
        scan.techs["Firebase Firestore"] = display

    # google-services*.json — full structured parse.
    if is_google_services_json(lower_name):
        cfg = parse_google_services_json(data, display)
        if cfg is not None:
            scan.firebase_configs.append(cfg)
            scan.saved_files[display] = data

    # Generic JSON — try the service-account shape.
    if lower_name.endswith(".json"):
        sa = _detect_service_account_secret(content, display)
        if sa is not None:
            scan.secrets.append(sa)
            scan.saved_files[display] = data

    # Regex fallback for ``project_id`` in arbitrary content.
    fallback = regex_fallback_project_ids(content, display)
    scan.firebase_configs.extend(fallback)

    # Multi-line secret patterns — PEM keys etc.
    multiline = match_secrets_multiline(content, display)
    scan.secrets.extend(multiline)
    if _contains_confirmed_secret(multiline):
        scan.saved_files[display] = data

    return _attach_keys(scan, api_keys)


def _scan_arsc(data: bytes, display: str) -> tuple[list[SecretMatch], FirebaseConfig]:
    """Parse a ``resources.arsc`` blob and run secret detection on values."""
    # Lazy import to keep this module's import-time cheap.
    from mnexus.playintel.arsc import parse_arsc

    parsed = parse_arsc(data)
    fb = firebase_config_from_resources(parsed.project_id, parsed.resources, display)

    secrets: list[SecretMatch] = []
    for k, v in parsed.resources.items():
        # Filter values likely to be tokens: no whitespace, length in a
        # plausible token range. Skips filenames, sentences,
        # prefs-key-style strings.
        if 15 < len(v) < 150 and " " not in v:
            secrets.extend(match_secrets_with_decode(v, f"{display} resource '{k}'"))

    return secrets, fb


def _detect_service_account_secret(content: str, display: str) -> SecretMatch | None:
    """Detect a Google service-account JSON by its signature fields."""
    if '"type": "service_account"' not in content:
        return None
    if '"private_key"' not in content:
        return None
    return SecretMatch(
        type="GCP Service Account JSON",
        value=display,  # the value is the file location itself
        location=display,
    )


# ─── merge helpers ────────────────────────────────────────────────────────


def _attach_keys(scan: ScanZipResult, api_keys: set[str]) -> ScanZipResult:
    """Stamp the harvested AIza keys onto each Firebase config so the
    aggregation loop can promote them to ``additional_api_keys`` later.

    We do this on the per-entry result so the caller doesn't need a
    separate path through the loop.
    """
    if not api_keys:
        return scan
    for cfg in scan.firebase_configs:
        for k in api_keys:
            if k != cfg.api_key and k not in cfg.additional_api_keys:
                cfg.additional_api_keys.append(k)
    return scan


def _merge(result: ScanZipResult, scan: ScanZipResult, all_api_keys: set[str]) -> None:
    """Fold a single-entry scan into the per-zip aggregate."""
    for tech, loc in scan.techs.items():
        result.techs[tech] = loc
    result.secrets.extend(scan.secrets)
    result.firebase_configs.extend(scan.firebase_configs)
    for path, content in scan.saved_files.items():
        result.saved_files[path] = content
    for cfg in scan.firebase_configs:
        if cfg.api_key:
            all_api_keys.add(cfg.api_key)
        all_api_keys.update(cfg.additional_api_keys)


def _attach_additional_api_keys(configs: list[FirebaseConfig], all_keys: set[str]) -> None:
    """Final pass: every Firebase config gets the full union of AIza
    keys discovered anywhere in the APK as ``additional_api_keys``.
    """
    if not all_keys or not configs:
        return
    for cfg in configs:
        seen = {cfg.api_key, *cfg.additional_api_keys}
        for k in all_keys:
            if k and k not in seen:
                cfg.additional_api_keys.append(k)
                seen.add(k)


def _contains_confirmed_secret(secrets: list[SecretMatch]) -> bool:
    return any(not s.suspected for s in secrets)
