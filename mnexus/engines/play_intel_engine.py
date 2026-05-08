"""PlayIntelEngine — Firebase / GCP credential reconnaissance head.

This engine differs from the rest of the hydra in two ways:

1. It can ingest an APK *without* having it on disk first — given a
   package name and a working APK source (Google Play or otherwise),
   it streams just the bytes it needs over HTTP Range requests.
2. It runs *active probes* against any Firebase project it discovers,
   so the findings reflect actual rule misconfiguration, not just the
   presence of an identifier in the APK.

When invoked as part of a normal ``ingest_apk`` flow, the engine
operates on the local APK file (any ``AnalysisContext.apk_path`` that
exists on disk). When invoked standalone via :meth:`analyze_package`
it can pull straight from the Play CDN through the configured source.

The engine emits :class:`Finding` objects for:

* Each Firebase config recovered (informational — identifiers are
  expected to be in client APKs; the finding documents the project).
* Each confirmed credential pattern (severity scaled by class —
  service-account JSON is CRITICAL, generic AIza is INFO).
* Each active-probe vulnerability (Realtime DB / Firestore / Storage
  open-to-world).
"""

from __future__ import annotations

import logging
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding, FindingCategory, Severity
from mnexus.playintel.analyzer import AnalysisOutcome, analyze_package, unique_firebase_configs
from mnexus.playintel.apk_source import (
    APKSource,
    LocalAPKSource,
)
from mnexus.playintel.firebase_config import FirebaseConfig
from mnexus.playintel.secret_detector import SecretMatch

log = logging.getLogger(__name__)


# Severity per confirmed-secret class. Anything not listed defaults to
# MEDIUM. Tuned conservatively — these rate the credential's blast
# radius, not whether the specific token is currently active.
_SECRET_SEVERITY: dict[str, Severity] = {
    "GCP Service Account JSON": Severity.CRITICAL,
    "Private Key": Severity.CRITICAL,
    "FCM Server Key": Severity.HIGH,
    "AWS Key Pair": Severity.HIGH,
    "AWS Secret Access Key": Severity.HIGH,
    "Stripe API Key": Severity.HIGH,
    "Slack Token": Severity.HIGH,
    "GitHub Token": Severity.HIGH,
    "GitLab Token": Severity.HIGH,
    "SendGrid API Key": Severity.HIGH,
    "Twilio API Key SID": Severity.HIGH,
    "OpenAI API Key": Severity.HIGH,
    "Anthropic API Key": Severity.HIGH,
    "Groq API Key": Severity.HIGH,
    "OneSignal API Key": Severity.MEDIUM,
    "DigitalOcean PAT": Severity.HIGH,
    "Databricks Token": Severity.HIGH,
    "Vercel Token": Severity.MEDIUM,
    "Hugging Face API Token": Severity.MEDIUM,
}


