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
                message="set MNEXUS_MOBSF_API_KEY — MobSF doesn't give it away for free.",
            )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.config.mobsf_url}/api/v1/scan/recent_scans", headers=self._headers())
                if r.status_code == 200:
                    return EngineStatus(
                        name=self.name,
                        installed=True,
                        version="?",
                        path=self.config.mobsf_url,
                        message=f"online at {self.config.mobsf_url}",
                    )
                return EngineStatus(
                    name=self.name,
                    installed=False,
                    version=None,
                    path=self.config.mobsf_url,
                    message=f"MobSF answered {r.status_code}. Check the API key.",
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
        return {"Authorization": self.config.mobsf_api_key or ""}
