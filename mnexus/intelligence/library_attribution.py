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

import os
import re
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mnexus.intelligence.workspace_locator import LocatorHit, find_in_workspace
from mnexus.models.finding import Finding


# ─── ripgrep fast path ────────────────────────────────────────────────


_RG_PATH = shutil.which("rg")


def _find_with_ripgrep(
    workspace_dir: Path,
    project_id: str,
    pattern: str,
    *,
    max_results: int,
    app_package: str,
) -> list[LocatorHit] | None:
    """Locate ``pattern`` via ``rg`` — orders of magnitude faster than the
    pure-Python locator on big release APKs. Returns ``None`` when ``rg``
    isn't on PATH so the caller can fall back. Returns ``[]`` when ``rg``
    completes but finds nothing.

    Restricts the search to the JVM-source subtrees (``jadx/``,
    ``apktool/``, ``apktool-manifest/``, optional ``secrets/<pkg>/``)
    and the extensions library attribution cares about. ``rg`` is
    fixed-string mode here — we only ever pass concrete fingerprints.
    """
    if not _RG_PATH:
        return None

    project_dir = workspace_dir / project_id
    candidates: list[tuple[str, Path]] = [
        ("jadx",           project_dir / "jadx"),
        ("apktool",        project_dir / "apktool"),
        ("manifest-cache", project_dir / "apktool-manifest"),
    ]
    if app_package:
        candidates.append(("secrets", workspace_dir / "secrets" / app_package))
    roots = [(name, p) for name, p in candidates if p.exists()]
    if not roots:
        return []

    cmd = [
        _RG_PATH,
        "--fixed-strings",
        "--max-count", "1",
        "--max-filesize", "2M",
        "--no-config", "--no-heading",
        "--no-messages",
        "--with-filename",
        "--line-number",
        "--type-add", "jvm:*.{java,kt,kts,smali}",
        "--type", "jvm",
        "--",
        pattern,
    ]
    cmd.extend(str(p) for _, p in roots)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    # rg returns 0 on matches, 1 on no-match, 2 on error.
    if proc.returncode not in (0, 1):
        return None

    hits: list[LocatorHit] = []
    name_for_root = sorted(roots, key=lambda r: len(str(r[1])), reverse=True)
    for raw in proc.stdout.splitlines():
        # Format: "<abs-path>:<line>:<text>"
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        abs_path, line_s, text = parts
        try:
            line_no = int(line_s)
        except ValueError:
            continue
        abs_path_p = Path(abs_path)
        # Pick the tree the hit belongs to (longest matching root wins).
        tree = "raw"
        for n, root in name_for_root:
            try:
                abs_path_p.relative_to(root)
                tree = n
                break
            except ValueError:
                continue
        try:
            rel = abs_path_p.relative_to(workspace_dir).as_posix()
        except ValueError:
            rel = abs_path_p.as_posix()
        hits.append(LocatorHit(
            file=rel, line=line_no,
            snippet=text.strip()[:160], tree=tree,
        ))
        if len(hits) >= max_results:
            break
    return hits


# ─── Bytes-based fast Python locator ──────────────────────────────────


_FAST_EXTENSIONS = frozenset({b".java", b".kt", b".kts", b".smali"})
_FAST_READ_CAP = 256 * 1024   # 256 KB — most Java sources are < 50 KB.
_FAST_TIMEOUT_S = 8.0         # per-fingerprint budget on very large trees.
_FAST_WORKERS = max(2, (os.cpu_count() or 2) - 1)


def _iter_source_files(root: Path) -> Iterable[Path]:
    """Yield every JVM-source file under ``root``. Uses ``os.scandir``
    so we skip building Path objects until strictly necessary — on a
    100k-file jadx tree that alone saves several seconds versus
    ``rglob('*')``.
    """
    stack: list[str] = [str(root)]
    while stack:
        current = stack.pop()
        try:
            it = os.scandir(current)
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        name = entry.name
                        dot = name.rfind(".")
                        if dot >= 0 and name[dot:].lower().encode() in _FAST_EXTENSIONS:
                            yield Path(entry.path)
                except OSError:
                    continue