class PlayIntelEngine(BaseEngine):
    """Mobile credential / Firebase-misconfig recon head.

    Pure-Python end-to-end. Local APK scanning works everywhere; the
    streaming flow over the Google Play protocol additionally requires
    Play credentials in ``~/.config/mnexus/playintel.ini`` (or the
    legacy ``~/.config/apkeep/apkeep.ini`` location). Override the APK
    source via constructor injection if you want to bypass that.
    """

    def __init__(self, config, *, source: APKSource | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(config)
        self._explicit_source = source

    @property
    def name(self) -> str:
        return "playintel"

    @property
    def capabilities(self) -> list[str]:
        return ["firebase", "credentials", "play-stream"]

    async def health_check(self) -> EngineStatus:
        # Static path is always available; report whether Play credentials
        # are wired in too (so /doctor reflects which mode is usable).
        from mnexus.playintel.play_client import PlayCredentials, PlayAuthError

        try:
            PlayCredentials.from_apkeep_ini()
        except PlayAuthError as e:
            return EngineStatus(
                name=self.name,
                installed=True,
                version="static-only",
                path=None,
                message=f"ready · pure-Python scan; Play streaming disabled ({e})",
            )
        return EngineStatus(
            name=self.name,
            installed=True,
            version="play+static",
            path=None,
            message="ready · Play protocol + pure-Python scan",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Scan an APK that's already on disk.

        Wired into ``ingest_apk`` — uses the local-file source so this
        engine contributes findings to every regular MedusaNexus
        scan, even ones the user kicked off with their own APK file.
        """
        source = self._explicit_source or LocalAPKSource(context.apk_path)
        package = context.package_name or context.apk_path.stem
        outcome = analyze_package(
            source,
            package,
            workspace=context.workspace,
            run_active_probes=False,  # local /scan is offline-friendly by default
        )
        return self.findings_from(outcome)

    # ─── Public entry point for the streaming flow ─────────────────────

    async def analyze_package(
        self,
        package_name: str,
        *,
        source: APKSource,
        workspace: Path,
        run_active_probes: bool = True,
    ) -> tuple[AnalysisOutcome, list[Finding]]:
        """Stream + scan + probe a package end-to-end.

        Used by the ``mnexus play-scan`` CLI command and by any future
        HTTP endpoint that exposes the same flow.
        """
        outcome = analyze_package(
            source,
            package_name,
            workspace=workspace,
            run_active_probes=run_active_probes,
        )
        return outcome, self.findings_from(outcome)

    # ─── Findings emission ─────────────────────────────────────────────

    def findings_from(self, outcome: AnalysisOutcome) -> list[Finding]:
        """Translate an :class:`AnalysisOutcome` into MedusaNexus findings."""
        findings: list[Finding] = []
        findings.extend(self._firebase_config_findings(outcome))
        findings.extend(self._secret_findings(outcome.report.confirmed_secrets()))
        findings.extend(self._probe_findings(outcome))
        return findings

    def _firebase_config_findings(self, outcome: AnalysisOutcome) -> list[Finding]:
        out: list[Finding] = []
        for cfg in unique_firebase_configs(outcome.report):
            evidence_lines = [
                f"project_id          = {cfg.project_id}",
                f"google_app_id       = {cfg.app_id or '—'}",
                f"google_api_key      = {cfg.api_key or '—'}",
                f"firebase_database_url = {cfg.database_url or '—'}",
                f"google_storage_bucket = {cfg.storage_bucket or '—'}",
                f"default_web_client_id = {cfg.web_client_id or '—'}",
                f"recovered from      : {cfg.location}",
            ]
            if cfg.additional_api_keys:
                evidence_lines.append(
                    "additional_api_keys = " + ", ".join(cfg.additional_api_keys)
                )
            out.append(
                Finding(
                    title=f"Firebase project identifiers exposed: {cfg.project_id}",
                    description=(
                        "The APK ships Firebase project identifiers (project_id, API key, app ID). "
                        "These are public by design — Firebase SDKs are built to embed them in clients — "
                        "but they identify exactly which Google Cloud project an attacker can probe. "
                        "Real exposure is determined by the corresponding API-key application "
                        "restrictions and Firebase Security Rules; see the active-probe findings, "
                        "if any, in this report."
                    ),
                    severity=Severity.INFO,
                    category=FindingCategory.STORAGE,
                    source_engine=self.name,
                    evidence="\n".join(evidence_lines),
                    location=cfg.location,
                    masvs="MASVS-PLATFORM-1",
                    remediation=None,  # informational only
                    platform_hint="android",
                )
            )
        return out

    def _secret_findings(self, secrets: list[SecretMatch]) -> list[Finding]:
        out: list[Finding] = []
        seen: set[tuple[str, str]] = set()  # de-dup on (type, value)
        for s in secrets:
            key = (s.type, s.value)
            if key in seen:
                continue
            seen.add(key)
            sev = _SECRET_SEVERITY.get(s.type, Severity.MEDIUM)
            out.append(
                Finding(
                    title=f"Hardcoded credential: {s.type}",
                    description=(
                        "A credential matching the issuer's published format was found embedded "
                        "in the APK. Confirmed-pattern hits have low false-positive rates; treat "
                        "as exposed and rotate immediately."
                    ),
                    severity=sev,
                    category=FindingCategory.STORAGE,
                    source_engine=self.name,
                    evidence=f"{s.type}: {_redact(s.value)}\nlocation: {s.location}",
                    location=s.location,
                    cwe_id="CWE-798",
                    owasp_mobile="M9",
                    masvs="MASVS-CRYPTO-1",
                    remediation=(
                        "Rotate the leaked credential at the issuer immediately. "
                        "Move the secret out of the APK: store it server-side and have the app "
                        "obtain a short-lived token via your authenticated backend. "
                        "Add a CI check that fails the build if the same pattern reappears."
                    ),
                    platform_hint="android",
                )
            )
        return out

    def _probe_findings(self, outcome: AnalysisOutcome) -> list[Finding]:
        out: list[Finding] = []
        for r in outcome.rtdb_results:
            if not r.vulnerable:
                continue
            out.append(
                Finding(
                    title=f"Firebase Realtime DB world-accessible: {r.db_url}",
                    description=(
                        "The Realtime Database accepted an unauthenticated request. "
                        f"read={r.public_read}, write={r.public_write}. "
                        "This is the highest-impact misconfiguration class for Firebase: "
                        "anyone on the internet can read or modify customer data via simple HTTP."
                    ),
                    severity=Severity.CRITICAL,
                    category=FindingCategory.AUTH,
                    source_engine=self.name,
                    evidence=f"GET {r.db_url}/.json — read={r.public_read}, write={r.public_write}",
                    location=r.db_url,
                    cwe_id="CWE-284",
                    masvs="MASVS-AUTH-2",
                    remediation=(
                        "Tighten Firebase Realtime Database rules. Default-deny is the only safe baseline:\n"
                        '  { "rules": { ".read": false, ".write": false } }\n'
                        "Then carve out specific read/write paths gated on `auth.uid` or custom claims. "
                        "Enable Firebase App Check with Play Integrity attestation so even authenticated "
                        "tokens minted from outside the production app are rejected."
                    ),
                    platform_hint="android",
                )
            )
        for f in outcome.firestore_results:
            if not f.vulnerable:
                continue
            out.append(
                Finding(
                    title=f"Firestore world-readable: {f.project_id}",
                    description=(
                        f"Cloud Firestore returned {f.sample_document_count} collection IDs to an "
                        "unauthenticated request. Firestore rules are not enforcing authentication "
                        "for collection listing."
                    ),
                    severity=Severity.HIGH,
                    category=FindingCategory.AUTH,
                    source_engine=self.name,
                    evidence=f"POST .../listCollectionIds returned {f.sample_document_count} IDs anonymously",
                    location=f"projects/{f.project_id}/databases/(default)",
                    cwe_id="CWE-284",
                    masvs="MASVS-AUTH-2",
                    remediation=(
                        "Audit Firestore security rules for any `read: true` or `read: if request.auth != null` "
                        "(the latter is functionally public if anonymous sign-in is enabled). "
                        "Treat rule changes with the same review rigour as backend code; add unit tests with "
                        "@firebase/rules-unit-testing in CI."
                    ),
                    platform_hint="android",
                )
            )
        for s in outcome.storage_results:
            if not s.vulnerable:
                continue
            out.append(
                Finding(
                    title=f"Cloud Storage bucket world-listable: {s.bucket}",
                    description=(
                        f"The bucket exposes its object listing anonymously ({s.object_count} objects "
                        "visible in the test sample). Customer uploads, app assets, and staging data may "
                        "be downloadable without authentication."
                    ),
                    severity=Severity.HIGH,
                    category=FindingCategory.STORAGE,
                    source_engine=self.name,
                    evidence=f"GET .../{s.bucket}/o returned listing with {s.object_count} items",
                    location=s.bucket,
                    cwe_id="CWE-284",
                    masvs="MASVS-STORAGE-1",
                    remediation=(
                        "Replace any `allUsers: read` rule on the bucket with explicit auth-gated rules. "
                        "Audit the legacy `match /{allPaths=**}` patterns. Enable Firebase App Check on Storage."
                    ),
                    platform_hint="android",
                )
            )
        return out


def _redact(value: str) -> str:
    """Truncate a credential value for display in findings.

    The full value is preserved in the underlying ScanReport / saved
    files; the finding itself only needs enough to identify which
    credential it points to.
    """
    if len(value) <= 12:
        return value
    return f"{value[:6]}…{value[-4:]}"
