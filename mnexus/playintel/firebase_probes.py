"""Active probes for Firebase services.

Once a :class:`FirebaseConfig` is recovered from the APK, the analyzer
runs a small set of harmless reconnaissance probes against the
discovered project to see whether server-side rules actually keep an
anonymous attacker out:

* :func:`check_realtime_db` — read a small document at the database
  root and write a probe doc under a dedicated child path (cleaned up
  on success). Region redirects are followed once.
* :func:`check_firestore` — list documents in the default database via
  the public REST endpoint.
* :func:`check_storage_bucket` — list objects in the bucket via the
  Firebase Storage REST endpoint.

All probes are read-mostly; the RTDB write probe targets a dedicated
``_scanner_probe.json`` child key to avoid clobbering any real data,
and is followed by a DELETE on success. The Firestore and Storage
probes never write.

A successful "public read/write" finding is the gold-standard signal
that the project's security rules are misconfigured. A "denied"
response is the desired state — the rules did their job.

These probes do *not* attempt to mint Firebase auth tokens. The Go
reference does, via Identity Toolkit ``signInAnonymously`` /
``signInWithIdp``; that path is left to a follow-up because it requires
either a working anonymous-auth provider or a leaked OAuth client
secret. If the analyzer finds an OAuth client secret elsewhere in the
APK, that capability becomes worth adding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

# Firebase RTDB region-redirect handling. A request to an old-style
# `<project>.firebaseio.com` URL on a project that's been migrated to a
# regional database returns 404 with a JSON body containing the
# correct URL. We follow it once, but only to a known Firebase host
# (anti-SSRF — a malicious server can't redirect us anywhere else).
_RTDB_CORRECT_URL_RE = re.compile(r'"correctUrl"\s*:\s*"(https://[^"]+)"')
_RTDB_REDIRECT_FALLBACK_REGEXES = (
    re.compile(r"https://[a-zA-Z0-9-]+-default-rtdb\.[a-zA-Z0-9-]+\.firebasedatabase\.app"),
    re.compile(r"https://[a-zA-Z0-9-]+\.firebasedatabase\.app"),
)
_RTDB_ALLOWED_REDIRECT_HOSTS = (".firebaseio.com", ".firebasedatabase.app")
_RTDB_MAX_REDIRECT_DEPTH = 3
_RTDB_PROBE_WRITE_VALUE = '{"probe":true}'
_RTDB_PROBE_WRITE_PATH = "_scanner_probe"


@dataclass(slots=True)
class RealtimeDBResult:
    """Outcome of probing one RTDB URL."""

    db_url: str
    public_read: bool = False
    public_write: bool = False
    error: str = ""

    @property
    def vulnerable(self) -> bool:
        return self.public_read or self.public_write


@dataclass(slots=True)
class FirestoreResult:
    """Outcome of probing one Firestore project."""

    project_id: str
    public_read: bool = False
    sample_document_count: int = 0
    error: str = ""

    @property
    def vulnerable(self) -> bool:
        return self.public_read


@dataclass(slots=True)
class StorageResult:
    """Outcome of probing one Cloud Storage bucket."""

    bucket: str
    public_listing: bool = False
    object_count: int = 0
    error: str = ""

    @property
    def vulnerable(self) -> bool:
        return self.public_listing


# ─── Realtime Database ────────────────────────────────────────────────────


def check_realtime_db(
    db_url: str,
    *,
    client: httpx.Client | None = None,
    timeout_s: float = 10.0,
) -> RealtimeDBResult:
    """Probe one Firebase Realtime Database for anonymous read/write.

    Returns a :class:`RealtimeDBResult` describing the outcome.
    Region-redirects are followed once when the initial probe is met
    with the documented "wrong region" 404 + ``correctUrl`` body.
    """
    normalized = _normalize_rtdb_url(db_url)
    if not normalized:
        return RealtimeDBResult(db_url=db_url, error="missing database URL")

    own_client = client is None
    client = client or httpx.Client(timeout=timeout_s, follow_redirects=False)

    try:
        result = _probe_rtdb_with_redirects(client, normalized, depth=0)
    finally:
        if own_client:
            client.close()
    result.db_url = db_url
    return result


def _probe_rtdb_with_redirects(
    client: httpx.Client, base_url: str, *, depth: int
) -> RealtimeDBResult:
    if depth > _RTDB_MAX_REDIRECT_DEPTH:
        return RealtimeDBResult(
            db_url=base_url,
            error=f"redirect depth exceeded (max {_RTDB_MAX_REDIRECT_DEPTH})",
        )

    read = _probe_rtdb_read(client, base_url)
    write = _probe_rtdb_write(client, base_url)

    if read.public_read or write.public_write:
        return RealtimeDBResult(
            db_url=base_url,
            public_read=read.public_read,
            public_write=write.public_write,
            error=_combine(read.error, write.error),
        )

    redirect = read.redirect or write.redirect
    if redirect and _is_allowed_rtdb_redirect(redirect):
        next_url = redirect.rstrip("/") + "/.json"
        return _probe_rtdb_with_redirects(client, next_url, depth=depth + 1)

    return RealtimeDBResult(db_url=base_url, error=_combine(read.error, write.error))


@dataclass(slots=True)
class _RtdbProbeOutcome:
    public_read: bool = False
    public_write: bool = False
    redirect: str = ""
    error: str = ""


def _probe_rtdb_read(client: httpx.Client, url: str) -> _RtdbProbeOutcome:
    try:
        resp = client.get(url)
    except httpx.HTTPError as e:
        return _RtdbProbeOutcome(error=f"read error: {e}")
    body = resp.read()[:4096] if resp.status_code == 404 else b""
    return _classify_rtdb_read(resp.status_code, body)


def _classify_rtdb_read(status: int, body: bytes) -> _RtdbProbeOutcome:
    out = _RtdbProbeOutcome()
    if status == 200:
        # An empty database returns "null". Anything beyond that means
        # there's data we could read.
        out.public_read = True
        return out
    if status == 403:
        out.error = "permission denied (secured)"
        return out
    if status == 423:
        out.error = "database deactivated (HTTP 423)"
        return out
    if status == 404:
        out.redirect = _extract_rtdb_redirect(body)
        out.error = f"HTTP {status}"
        return out
    out.error = f"HTTP {status}"
    return out


def _probe_rtdb_write(client: httpx.Client, base_url: str) -> _RtdbProbeOutcome:
    write_url = _probe_write_url(base_url)
    try:
        resp = client.put(write_url, content=_RTDB_PROBE_WRITE_VALUE.encode("utf-8"))
    except httpx.HTTPError as e:
        return _RtdbProbeOutcome(error=f"write error: {e}")
    body = resp.read()[:4096] if resp.status_code == 404 else b""
    out = _classify_rtdb_write(resp.status_code, body)
    if out.public_write:
        # Best-effort cleanup so we don't leave probe data behind.
        try:
            client.delete(write_url)
        except httpx.HTTPError:
            pass
    return out


def _classify_rtdb_write(status: int, body: bytes) -> _RtdbProbeOutcome:
    out = _RtdbProbeOutcome()
    if status == 200:
        out.public_write = True
        return out
    if status == 403:
        out.error = "permission denied (secured)"
        return out
    if status == 423:
        out.error = "database deactivated (HTTP 423)"
        return out
    if status == 404:
        out.redirect = _extract_rtdb_redirect(body)
        out.error = f"HTTP {status}"
        return out
    out.error = f"HTTP {status}"
    return out


def _normalize_rtdb_url(url: str) -> str:
    trimmed = url.strip()
    if not trimmed:
        return ""
    if trimmed.endswith("/.json") or trimmed.endswith(".json"):
        return trimmed
    if trimmed.endswith("/"):
        return trimmed + ".json"
    return trimmed + "/.json"


def _probe_write_url(base_url: str) -> str:
    """Derive ``…/_scanner_probe.json`` from a ``…/.json`` base URL."""
    trimmed = base_url
    for suffix in ("/.json", ".json"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
            break
    trimmed = trimmed.rstrip("/")
    return f"{trimmed}/{_RTDB_PROBE_WRITE_PATH}.json"


def _is_allowed_rtdb_redirect(url: str) -> bool:
    if not url.startswith("https://"):
        return False
    host = url.split("/", 3)[2].lower()
    return any(host.endswith(suffix) for suffix in _RTDB_ALLOWED_REDIRECT_HOSTS)


def _extract_rtdb_redirect(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    m = _RTDB_CORRECT_URL_RE.search(text)
    if m:
        return m.group(1)
    for re_pat in _RTDB_REDIRECT_FALLBACK_REGEXES:
        m = re_pat.search(text)
        if m:
            return m.group(0)
    return ""


def _combine(a: str, b: str) -> str:
    if a and b:
        return f"read: {a}; write: {b}"
    return a or b


# ─── Cloud Firestore ──────────────────────────────────────────────────────


def check_firestore(
    project_id: str,
    *,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    timeout_s: float = 10.0,
) -> FirestoreResult:
    """Probe one Cloud Firestore database for anonymous list-documents.

    Hits the public REST endpoint at ``runQuery`` for the default
    database. A 200 with at least one document means the rules accept
    unauthenticated reads. The API key, if provided, is appended as
    a query string — useful when the rules are gated on key presence
    rather than on auth.
    """
    own_client = client is None
    client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)

    url = (
        f"https://firestore.googleapis.com/v1/projects/{project_id}/"
        "databases/(default)/documents:listCollectionIds"
    )
    params: dict[str, str] = {}
    if api_key:
        params["key"] = api_key

    try:
        resp = client.post(url, json={}, params=params)
    except httpx.HTTPError as e:
        if own_client:
            client.close()
        return FirestoreResult(project_id=project_id, error=f"request error: {e}")

    try:
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            ids = payload.get("collectionIds") if isinstance(payload, dict) else None
            count = len(ids) if isinstance(ids, list) else 0
            return FirestoreResult(
                project_id=project_id,
                public_read=count > 0,
                sample_document_count=count,
            )
        if resp.status_code in (401, 403):
            return FirestoreResult(project_id=project_id, error="permission denied")
        return FirestoreResult(
            project_id=project_id, error=f"unexpected status {resp.status_code}"
        )
    finally:
        if own_client:
            client.close()


# ─── Cloud Storage ────────────────────────────────────────────────────────


def check_storage_bucket(
    bucket: str,
    *,
    client: httpx.Client | None = None,
    timeout_s: float = 10.0,
) -> StorageResult:
    """Probe one Firebase Cloud Storage bucket for public listing.

    Uses the Firebase Storage REST endpoint. ``allUsers: read`` rules
    return a JSON listing of objects; secured buckets return 403 or
    a Google-Cloud error envelope.
    """
    own_client = client is None
    client = client or httpx.Client(timeout=timeout_s, follow_redirects=True)

    url = f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o"
    try:
        resp = client.get(url, params={"maxResults": "10"})
    except httpx.HTTPError as e:
        if own_client:
            client.close()
        return StorageResult(bucket=bucket, error=f"request error: {e}")

    try:
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
            items = payload.get("items") if isinstance(payload, dict) else None
            count = len(items) if isinstance(items, list) else 0
            return StorageResult(
                bucket=bucket,
                public_listing=count > 0,
                object_count=count,
            )
        if resp.status_code in (401, 403):
            return StorageResult(bucket=bucket, error="permission denied")
        return StorageResult(bucket=bucket, error=f"unexpected status {resp.status_code}")
    finally:
        if own_client:
            client.close()
