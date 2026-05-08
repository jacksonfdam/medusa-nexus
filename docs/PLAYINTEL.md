# PlayIntel — Mobile credential & Firebase reconnaissance

PlayIntel is a MedusaNexus engine that recovers backend identifiers and
embedded credentials from Android APKs, then runs a small set of
harmless active probes against any Firebase project it discovers. It is
a Python port of the internal Go scanner ``go-google-login``, integrated
as a first-class head of the hydra alongside `apktool`, `jadx`, `mobsf`,
`ghidra`, etc.

## What it does

Given **either** a local APK file or a Google Play package name, the
engine:

1. **Streams the APK** — issues HTTP `Range` requests for only the zip
   central directory plus the high-value entries
   (``resources.arsc``, ``google-services.json``, JS bundles, .NET
   assemblies, `.pem` files). On a 100 MB APK this transfers
   ~5–10 MB end-to-end.
2. **Parses the resource table** — a hand-rolled `resources.arsc`
   parser extracts every string resource (Firebase project ID,
   `google_api_key`, `firebase_database_url`, `gcm_defaultSenderId`,
   `default_web_client_id`, `google_app_id`, `google_storage_bucket`,
   plus thousands of unrelated strings used for entropy-filtered
   secret detection).
3. **Detects credentials** — runs a regex+entropy detector (~25
   confirmed patterns: OpenAI, Anthropic, AWS, Stripe, Slack, GitHub,
   FCM legacy server keys, PEM private keys, …; plus a separate
   "suspected" tier gated on Shannon entropy ≥ 3.0). AKIA / ASIA
   access-key IDs trigger a paired-secret search inside a 1024-byte
   window, with extra entropy and hex-only filters to drop SHA-1s.
   google-api-client SDK test-key fingerprints are filtered out.
4. **Probes server-side rules** (optional) — for each unique Firebase
   project ID, hits Realtime Database, Cloud Firestore, and Cloud
   Storage with anonymous requests. Reports public read/write
   misconfiguration. RTDB region-redirects are followed once with an
   anti-SSRF host allow-list. The write probe targets a dedicated
   `_scanner_probe.json` child key and self-cleans on success.
5. **Persists bearing files** — files containing a confirmed credential
   or a Firebase project ID are saved to
   `<workspace>/secrets/<package>/` so the analyst can re-inspect them
   offline.
6. **Emits findings** — translates everything into MedusaNexus
   `Finding` objects with appropriate CWE / OWASP-Mobile / MASVS tags,
   so the rest of the platform (UI, reports, hooks) renders them like
   any other engine output.

## Design

```
mnexus/playintel/
├── arsc.py                # AOSP resources.arsc parser (string-type entries)
├── secret_detector.py     # regex + entropy + AKIA-pair correlator
├── firebase_config.py     # google-services.json + ARSC → FirebaseConfig
├── scan_targets.py        # zip-entry whitelist
├── remote_zip.py          # HTTP Range zip reader + LocalZip adapter
├── zip_entry_scanner.py   # per-entry routing → ScanZipResult
├── scan_report.py         # thread-safe aggregator
├── firebase_probes.py     # RTDB / Firestore / Storage active probes
├── apk_source.py          # pluggable: LocalAPKSource | DirectURLSource | PlayBinarySource
└── analyzer.py            # high-level orchestration → AnalysisOutcome

mnexus/engines/play_intel_engine.py     # MedusaNexus engine wrapper
```

### Pluggable APK source

The analyzer never branches on where bytes come from. Three sources
implement the same protocol:

| Source              | Used for                                      | Notes |
|---------------------|-----------------------------------------------|-------|
| `LocalAPKSource`    | Any local `.apk` or `.xapk` file              | No network. Default for `ingest_apk` flow. |
| `DirectURLSource`   | Pre-resolved CDN URL + size + headers         | When another tool already did Play protocol. |
| `PlayBinarySource`  | Subprocess bridge to `poc-firebase-google`    | Full Play protocol via the Go reference binary; auth via `~/.config/apkeep/apkeep.ini`. |

A future `PlayProtocolSource` implementing the protocol natively in
Python is purely additive — same protocol, same downstream pipeline.

### Findings

Severities are tuned conservatively — they describe the credential's
blast radius, not whether the specific token is currently active:

| Class                       | Severity   |
|-----------------------------|------------|
| GCP Service Account JSON    | CRITICAL   |
| PEM private key             | CRITICAL   |
| RTDB / Firestore / Storage open to world | CRITICAL / HIGH |
| FCM Server Key, AWS Key Pair, Stripe live key, Slack/GitHub/SendGrid/Twilio token | HIGH |
| OneSignal, Vercel, HuggingFace tokens | MEDIUM |
| Generic `api_key=` / JWT (suspected tier) | MEDIUM |
| Firebase project identifiers (informational) | INFO |

Every CRITICAL / HIGH finding ships a code-level remediation block —
that's enforced at construction time by `Finding.model_validator`.

### What the engine does **not** do

- **Mint Firebase auth tokens.** The Go reference scanner can
  `signInAnonymously` / `signInWithIdp` to test "auth required" rules.
  That path requires a working anonymous-auth provider on the target
  project (or a leaked OAuth client secret) and is left to a future
  iteration.
- **Implement the Google Play protocol natively.** The
  `PlayBinarySource` shells out to the existing Go binary for the
  auth + GetDownloadInfo dance. Implementing the protobuf-based
  protocol in Python is a separate, sizeable piece of work.
- **Touch user data.** The RTDB write probe is the only mutating
  call, targets a dedicated child path, and self-cleans on success.
  Firestore and Storage probes are read-only.

## Usage

### CLI — interactive REPL (slash command)

