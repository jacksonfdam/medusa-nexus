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

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

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
