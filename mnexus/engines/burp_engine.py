"""Burp engine — proxy everything, trust nothing.

Two compatible REST flavors are probed, in order:

1. **vmware-archive/burp-rest-api** — Spring Boot wrapper, GET /burp/versions,
   no auth by default. Signaled by MNEXUS_BURP_API_KEY in
   ("", "none", "no-auth").

2. **Burp Suite Professional native REST API** — GET /<api_key>/v0.1/. The
   "key" is part of the URL path, not an Authorization header. Enable via
   *Settings → Suite → API*. Signaled by any other MNEXUS_BURP_API_KEY value.

Whichever answers 200 first wins. This keeps the health probe engine-agnostic
so `mnexus doctor` just reports "Burp is reachable and talking".
"""

from __future__ import annotations

import httpx

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


_NO_AUTH_SENTINELS = {"", "none", "no-auth"}


class BurpEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "burp"

    @property
    def capabilities(self) -> list[str]:
        return ["proxy", "intercept", "scan", "traffic_history"]

    async def health_check(self) -> EngineStatus:
        key = (self.config.burp_api_key or "").strip()
        base = self.config.burp_url.rstrip("/")

        # Decide which flavor to probe based on the key value.
        probes = self._probe_plan(base, key)

        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                for flavor, url in probes:
                    result = await self._probe(client, flavor, url)
                    if result is not None:
                        return result
        except httpx.HTTPError as exc:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.burp_url,
                message=(
                    f"Burp unreachable: {exc.__class__.__name__} — "
                    "is Burp running (or burp-rest-api launched via "
                    "`~/.mnexus/tools/burp-rest-api/run.sh`)?"
                ),
            )

        return EngineStatus(
            name=self.name,
            installed=False,
            version=None,
            path=self.config.burp_url,
            message=(
                "no REST API answered. Either enable Burp Pro's API (Settings → Suite → API) "
                "or install burp-rest-api: scripts/setup.sh --burp-rest-api"
            ),
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

    # ─── internals ───

    def _probe_plan(self, base: str, key: str) -> list[tuple[str, str]]:
        """Return the (flavor, url) pairs we'll try, in order."""
        plan: list[tuple[str, str]] = []
        if key.lower() in _NO_AUTH_SENTINELS:
            # Prefer burp-rest-api. Fall through to a path-keyed probe that uses
            # the literal sentinel (mostly to generate a useful 404 message).
            plan.append(("burp-rest-api", f"{base}/burp/versions"))
            if key.lower() == "no-auth":
                plan.append(("pro-fallback", f"{base}/no-auth/v0.1/"))
        else:
            # Pro native first, but fall back to burp-rest-api in case the user
            # wired the wrong endpoint into MNEXUS_BURP_URL.
            plan.append(("pro", f"{base}/{key}/v0.1/"))
            plan.append(("burp-rest-api", f"{base}/burp/versions"))
        return plan

    async def _probe(
        self, client: httpx.AsyncClient, flavor: str, url: str
    ) -> EngineStatus | None:
        """Probe one URL. Return an EngineStatus if it concludes the check,
        or None to signal 'keep trying the next probe'."""
        r = await client.get(url)

        if r.status_code == 200:
            version = self._extract_version(r, flavor)
            banner = {
                "burp-rest-api": "burp-rest-api online — headless + no auth",
                "pro": "Burp Pro REST API online — ready to scan",
                "pro-fallback": "Burp Pro REST API online (via sentinel key)",
            }.get(flavor, "online")
            return EngineStatus(
                name=self.name,
                installed=True,
                version=version,
                path=self.config.burp_url,
                message=banner,
            )

        if r.status_code in (401, 403):
            if flavor.startswith("pro"):
                return EngineStatus(
                    name=self.name,
                    installed=False,
                    version=None,
                    path=self.config.burp_url,
                    message=f"Burp rejected the key ({r.status_code}) — regenerate in Suite → API.",
                )
            return None  # try the next probe

        if r.status_code == 404 and flavor == "burp-rest-api":
            # burp-rest-api is not at this URL. Don't conclude yet.
            return None

        if r.status_code == 404 and flavor.startswith("pro"):
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=self.config.burp_url,
                message="Burp up but /<key>/v0.1/ 404 — wrong MNEXUS_BURP_API_KEY?",
            )

        # Anything else: surface it.
        return EngineStatus(
            name=self.name,
            installed=False,
            version=None,
            path=self.config.burp_url,
            message=f"{flavor} answered {r.status_code} at {url}",
        )

    @staticmethod
    def _extract_version(response: httpx.Response, flavor: str) -> str:
        try:
            data = response.json()
        except ValueError:
            return "?"
        if not isinstance(data, dict):
            return "?"
        if flavor == "burp-rest-api":
            # GET /burp/versions returns {"extensionVersion": ..., "burpVersion": ...}
            burp = data.get("burpVersion") or data.get("burp_version") or "?"
            ext = data.get("extensionVersion") or data.get("extension_version")
            return f"burp {burp} · rest-api {ext}" if ext else str(burp)
        for k in ("version", "burp_version", "api_version"):
            if k in data:
                return str(data[k])
        return "?"