```
🔱 nexus ❯ /play-scan com.example.app
```

Optional flags inside the REPL:

* `/play-scan <pkg> --apk <local-file>` — bypass Play and use a local APK.
* `/play-scan <pkg> --no-probes` — static-only scan (no outbound traffic).

### CLI — flat subcommand

```
mnexus play-scan com.example.app
mnexus play-scan com.example.app --apk ~/Downloads/target.apk
mnexus play-scan com.example.app --no-probes
```

### Web UI

Sidebar: **PLAY SCAN** (`#/play-scan`). Form takes a package name and
an "active probes" toggle; results render Firebase project IDs,
confirmed secrets, active-probe vulnerabilities, and the engine's
emitted findings.

### REST API

```
POST /v1/playintel/scan
Content-Type: application/json

{
  "package": "com.example.app",
  "apk_path": "/optional/local.apk",
  "run_active_probes": true
}
```

Response:

```json
{
  "package": "com.example.app",
  "source": "play-bridge",
  "firebase_projects": ["…"],
  "confirmed_secrets": [{"type": "OpenAI API Key", "location": "…"}],
  "suspected_secrets_count": 3,
  "vulnerabilities": ["Realtime Database public access: …"],
  "findings": [{"id": "FND-…", "title": "…", "severity": "high", "category": "…", "location": "…"}],
  "saved_files_dir": "/workspace/secrets/com.example.app"
}
```

### Programmatic

```python
from pathlib import Path
from mnexus.config import NexusConfig
from mnexus.engines.play_intel_engine import PlayIntelEngine
from mnexus.playintel.apk_source import LocalAPKSource, PlayBinarySource

config = NexusConfig.from_env()
engine = PlayIntelEngine(config)

# Local file:
source = LocalAPKSource(Path("./target.apk"))
outcome, findings = await engine.analyze_package(
    "com.example.app",
    source=source,
    workspace=config.workspace,
    run_active_probes=False,
)

# Or stream from Play (requires the Go bridge binary on PATH):
source = PlayBinarySource()
outcome, findings = await engine.analyze_package(
    "com.example.app",
    source=source,
    workspace=config.workspace,
    run_active_probes=True,
)

print(outcome.report.confirmed_secrets())
print(outcome.report.vulnerabilities)
```

## Operating notes

### Severity framing — `AIza*` keys are not secrets

`AIzaSy*` API keys are **project identifiers** — Firebase / Maps SDKs
are designed to ship them inside client APKs. Their disclosure is
unavoidable; what determines actual risk is server-side configuration:

1. **API-key application restrictions** — Android package + SHA-1
   signing certificate, plus a whitelist of allowed Google APIs.
2. **Firebase Security Rules** — for Realtime Database, Firestore,
   Cloud Storage.
3. **Firebase App Check** — Play Integrity attestation, enforced on
   Firestore / RTDB / Storage / Cloud Functions.

The engine reflects this: a recovered `FirebaseConfig` produces an
**INFO** finding (informational, no remediation required). The
**CRITICAL / HIGH** findings come from the active probes — they
demonstrate that the rules don't actually keep an anonymous attacker
out.

### Test data policy

All tests use synthetic inputs. The ARSC test suite includes a small
encoder helper (`tests/playintel/test_arsc.py::_build_minimal_arsc`)
that constructs a valid resource-table blob in memory. The analyzer
integration test builds a tiny synthetic APK with a fabricated
`google-services.json` and a fake credential. **Do not commit
real-world target data** — recovered credentials, customer-data
fixtures, or named-app case studies belong in one-off deliverables, not
in the repo.

### Adding a new credential pattern

Edit `mnexus/playintel/secret_detector.py`:

* Add to `SECRET_PATTERNS` if the pattern is vendor-specific and
  rarely produces false positives. The pattern must match the issuer's
  published format prefix (`sk_live_`, `ghp_`, etc.).
* Add to `SUSPECTED_SECRET_PATTERNS` if it's a generic `key=value`
  shape. It will only fire when no confirmed pattern matched the same
  value AND Shannon entropy ≥ `MIN_SECRET_ENTROPY` (3.0).
* Set the severity in
  `mnexus/engines/play_intel_engine.py::_SECRET_SEVERITY`. Default is
  MEDIUM; reach for HIGH or CRITICAL only when the credential class
  unlocks real customer data.

Add a test under `tests/playintel/test_secret_detector.py` that
exercises both the positive case and a near-miss that should not
trigger.

### Performance characteristics

* Range-fetched APK scan: dominated by HTTP round-trip latency, not
  bandwidth. `RemoteZip.prefetch_entries` issues one ranged GET per
  whitelisted entry to avoid the cold-cache pattern of
  `zipfile`-internal small reads.
* `resources.arsc` parsing: linear in the size of the global string
  pool. McDonald's-class APKs (~15 MB arsc, 6k+ string resources)
  parse in tens of milliseconds.
* Active probes: 3 HTTP round-trips per Firebase project (RTDB read,
  RTDB write+cleanup, Firestore listCollectionIds, Storage listObjects),
  bounded by `httpx.Client(timeout=10s)`.

## Files of interest

* `mnexus/playintel/arsc.py` — resources.arsc parser; references AOSP
  `frameworks/base/libs/androidfw/include/androidfw/ResourceTypes.h`.
* `mnexus/playintel/secret_detector.py` — pattern catalog + entropy
  filter + AKIA-pair correlator.
* `mnexus/playintel/firebase_probes.py` — active-probe implementations,
  including the RTDB region-redirect handling and SSRF allow-list.
* `mnexus/engines/play_intel_engine.py` — engine wrapper; severity
  table; finding emission.
* `tests/playintel/test_arsc.py` — synthetic ARSC encoder used as a
  test fixture.
