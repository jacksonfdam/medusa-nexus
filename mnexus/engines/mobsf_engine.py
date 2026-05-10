"""MobSF engine — local cross-checks + optional real upload/poll integration.

Two modes share one engine:

1. **Default (offline, deterministic):** local MASTG-flavoured cross-checks
   over `apk_meta` produced by the apktool engine. No network. Always runs.

2. **Real MobSF (opt-in):** when `MNEXUS_USE_MOBSF=1` and a working API
   key is configured, also POST the APK to `/api/v1/upload` + `/api/v1/scan`,
   poll `/api/v1/report_json`, normalise the result into `Finding` objects,
   and dedupe against findings already produced by the local engines.

The dedup strategy is intentionally crude — same (title-prefix, location)
counts as a duplicate. MobSF tends to phrase the same thing six different
ways across versions, so we collapse aggressively rather than ship a six-row
"hardcoded API key" cluster.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding, FindingCategory, Severity

# MobSF severity strings → our Severity enum.
_MOBSF_SEVERITY = {
    "high":     Severity.HIGH,
    "warning":  Severity.MEDIUM,
    "info":     Severity.INFO,
    "good":     Severity.INFO,
    "secure":   Severity.INFO,
    "dangerous": Severity.CRITICAL,
}


class MobSFEngine(BaseEngine):
    """REST client for a running MobSF instance + local manifest cross-checks."""

    @property
    def name(self) -> str:
        return "mobsf"

    @property
    def capabilities(self) -> list[str]:
        return ["static_scan", "full_scan"]

    async def health_check(self) -> EngineStatus:
        if not self.config.mobsf_api_key:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.mobsf_url,
                message="set MNEXUS_MOBSF_API_KEY (or run: scripts/setup.sh --mobsf).",
            )

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                liveness = await client.get(f"{self.config.mobsf_url}/")
                if liveness.status_code >= 500:
                    return EngineStatus(
                        name=self.name,
                        installed=False,
                        version=None,
                        path=self.config.mobsf_url,
                        message=f"MobSF answered {liveness.status_code} — still booting?",
                    )

                auth_probe = await client.post(
                    f"{self.config.mobsf_url}/api/v1/scans",
                    headers=self._headers(),
                )
                if auth_probe.status_code in (401, 403):
                    return EngineStatus(
                        name=self.name,
                        installed=False,
                        version=None,
                        path=self.config.mobsf_url,
                        message="MobSF up but key rejected. Try: scripts/setup.sh --mobsf",
                    )
                upload_path = "online · key OK"
                if not _real_upload_enabled():
                    upload_path += " · MNEXUS_USE_MOBSF=0 (local cross-checks only)"
                return EngineStatus(
                    name=self.name,
                    installed=True,
                    version=self._extract_version(liveness.text),
                    path=self.config.mobsf_url,
                    message=upload_path,
                )
        except httpx.HTTPError as exc:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.mobsf_url,
                message=f"MobSF unreachable: {exc.__class__.__name__}",
            )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Local checks (always) + remote MobSF findings (opt-in, deduped)."""
        local = self._local_findings(context)

        if not _real_upload_enabled() or not self.config.mobsf_api_key:
            return local

        remote = await self._run_remote_scan(context)
        # Dedupe against everything we and other engines have already seen.
        existing_keys = _signatures(local) | _signatures(_extras_findings(context))
        novel = [f for f in remote if _signature(f) not in existing_keys]
        return local + novel

    # ─── local mode ───────────────────────────────────────────────────

    def _local_findings(self, context: AnalysisContext) -> list[Finding]:
        meta = (context.extras or {}).get("apk_meta") or {}
        findings: list[Finding] = []

        for comp in meta.get("exported_components", []):
            if comp.get("type") == "provider" and comp.get("unprotected"):
                findings.append(Finding(
                    title=f"ContentProvider exported without permission: {comp['name']}",
                    description=("An exported provider without `android:permission` is a remote SQL/IPC endpoint "
                                 "any installed app can talk to."),
                    severity=Severity.HIGH,
                    category=FindingCategory.STORAGE,
                    source_engine=self.name,
                    evidence=f"<provider android:name=\"{comp['name']}\" android:exported=\"true\">",
                    location="AndroidManifest.xml",
                    cwe_id="CWE-926",
                    masvs="MSTG-PLATFORM-4",
                    remediation="Add `android:permission` (signature-level), parametrize all queries, deny `*` URIs.",
                ))

        perms = meta.get("permissions", [])
        if len(perms) >= 25:
            findings.append(Finding(
                title=f"App declares {len(perms)} permissions — unusually broad",
                description="A large permission set widens the attack surface and triggers Play Store review.",
                severity=Severity.LOW,
                category=FindingCategory.PRIVACY,
                source_engine=self.name,
                evidence=", ".join(perms[:8]) + ("…" if len(perms) > 8 else ""),
                location="AndroidManifest.xml",
            ))

        try:
            min_sdk_int = int(meta.get("min_sdk") or "0")
        except ValueError:
            min_sdk_int = 0
        if 0 < min_sdk_int < 21:
            findings.append(Finding(
                title=f"minSdkVersion={min_sdk_int} — pre-Lollipop devices in scope",
                description=("Below API 21 you lose Network Security Config, scoped storage, JobScheduler, "
                             "and a long list of platform mitigations."),
                severity=Severity.LOW,
                category=FindingCategory.CODE,
                source_engine=self.name,
                evidence=f"minSdkVersion={min_sdk_int}",
                location="AndroidManifest.xml",
            ))

        return findings

    # ─── remote mode ──────────────────────────────────────────────────

    async def _run_remote_scan(self, context: AnalysisContext) -> list[Finding]:
        """Upload → scan → poll report_json → normalise. Never raises."""
        import logging
        log = logging.getLogger(__name__)
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                hash_id = await self._upload(client, context)
                if not hash_id:
                    return []
                await self._scan(client, hash_id)
                report = await self._poll_report(client, hash_id)
                if not report:
                    return []
                return list(_normalize_report(report, source_engine=self.name))
        except httpx.HTTPError as exc:
            log.warning("MobSF remote scan failed: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            log.warning("MobSF remote scan unexpected error: %s", exc)
            return []

    async def _upload(self, client: httpx.AsyncClient, context: AnalysisContext) -> str | None:
        """POST /api/v1/upload returns {hash, scan_type, file_name}."""
        with open(context.apk_path, "rb") as fh:
            files = {"file": (context.apk_path.name, fh, "application/vnd.android.package-archive")}
            r = await client.post(
                f"{self.config.mobsf_url}/api/v1/upload",
                headers=self._headers(),
                files=files,
            )
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("hash")

    async def _scan(self, client: httpx.AsyncClient, hash_id: str) -> None:
        """POST /api/v1/scan kicks off the static analysis pipeline."""
        await client.post(
            f"{self.config.mobsf_url}/api/v1/scan",
            headers=self._headers(),
            data={"hash": hash_id},
        )

    async def _poll_report(
        self, client: httpx.AsyncClient, hash_id: str, max_attempts: int = 30, delay_s: float = 2.0
    ) -> dict[str, Any] | None:
        """Wait for the JSON report to be ready. MobSF is sync once /scan is invoked,
        but very large APKs occasionally exceed a single request timeout — poll
        with exponential-ish backoff."""
        for _ in range(max_attempts):
            r = await client.post(
                f"{self.config.mobsf_url}/api/v1/report_json",
                headers=self._headers(),
                data={"hash": hash_id},
            )
            if r.status_code == 200:
                payload = r.json()
                # MobSF returns {"error": "..."} when the report isn't ready.
                if isinstance(payload, dict) and "error" not in payload and payload.get("findings") is not None or payload.get("manifest_analysis") is not None:
                    return payload
            await asyncio.sleep(delay_s)
            delay_s = min(delay_s * 1.4, 10.0)
        return None

    # ─── plumbing ──────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Send both header styles. MobSF has historically accepted either."""
        key = self.config.mobsf_api_key or ""
        return {"Authorization": key, "X-Mobsf-Api-Key": key}

    @staticmethod
    def _extract_version(html: str) -> str:
        import re

        match = re.search(r"MobSF[^<]*?v?([0-9]+\.[0-9]+\.[0-9]+)", html)
        return match.group(1) if match else "?"


# ─── module helpers ────────────────────────────────────────────────────


def _real_upload_enabled() -> bool:
    """Opt-in to the real MobSF upload+poll path."""
    return os.environ.get("MNEXUS_USE_MOBSF", "").lower() in {"1", "true", "yes", "on"}


def _signature(f: Finding) -> tuple[str, str]:
    """Crude dedup key — first 6 words of the title + location."""
    title_prefix = " ".join(f.title.lower().split()[:6])
    return (title_prefix, (f.location or "").lower())


def _signatures(findings: list[Finding]) -> set[tuple[str, str]]:
    return {_signature(f) for f in findings}


def _extras_findings(context: AnalysisContext) -> list[Finding]:
    """Findings already produced by other engines and stashed in extras
    (the orchestrator stages them so MobSF's dedup can see them)."""
    extras = context.extras or {}
    bag = extras.get("findings_so_far") or []
    return [f for f in bag if isinstance(f, Finding)]


def _normalize_report(report: dict[str, Any], *, source_engine: str) -> list[Finding]:
    """Map a MobSF JSON report into `Finding` objects.

    MobSF's schema has migrated a few times — we look for the shapes we've
    actually seen in 3.x and 4.x:
      - `code_analysis.findings` / `code_analysis.summary`
      - `manifest_analysis` / `manifest_analysis_findings`
      - `permissions` (with status: dangerous/normal/signature)
      - `urls`, `secrets`, `firebase_urls`, `trackers`
    Anything we don't recognise is skipped silently — we'd rather miss a
    novel finding than crash the pipeline.
    """
    out: list[Finding] = []

    code = report.get("code_analysis") or {}
    findings_blob = code.get("findings") or {}
    if isinstance(findings_blob, dict):
        for title, payload in findings_blob.items():
            if not isinstance(payload, dict):
                continue
            sev = _MOBSF_SEVERITY.get(str(payload.get("metadata", {}).get("severity", "info")).lower(), Severity.INFO)
            files = payload.get("files") or {}
            for file_path, line in (files.items() if isinstance(files, dict) else []):
                cwe = payload.get("metadata", {}).get("cwe", "") or None
                masvs = payload.get("metadata", {}).get("masvs", "") or None
                description = payload.get("metadata", {}).get("description") or title
                rem = payload.get("metadata", {}).get("ref") or None
                # Force a minimum mitigation for HIGH/CRITICAL — Finding's own
                # validator will reject otherwise. For LOW/MEDIUM/INFO we let
                # the empty `remediation` ride.
                if sev in (Severity.CRITICAL, Severity.HIGH) and not rem:
                    rem = (
                        "MobSF flagged this without explicit remediation. "
                        "Cross-reference the rule id in MobSF's UI for guidance, or strip the responsible API "
                        "if it isn't required."
                    )
                try:
                    out.append(Finding(
                        title=title.replace("_", " ").capitalize(),
                        description=description,
                        severity=sev,
                        category=_guess_category(title),
                        source_engine=source_engine,
                        evidence=f"file: {file_path} line: {line}",
                        location=file_path,
                        cwe_id=str(cwe) if cwe else None,
                        owasp_mobile=None,
                        masvs=str(masvs) if masvs else None,
                        remediation=rem,
                    ))
                except ValueError:
                    # invariant rejected (e.g. empty title) — skip
                    continue

    # Manifest findings — MobSF 4.x ships them under `manifest_analysis.manifest_findings`
    ma = report.get("manifest_analysis") or {}
    for entry in ma.get("manifest_findings") or []:
        if not isinstance(entry, dict):
            continue
        sev = _MOBSF_SEVERITY.get(str(entry.get("severity", "info")).lower(), Severity.INFO)
        title = entry.get("title") or entry.get("rule") or "MobSF manifest finding"
        description = entry.get("description") or title
        rem = entry.get("remediation") or None
        if sev in (Severity.CRITICAL, Severity.HIGH) and not rem:
            rem = "Inspect the matching MobSF rule and update the manifest accordingly."
        try:
            out.append(Finding(
                title=str(title)[:120],
                description=str(description),
                severity=sev,
                category=FindingCategory.IPC,
                source_engine=source_engine,
                evidence=str(entry.get("component") or entry.get("name") or "—"),
                location="AndroidManifest.xml",
                remediation=rem,
            ))
        except ValueError:
            continue

    return out


def _guess_category(title: str) -> FindingCategory:
    t = title.lower()
    if "crypto" in t or "cipher" in t or "key" in t or "iv" in t or "hash" in t:
        return FindingCategory.CRYPTO
    if "webview" in t or "javascript" in t:
        return FindingCategory.WEBVIEW
    if "network" in t or "ssl" in t or "tls" in t or "cleartext" in t or "trust" in t or "pinning" in t:
        return FindingCategory.NETWORK
    if "log" in t or "stacktrace" in t or "debug" in t:
        return FindingCategory.PRIVACY
    if "intent" in t or "broadcast" in t or "provider" in t or "exported" in t:
        return FindingCategory.IPC
    if "shared" in t or "sql" in t or "storage" in t or "file" in t:
        return FindingCategory.STORAGE
    if "auth" in t or "biometric" in t or "fingerprint" in t:
        return FindingCategory.AUTH
    if "native" in t or ".so" in t or "jni" in t:
        return FindingCategory.NATIVE
    return FindingCategory.CODE
