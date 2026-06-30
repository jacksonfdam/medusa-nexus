"""Library attribution — tell the developer whose code holds the bug.

The static engines emit findings with generic locations like
``"classes.dex"`` or ``"DEX strings"``. That's correct but useless when
the fix path depends on *which* code carries the smell. A hard-coded
``AIza`` key inside ``com/google/android/libraries/places/internal/zzcg``
is a build-config override problem; the same key under
``com/mcdonalds/mobileapp/Config`` is a "rotate + audit your own code"
problem. Different categories, different owners, different remediations.

This module attributes each finding to one of three buckets:

  * **first-party**          — the offending artefact lives under the
                                app's own package namespace.
  * **named third-party SDK** — the artefact lives under a known SDK's
                                package prefix (Google Places, Firebase,
                                Amplitude, Sentry, etc.).
  * **third-party (unknown)** — the artefact is outside the app's
                                namespace but doesn't match any prefix
                                in our registry. Worth investigating
                                manually.

Attribution runs after the chain correlator in the orchestrator's
intelligence phase. It uses :mod:`workspace_locator` to grep the
project's decompiled trees for each finding's evidence-fingerprint
(e.g. an ``AIza`` key extracted from the evidence text), then maps the
file paths to owners via :data:`KNOWN_SDK_PREFIXES`.

The cost is bounded: only findings whose evidence carries a
secret-shaped pattern (regex match against the standard credential
prefixes) trigger a workspace walk. A typical APK ingest adds <500ms.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mnexus.intelligence.workspace_locator import LocatorHit, find_in_workspace
from mnexus.models.finding import Finding


# ─── SDK registry ──────────────────────────────────────────────────────


# Paths use ``/`` separators because that's the form the workspace
# locator returns (``Path.relative_to(workspace).as_posix()``).
# Order matters — more specific prefixes must come BEFORE the more
# general ones so the longest match wins (e.g. ``com/google/firebase``
# must precede a hypothetical ``com/google`` catch-all).
KNOWN_SDK_PREFIXES: list[tuple[str, str, str]] = [
    # (path_prefix_under_jadx_or_smali, sdk_name, category)
    # ─── Google ecosystem ─────────────────────────────────────────
    ("com/google/firebase",                 "Firebase",                "analytics"),
    ("com/google/android/libraries/places", "Google Places SDK",       "maps"),
    ("com/google/android/libraries/maps",   "Google Maps SDK",         "maps"),
    ("com/google/android/gms",              "Google Play Services",    "auth"),
    ("com/google/android/play",             "Google Play Core",        "core"),
    ("com/google/mlkit",                    "Google ML Kit",           "ml"),
    ("com/google/ads",                      "Google AdMob",            "ads"),
    ("com/google/android/gms/ads",          "Google AdMob",            "ads"),
    # ─── Meta / Facebook ──────────────────────────────────────────
    ("com/facebook/login",                  "Facebook Login SDK",      "auth"),
    ("com/facebook/share",                  "Facebook Share SDK",      "social"),
    ("com/facebook/internal",               "Facebook Core SDK",       "core"),
    ("com/facebook",                        "Facebook SDK",            "social"),
    # ─── Analytics + product ──────────────────────────────────────
    ("com/amplitude",                       "Amplitude",               "analytics"),
    ("com/mixpanel",                        "Mixpanel",                "analytics"),
    ("io/segment",                          "Segment",                 "analytics"),
    ("com/segment",                         "Segment",                 "analytics"),
    ("com/heap",                            "Heap",                    "analytics"),
    ("com/appsflyer",                       "AppsFlyer",               "attribution"),
    ("com/adjust",                          "Adjust",                  "attribution"),
    ("com/branch",                          "Branch.io",               "attribution"),
    # ─── Push + messaging ─────────────────────────────────────────
    ("com/onesignal",                       "OneSignal",               "push"),
    ("com/urbanairship",                    "Urban Airship",           "push"),
    ("com/braze",                           "Braze",                   "engagement"),
    ("com/appboy",                          "Braze (legacy)",          "engagement"),
    # ─── Crash + monitoring ───────────────────────────────────────
    ("io/sentry",                           "Sentry",                  "crash"),
    ("com/datadog",                         "Datadog",                 "monitoring"),
    ("io/datadog",                          "Datadog",                 "monitoring"),
    ("com/newrelic",                        "New Relic",               "monitoring"),
    ("com/bugsnag",                         "Bugsnag",                 "crash"),
    ("com/crashlytics",                     "Firebase Crashlytics",    "crash"),
    ("com/instabug",                        "Instabug",                "feedback"),
    # ─── Payments + commerce ──────────────────────────────────────
    ("com/stripe",                          "Stripe SDK",              "payments"),
    ("com/paypal",                          "PayPal SDK",              "payments"),
    ("com/braintreepayments",               "Braintree",               "payments"),
    ("com/squareup",                        "Square SDK",              "payments"),
    # ─── Auth + identity ──────────────────────────────────────────
    ("com/auth0",                           "Auth0",                   "auth"),
    ("io/keycloak",                         "Keycloak",                "auth"),
    ("com/okta",                            "Okta",                    "auth"),
    ("com/microsoft/identity",              "Microsoft Identity",      "auth"),
    # ─── Maps + location ──────────────────────────────────────────
    ("com/mapbox",                          "Mapbox",                  "maps"),
    ("com/here/sdk",                        "HERE Maps",               "maps"),
    # ─── Networking + serialization ───────────────────────────────
    ("com/squareup/okhttp3",                "OkHttp",                  "network"),
    ("retrofit2",                           "Retrofit",                "network"),
    ("com/squareup/retrofit2",              "Retrofit",                "network"),
    ("com/squareup/moshi",                  "Moshi",                   "serialization"),
    ("com/google/gson",                     "Gson",                    "serialization"),
    # ─── Imaging + media ──────────────────────────────────────────
    ("com/bumptech/glide",                  "Glide",                   "imaging"),
    ("com/squareup/picasso",                "Picasso",                 "imaging"),
    ("com/airbnb/lottie",                   "Lottie",                  "imaging"),
    # ─── Anti-fraud / device intel ────────────────────────────────
    ("com/iovation",                        "Iovation",                "fraud"),
    ("com/threatmetrix",                    "ThreatMetrix",            "fraud"),
    ("com/incognia",                        "Incognia",                "fraud"),
    # ─── Communication / collab ───────────────────────────────────
    ("com/slack",                           "Slack SDK",               "comms"),
    ("com/twilio",                          "Twilio SDK",              "comms"),
    ("com/agora",                           "Agora",                   "rtc"),
    ("io/agora",                            "Agora",                   "rtc"),
    # ─── Apple equivalents (in case of cross-platform Kotlin Multiplatform) ─
    ("io/intercom",                         "Intercom",                "support"),
    ("com/zendesk",                         "Zendesk",                 "support"),
]


# ─── Key-pattern extractor ─────────────────────────────────────────────


# Patterns that look "secret-ish" — when one matches inside a finding's
# evidence text, we treat it as a fingerprint worth grepping the
# workspace for. Cheap regex sweep, runs once per finding.
_KEY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),                            # Google API
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),                       # AWS access key
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{20,}\b"),             # Stripe secret
    re.compile(r"\brk_(?:live|test)_[A-Za-z0-9]{20,}\b"),             # Stripe restricted
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                    # Slack token
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),                          # GitHub personal
    re.compile(r"\bgho_[A-Za-z0-9]{30,}\b"),                          # GitHub OAuth
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"\bAC[a-f0-9]{32}\b"),                                # Twilio
    re.compile(r"\bnpm_[A-Za-z0-9]{32,}\b"),                          # NPM token
    re.compile(r"\bpat_[A-Za-z0-9]{30,}\b"),                          # Personal access (generic)
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),                # PEM
]


def _extract_fingerprints(evidence: str) -> list[str]:
    """Return every key-shaped substring from ``evidence``. Empty = skip."""
    if not evidence:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for pat in _KEY_PATTERNS:
        for m in pat.finditer(evidence):
            value = m.group(0)
            if value not in seen:
                seen.add(value)
                out.append(value)
    return out


# ─── Path → owner mapping ──────────────────────────────────────────────


@dataclass(frozen=True)
class AttributionResult:
    """Outcome of attributing one finding."""

    attributed_to: str | None
    confidence: str           # "high" | "medium" | "low"
    sdk_category: str | None
    paths: list[str]


def _normalise_path_for_match(path: str) -> str:
    """Strip the workspace-tree prefix so we can match SDK prefixes directly.

    Locator returns paths like ``jadx/sources/com/google/.../zzcg.java``
    or ``apktool/smali_classes2/com/google/.../zzcg.smali`` or, in the
    PlayIntel case, ``secrets/<dotted.package>/com/google/.../Foo.java``.
    We want to match against the slash-delimited java package, so we
    strip everything before the package-root segment.
    """
    # Common root prefixes the locator emits.
    for marker in ("jadx/sources/", "apktool/smali_classes2/",
                   "apktool/smali_classes3/", "apktool/smali_classes4/",
                   "apktool/smali/", "apktool-manifest/", "secrets/"):
        idx = path.find(marker)
        if idx >= 0:
            tail = path[idx + len(marker):]
            # Under secrets/ the next directory is the package name with
            # dots (e.g. ``com.example.app/``) — strip that so we're back
            # at the slash-delimited package root the SDK prefixes match.
            if marker == "secrets/" and "/" in tail:
                first, rest = tail.split("/", 1)
                if "." in first:
                    tail = rest
            return tail
    return path


def _attribute_path(file_path: str, app_package: str) -> tuple[str, str, str]:
    """Map a single hit's file path to (owner, confidence, category).

    Returns ``(attributed_to, confidence, sdk_category)``.
    """
    normalised = _normalise_path_for_match(file_path)
    app_prefix = app_package.replace(".", "/") + "/" if app_package else ""

    # 1. App's own namespace wins — first-party.
    if app_prefix and normalised.startswith(app_prefix):
        return ("first-party", "high", "app-code")

    # 2. Match the longest registered SDK prefix.
    best: tuple[str, str, str] | None = None
    best_len = 0
    for prefix, name, category in KNOWN_SDK_PREFIXES:
        if normalised.startswith(prefix + "/") or normalised == prefix:
            if len(prefix) > best_len:
                best = (name, "high", category)
                best_len = len(prefix)
    if best:
        return best

    # 3. Fallback — outside the app's namespace, no SDK match. Worth
    #    flagging because some private bundled libs may still be the
    #    real owner; the analyst should review.
    return ("third-party (unknown)", "medium", None)


def attribute_finding(
    finding: Finding,
    *,
    workspace_dir: Path,
    project_id: str,
    app_package: str,
) -> AttributionResult | None:
    """Try to attribute one finding to an SDK or first-party code.

    Returns ``None`` when the finding has no actionable fingerprint
    (e.g. a manifest-level finding like ``debuggable=true`` — that's
    a build-config issue, not a library-attribution one).
    """
    fingerprints = _extract_fingerprints(finding.evidence)
    if not fingerprints:
        return None

    # Use the most distinctive fingerprint (the longest one) to keep
    # the grep tight. Multiple fingerprints would multiply work for
    # little extra information.
    fingerprints.sort(key=len, reverse=True)
    primary = fingerprints[0]

    try:
        hits = find_in_workspace(
            workspace_dir=workspace_dir,
            project_id=project_id,
            pattern=primary,
            regex=False,
            case_insensitive=False,
            max_results=30,
            package_name=app_package,
        )
    except Exception:
        return None

    if not hits:
        # Fingerprint exists in evidence but not on disk — could be a
        # synthetic evidence string or the workspace was wiped. Report
        # low-confidence unknown.
        return AttributionResult(
            attributed_to="third-party (unknown)",
            confidence="low",
            sdk_category=None,
            paths=[],
        )

    # Tally owners across the hits — most-common wins, with confidence
    # gated on consensus.
    owners: Counter[str] = Counter()
    category_by_owner: dict[str, str | None] = {}
    for hit in hits:
        owner, _, category = _attribute_path(hit.file, app_package)
        owners[owner] += 1
        category_by_owner.setdefault(owner, category)

    top_owner, top_count = owners.most_common(1)[0]
    total = sum(owners.values())
    share = top_count / total if total else 0
    if share >= 0.8:
        confidence = "high"
    elif share >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"

    return AttributionResult(
        attributed_to=top_owner,
        confidence=confidence,
        sdk_category=category_by_owner.get(top_owner),
        paths=[h.file for h in hits[:5]],
    )


# ─── public entry point ───────────────────────────────────────────────


def attribute_findings(
    findings: Iterable[Finding],
    *,
    workspace_dir: Path,
    project_id: str,
    app_package: str,
) -> None:
    """Walk every finding, attribute in place. Mutates the findings."""
    for finding in findings:
        result = attribute_finding(
            finding,
            workspace_dir=workspace_dir,
            project_id=project_id,
            app_package=app_package,
        )
        if result is None:
            continue
        finding.attributed_to = result.attributed_to
        finding.attribution_confidence = result.confidence
        finding.sdk_category = result.sdk_category
        finding.attribution_paths = result.paths
