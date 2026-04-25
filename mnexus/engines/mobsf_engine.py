"""MobSF engine — the static lecturer. Runs over REST because who wants another CLI."""

from __future__ import annotations

import httpx

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class MobSFEngine(BaseEngine):
    """REST client for a running MobSF instance. Uploads APK → polls → normalizes."""

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

        # Two probes:
        # 1. GET / — is MobSF up at all?
        # 2. POST /api/v1/scans (no body, auth headers) — does the key pass auth?
        #    Expect 400 / 405 / 500 on valid key (we omitted the body on purpose).
        #    401 / 403 means the key is wrong.
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
                return EngineStatus(
                    name=self.name,
                    installed=True,
                    version=self._extract_version(liveness.text),
                    path=self.config.mobsf_url,
                    message=f"online · key OK ({auth_probe.status_code} on empty scan probe)",
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
        """Local MobSF-style static checks driven by parsed manifest metadata.

        We don't require a running MobSF server — these are MASTG-flavored
        cross-checks over what the apktool engine already extracted. When
        MobSF *is* configured, the orchestrator can promote its findings;
        here we keep things deterministic so the pipeline produces value
        even on a fresh install.
        """
        from mnexus.models.finding import Finding, FindingCategory, Severity

        meta = (context.extras or {}).get("apk_meta") or {}
        findings: list[Finding] = []

        # Components: surface providers without permission separately so they
        # show up under the storage category (typical content-provider risk).
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

        # Permission count — informational only.
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

        # Min SDK too low — pre-N apps lose modern platform protections.
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

    def _headers(self) -> dict[str, str]:
        """Send both header styles. MobSF has historically accepted either."""
        key = self.config.mobsf_api_key or ""
        return {"Authorization": key, "X-Mobsf-Api-Key": key}

    @staticmethod
    def _extract_version(html: str) -> str:
        """Best-effort scrape of MobSF version from the landing page title/footer."""
        import re

        match = re.search(r"MobSF[^<]*?v?([0-9]+\.[0-9]+\.[0-9]+)", html)
        return match.group(1) if match else "?"
