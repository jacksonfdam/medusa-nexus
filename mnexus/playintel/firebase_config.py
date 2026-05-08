"""Firebase configuration recovery from APK resources.

An Android Firebase project is identified by a small bundle of values:
the project ID, an API key, the mobile SDK app ID, the realtime DB URL,
the storage bucket, and (optionally) the OAuth web client ID. These
values are not secrets — they are *identifiers* the Firebase SDKs are
designed to ship inside the client APK — but they identify exactly which
Google Cloud project to attack, so recovering them is the first step of
any active probe.

There are two carriers for these values:

1. ``google-services.json`` (or its variants ``-desktop`` /
   ``-debug``) — a structured JSON document the Firebase Gradle plugin
   can drop into ``assets/`` or build-config sources. Parsed by
   :func:`parse_google_services_json`.
2. The compiled resource table (``resources.arsc``) — the standard
   plugin path. Each Firebase value lands as a string resource keyed by
   ``project_id``, ``google_api_key`` etc. Parsed via the ARSC parser
   and mapped here by :func:`firebase_config_from_resources`.

In real-world APKs option 2 is overwhelmingly more common; option 1
shows up mostly in cross-platform builds (React Native, Flutter, Unity)
that ship the JSON as an asset.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# Regexes used as a last-ditch fallback when neither the structured JSON
# nor the ARSC mapping yielded a project ID. These match how the Gradle
# plugin emits the resource strings into XML or JSON.
_FIREBASE_PROJECT_ID_REGEXES: list[re.Pattern[str]] = [
    re.compile(r'"project_id":\s*"([^"]+)"'),
    re.compile(r'<string name="project_id"[^>]*>([^<]+)</string>'),
    re.compile(r'<string name="com\.google\.firebase\.project_id"[^>]*>([^<]+)</string>'),
]

# Google API keys all share the AIza-prefixed shape. These are not
# secrets in the credential sense — they're per-project identifiers
# whose security relies on application-restriction policy in GCP.
GOOGLE_API_KEY_RE = re.compile(r"AIza[a-zA-Z0-9_-]{35}")

# Map of substring (case-folded resource key) → field name on
# :class:`FirebaseConfig`. Mapping keeps the loop in
# :func:`firebase_config_from_resources` flat and obvious.
_RESOURCE_KEY_TO_FIELD: tuple[tuple[str, str], ...] = (
    ("firebase_database_url", "database_url"),
    ("firebase_url", "database_url"),
    ("google_api_key", "api_key"),
    ("google_app_id", "app_id"),
    ("google_storage_bucket", "storage_bucket"),
    ("gcm_defaultsenderid", "sender_id"),
    ("default_web_client_id", "web_client_id"),
)


@dataclass(slots=True)
class FirebaseConfig:
    """One Firebase project's identifying configuration.

    Every field except ``project_id`` is optional — APKs often ship a
    subset (e.g. only the API key + app ID, with the database URL
    derived at runtime by appending ``-default-rtdb.firebaseio.com``).

    ``additional_api_keys`` collects any extra ``AIza*`` strings found
    in the same APK. They aren't necessarily bound to *this* project —
    apps with multiple Google services often ship one key per service —
    but they're worth validating as part of the same scan.
    """

    project_id: str = ""
    database_url: str = ""
    api_key: str = ""
    app_id: str = ""
    storage_bucket: str = ""
    sender_id: str = ""
    web_client_id: str = ""
    location: str = ""  # APK-relative path of the source file
    additional_api_keys: list[str] = field(default_factory=list)

    @property
    def realtime_db_candidates(self) -> list[str]:
        """All RTDB URLs worth probing.

        Returns the explicit ``database_url`` if set, plus the two
        derived defaults Firebase uses (``<project>.firebaseio.com``
        for older projects and ``<project>-default-rtdb.firebaseio.com``
        for newer ones). De-duplicated, in probe-priority order.
        """
        urls: list[str] = []
        if self.database_url:
            urls.append(self.database_url)
        if self.project_id:
            urls.append(f"https://{self.project_id}.firebaseio.com")
            urls.append(f"https://{self.project_id}-default-rtdb.firebaseio.com")
        seen: set[str] = set()
        unique: list[str] = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                unique.append(u)
        return unique


# ─── google-services.json parser ──────────────────────────────────────────


def is_google_services_json(lower_name: str) -> bool:
    """Match ``google-services.json`` and its variants (``-desktop``,
    ``-debug``…). Receives the lower-cased path; expected to be cheap.
    """
    base = os.path.basename(lower_name)
    return base.startswith("google-services") and base.endswith(".json")


def parse_google_services_json(data: bytes, location: str) -> FirebaseConfig | None:
    """Deserialize a ``google-services.json`` file into a
    :class:`FirebaseConfig`.

    The schema is documented at
    https://developers.google.com/android/guides/google-services-plugin
    — the relevant fields are::

        project_info.project_id
        project_info.firebase_url
        project_info.storage_bucket
        client[].client_info.mobilesdk_app_id
        client[].api_key[].current_key
        client[].oauth_client[]   (client_type 3 = web)

    Returns ``None`` if parsing fails or the project ID is missing —
    a config without a project ID is useless for the active probes.
    """
    try:
        doc = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    project_info = doc.get("project_info") or {}
    project_id = project_info.get("project_id") or ""
    if not project_id:
        return None

    cfg = FirebaseConfig(
        project_id=project_id,
        database_url=project_info.get("firebase_url") or "",
        storage_bucket=project_info.get("storage_bucket") or "",
        sender_id=project_info.get("project_number") or "",
        location=location,
    )

    clients = doc.get("client") or []
    seen_keys: set[str] = set()
    for i, client in enumerate(clients):
        client_info = client.get("client_info") or {}
        api_keys = client.get("api_key") or []

        if i == 0:
            cfg.app_id = client_info.get("mobilesdk_app_id") or ""
            if api_keys:
                cfg.api_key = api_keys[0].get("current_key") or ""
                if cfg.api_key:
                    seen_keys.add(cfg.api_key)
            for oc in client.get("oauth_client") or []:
                # client_type 3 is the web OAuth client. That's what's
                # consumed by Identity Toolkit's signInWithIdp flow.
                if oc.get("client_type") == 3 and oc.get("client_id"):
                    cfg.web_client_id = oc["client_id"]
                    break
            # Extra keys on the first client.
            for ak in api_keys[1:]:
                k = ak.get("current_key") or ""
                if k and k not in seen_keys:
                    seen_keys.add(k)
                    cfg.additional_api_keys.append(k)
        else:
            # Subsequent clients: treat their keys as additional.
            for ak in api_keys:
                k = ak.get("current_key") or ""
                if k and k not in seen_keys:
                    seen_keys.add(k)
                    cfg.additional_api_keys.append(k)

    return cfg


# ─── Resource-table mapping ───────────────────────────────────────────────


def firebase_config_from_resources(
    project_id: str,
    resources: dict[str, str],
    location: str,
) -> FirebaseConfig:
    """Map a parsed resources.arsc dictionary into a :class:`FirebaseConfig`.

    The arsc parser produces ``key → value`` pairs where the keys are
    Android resource names (case as declared). Match each known field
    case-insensitively so this also works on resources that the
    Firebase SDK declares with mixed casing
    (``gcm_defaultSenderId``).
    """
    cfg = FirebaseConfig(project_id=project_id, location=location)
    for key, value in resources.items():
        lower = key.lower()
        for marker, field_name in _RESOURCE_KEY_TO_FIELD:
            if marker in lower:
                if not getattr(cfg, field_name):
                    setattr(cfg, field_name, value)
                break
    return cfg


def regex_fallback_project_ids(content: str, location: str) -> list[FirebaseConfig]:
    """Last-resort scan for ``project_id`` in arbitrary text content.

    Used when the structured parsers can't be applied (e.g. a custom
    XML config the Firebase plugin doesn't emit). Returns a
    :class:`FirebaseConfig` with only ``project_id`` populated for each
    distinct hit.
    """
    found: list[FirebaseConfig] = []
    seen: set[str] = set()
    for re_pat in _FIREBASE_PROJECT_ID_REGEXES:
        for m in re_pat.finditer(content):
            pid = m.group(1)
            if pid and pid not in seen:
                seen.add(pid)
                found.append(FirebaseConfig(project_id=pid, location=location))
    return found
