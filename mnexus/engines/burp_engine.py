"""Burp engine — proxy everything, trust nothing.

Talks to Burp Suite Professional over its REST API. Burp Pro exposes the API
at `http://<host>:<port>/<api_key>/v0.1/…` — the "key" is part of the URL path,
not an Authorization header. Enable the API under *Settings → Suite → API*.

For proxy-history streaming (what we actually want) we'll later require the
`burp-rest-api` extension or a thin Montoya helper; this file covers the
REST-API health probe only.
"""

from __future__ import annotations

import httpx

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class BurpEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "burp"

    @property
    def capabilities(self) -> list[str]:
        return ["proxy", "intercept", "scan", "traffic_history"]

    async def health_check(self) -> EngineStatus:
        if not self.config.burp_api_key:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.burp_url,
                message=(
                    "enable Burp REST API (Settings → Suite → API), "
                    "set MNEXUS_BURP_API_KEY (or: scripts/setup.sh --burp)."
                ),
            )

        base = self.config.burp_url.rstrip("/")
        url = f"{base}/{self.config.burp_api_key}/v0.1/"
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                r = await client.get(url)
        except httpx.HTTPError as exc:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.burp_url,
                message=f"Burp unreachable: {exc.__class__.__name__} — is Burp running with the REST API on?",
            )

        if r.status_code == 200:
            version = self._extract_version(r)
            return EngineStatus(
                name=self.name,
                installed=True,
                version=version,
                path=self.config.burp_url,
                message="online — ready to proxy and scan",
            )
        if r.status_code == 404:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.burp_url,
                message="Burp up but key path 404 — wrong MNEXUS_BURP_API_KEY? check Burp's API panel.",
            )
        if r.status_code in (401, 403):
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.burp_url,
                message=f"Burp rejected the key ({r.status_code}) — regenerate in Suite → API.",
            )
        return EngineStatus(
            name=self.name,
            installed=False,
            version=None,
            path=self.config.burp_url,
            message=f"Burp answered {r.status_code} at /v0.1/ — consult Burp logs.",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

    @staticmethod
    def _extract_version(response: httpx.Response) -> str:
        """Best-effort grab of Burp's API version string from the root response."""
        try:
            data = response.json()
        except ValueError:
            return "?"
        if isinstance(data, dict):
            for key in ("version", "burp_version", "api_version"):
                if key in data:
                    return str(data[key])
        return "?"