def _find_fast_python(
    workspace_dir: Path,
    project_id: str,
    pattern: str,
    *,
    max_results: int,
    app_package: str,
) -> list[LocatorHit]:
    """Bytes-based, concurrent, timeout-bounded workspace grep.

    Trades the general workspace_locator's flexibility (regex,
    case-insensitive, snippet contexts) for raw speed — reads each
    file's first 256KB as bytes and does a ``bytes.find`` for the
    fingerprint. On a 100k-file release APK this beats the pure-Python
    locator by 5-10× because it skips utf-8 decode + line-number
    accounting + Path object allocation per file.

    Bounded by ``_FAST_TIMEOUT_S`` — if the walker hasn't returned by
    then, we short-circuit and let the caller flag the finding as
    ``third-party (unknown)`` with low confidence. Correctness under
    a busy laptop mattered more than exhaustive attribution here.
    """
    project_dir = workspace_dir / project_id
    candidates: list[Path] = [
        project_dir / "jadx",
        project_dir / "apktool",
        project_dir / "apktool-manifest",
    ]
    if app_package:
        candidates.append(workspace_dir / "secrets" / app_package)
    roots = [p for p in candidates if p.exists()]
    if not roots:
        return []

    needle = pattern.encode("utf-8", errors="replace")
    deadline = time.monotonic() + _FAST_TIMEOUT_S
    hits: list[LocatorHit] = []

    def _check(path: Path) -> LocatorHit | None:
        try:
            with open(path, "rb") as fh:
                blob = fh.read(_FAST_READ_CAP)
        except OSError:
            return None
        idx = blob.find(needle)
        if idx < 0:
            return None
        line_no = blob.count(b"\n", 0, idx) + 1
        try:
            rel = path.relative_to(workspace_dir).as_posix()
        except ValueError:
            rel = path.as_posix()
        tree = "raw"
        parts = rel.split("/", 3)
        if len(parts) >= 3:
            if parts[1] == "jadx":              tree = "jadx"
            elif parts[1] == "apktool":         tree = "apktool"
            elif parts[1] == "apktool-manifest":tree = "manifest-cache"
        elif rel.startswith("secrets/"):
            tree = "secrets"
        # Snippet: 80 chars around the hit, newlines squashed.
        a = max(0, idx - 60); b = min(len(blob), idx + len(needle) + 60)
        snippet = blob[a:b].decode("utf-8", errors="replace").replace("\n", " ⏎ ").strip()
        return LocatorHit(file=rel, line=line_no, snippet=snippet[:160], tree=tree)

    with ThreadPoolExecutor(max_workers=_FAST_WORKERS) as pool:
        # Feed a bounded window of work so we can abort quickly.
        pending = set()
        gen = (p for root in roots for p in _iter_source_files(root))
        for _ in range(_FAST_WORKERS * 4):
            try:
                pending.add(pool.submit(_check, next(gen)))
            except StopIteration:
                break

        while pending:
            if time.monotonic() > deadline:
                for fut in pending:
                    fut.cancel()
                break
            done, pending = _wait_first(pending, timeout=0.5)
            for fut in done:
                result = fut.result()
                if result is not None:
                    hits.append(result)
                    if len(hits) >= max_results:
                        for f in pending:
                            f.cancel()
                        return hits
                try:
                    pending.add(pool.submit(_check, next(gen)))
                except StopIteration:
                    pass
    return hits


def _wait_first(futures: set, *, timeout: float) -> tuple[set, set]:
    """Tiny helper — return (done, pending) after ``timeout`` seconds."""
    from concurrent.futures import wait, FIRST_COMPLETED
    done, pending = wait(futures, timeout=timeout, return_when=FIRST_COMPLETED)
    return done, pending


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


# Only walk source-bearing files for attribution. Resource bundles
# (.json / .xml / .properties) are usually not where SDK ownership
# lives, so dropping them cuts the locator's read budget by an order
# of magnitude on real release APKs.
_ATTRIBUTION_EXTENSIONS = (".java", ".kt", ".kts", ".smali")


def attribute_finding(
    finding: Finding,
    *,
    workspace_dir: Path,
    project_id: str,
    app_package: str,
    locator_cache: dict[str, list[LocatorHit]] | None = None,
) -> AttributionResult | None:
    """Try to attribute one finding to an SDK or first-party code.

    Returns ``None`` when the finding has no actionable fingerprint
    (e.g. a manifest-level finding like ``debuggable=true`` — that's
    a build-config issue, not a library-attribution one).

    ``locator_cache`` lets multiple findings that share the same
    hardcoded key reuse one workspace walk instead of N. The caller
    (``attribute_findings``) wires this in automatically.
    """
    fingerprints = _extract_fingerprints(finding.evidence)
    if not fingerprints:
        return None

    # Use the most distinctive fingerprint (the longest one) to keep
    # the grep tight. Multiple fingerprints would multiply work for
    # little extra information.
    fingerprints.sort(key=len, reverse=True)
    primary = fingerprints[0]

    if locator_cache is not None and primary in locator_cache:
        hits = locator_cache[primary]
    else:
        # Try in order of expected speed:
        # 1. ripgrep (Rust, mmap, parallel — 10-50x the pure-python
        #    walker on real release APKs). Returns None if ``rg``
        #    isn't on PATH or subprocess fails.
        # 2. Bytes-based fast locator with threadpool + timeout —
        #    beats the general workspace_locator by 5-10× because
        #    it skips utf-8 decode + snippet accounting per file.
        # 3. The generic workspace_locator (last resort).
        hits = _find_with_ripgrep(
            workspace_dir=workspace_dir,
            project_id=project_id,
            pattern=primary,
            max_results=10,
            app_package=app_package,
        )
        if hits is None:
            try:
                hits = _find_fast_python(
                    workspace_dir=workspace_dir,
                    project_id=project_id,
                    pattern=primary,
                    max_results=10,
                    app_package=app_package,
                )
            except Exception:
                hits = None
        if not hits:
            try:
                hits = find_in_workspace(
                    workspace_dir=workspace_dir,
                    project_id=project_id,
                    pattern=primary,
                    regex=False,
                    case_insensitive=False,
                    max_results=10,
                    extensions=_ATTRIBUTION_EXTENSIONS,
                    package_name=app_package,
                )
            except Exception:
                hits = []
        if locator_cache is not None:
            locator_cache[primary] = hits

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
    """Walk every finding, attribute in place. Mutates the findings.

    Findings that share the same hardcoded fingerprint (a common case
    when several detectors report the same ``AIza...`` key from
    different angles) share one workspace walk via ``locator_cache``.
    """
    locator_cache: dict[str, list[LocatorHit]] = {}
    for finding in findings:
        result = attribute_finding(
            finding,
            workspace_dir=workspace_dir,
            project_id=project_id,
            app_package=app_package,
            locator_cache=locator_cache,
        )
        if result is None:
            continue
        finding.attributed_to = result.attributed_to
        finding.attribution_confidence = result.confidence
        finding.sdk_category = result.sdk_category
        finding.attribution_paths = result.paths
