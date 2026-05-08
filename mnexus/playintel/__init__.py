"""playintel — Mobile credential/Firebase reconnaissance for Android APKs.

This package is a Python port of the Go scanner ``go-google-login``
(``github.com/jacksonmafra/go-google-login`` / internal). It provides:

1. A streaming APK reader that fetches only the bytes it needs over HTTP
   Range requests — no full-APK download to disk.
2. A format-aware ``resources.arsc`` parser that recovers the same
   ``key → value`` map the Android runtime uses, so we can pull Firebase
   project IDs, API keys, and other resource-table identifiers without
   relying on substring matching.
3. A regex + entropy secret detector covering ~25 cloud-provider token
   shapes (AWS, GitHub, Stripe, FCM legacy keys, PEM private keys, …) plus
   AKIA-pair correlation.
4. Active misconfiguration probes for Firebase Realtime Database, Cloud
   Firestore, and Cloud Storage that consume any recovered credentials and
   report whether the corresponding security rules actually keep an
   anonymous attacker out.

The package is consumed by :class:`mnexus.engines.play_intel_engine.PlayIntelEngine`,
which packages findings into ``Finding`` objects so the rest of the
MedusaNexus pipeline (UI, reports, hooks) can render them.

The hard work — the resource-table parser, the streaming reader, the
secret-pattern set — is in this package so it can be unit-tested in
isolation. The engine class only wires it into the platform.
"""

from mnexus.playintel.arsc import ParsedArsc, parse_arsc
from mnexus.playintel.firebase_config import FirebaseConfig, parse_google_services_json
from mnexus.playintel.scan_report import ScanReport, ScanZipResult
from mnexus.playintel.secret_detector import (
    SecretMatch,
    match_secrets,
    match_secrets_multiline,
    match_secrets_with_decode,
    shannon_entropy,
)

__all__ = [
    "FirebaseConfig",
    "ParsedArsc",
    "ScanReport",
    "ScanZipResult",
    "SecretMatch",
    "match_secrets",
    "match_secrets_multiline",
    "match_secrets_with_decode",
    "parse_arsc",
    "parse_google_services_json",
    "shannon_entropy",
]
