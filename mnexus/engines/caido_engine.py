"""Caido engine — alternative to Burp Suite.

Caido (https://caido.io) is a Rust-based intercepting proxy with a modern
UI and a documented REST API. We keep parity with `BurpEngine` so the rest
of the platform can swap between them based on `MNEXUS_PROXY_FLAVOR`
(default `burp` for back-compat; set to `caido` to use Caido instead).

The Caido API surface we care about:

* `GET  /v1/version`       — liveness + version (no auth required).
* `POST /v1/auth/login`    — exchange username/password for an API token.
* `GET  /v1/users/me`      — token validity check.
* `GET  /v1/projects`      — list workspaces.
* `GET  /v1/replay/sessions` — past requests (for traffic export).
* `GET  /v1/sitemap`       — discovered hosts/paths (for endpoint export).

The community OpenAPI lives at https://github.com/MDGDSS/caido-openapi —
we don't generate from it (yet) to avoid a heavy codegen step; we hand-roll
the four calls we actually need.
"""

from __future__ import annotations

import httpx

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class CaidoEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "caido"

    @property
    def capabilities(self) -> list[str]:
        return ["proxy", "intercept", "replay", "sitemap"]

    async def health_check(self) -> EngineStatus:
        base = self.config.caido_url.rstrip("/")
        token = (self.config.caido_api_key or "").strip()

        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                # 1. Public liveness — /v1/version is unauth.
                live = await client.get(f"{base}/v1/version")
                if live.status_code != 200:
                    return EngineStatus(
                        name=self.name,
                        installed=False,
                        version=None,
                        path=base,
                        message=f"Caido answered {live.status_code} on /v1/version — running on {base}?",
                    )
                version = self._extract_version(live)

                # 2. Auth check (only if a token is configured).
                if token:
                    me = await client.get(
                        f"{base}/v1/users/me",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if me.status_code in (401, 403):
                        return EngineStatus(
                            name=self.name,
                            installed=False,
                            version=version,
                            path=base,
                            message="Caido up but token rejected. Regenerate at Workbench → Settings → Tokens.",
                        )

                msg = "online · ready to proxy and replay"
                if not token:
                    msg += " · no token (read-only sitemap export)"
                return EngineStatus(
                    name=self.name,
                    installed=True,
                    version=version,
                    path=base,
                    message=msg,
                )
        except httpx.HTTPError as exc:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=base,
                message=f"Caido unreachable: {exc.__class__.__name__} — see https://docs.caido.io/app/quickstart/",
            )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Promote Caido replay history into structured Findings.

        Same contract as BurpEngine.execute — pull recent requests
        from /v1/replay/sessions (or /v1/sitemap as a poor proxy when
        replay isn't available), normalise, run the shared analyser.
        ``[]`` on any failure path.
        """
        from mnexus.intelligence.traffic_findings import findings_for_flows

        flows = await self._fetch_history()
        if not flows:
            return []
        surface_hosts = set(getattr(context, "surface_hosts", set()) or set())
        return findings_for_flows(flows, surface_hosts=surface_hosts, source_engine="caido")

    async def _fetch_history(self) -> list[dict]:
        """Caido /v1/replay/sessions or /v1/sitemap into common flow shape."""
        base = self.config.caido_url.rstrip("/")
        token = self.config.caido_api_key or ""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for path in ("/v1/replay/sessions", "/v1/sitemap"):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{base}{path}", headers=headers)
                    if r.status_code != 200:
                        continue
                    payload = r.json()
            except httpx.HTTPError:
                continue
            rows = payload.get("items") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                continue
            out: list[dict] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "")
                out.append({
                    "method": str(row.get("method") or "GET").upper(),
                    "url": url,
                    "host": row.get("host") or "",
                    "path": row.get("path") or "/",
                    "status": row.get("status") or row.get("status_code"),
                    "raw_request": row.get("request") or row.get("raw_request"),
                    "raw_response": row.get("response") or row.get("raw_response"),
                    "ts": row.get("ts") or row.get("created_at"),
                })
            if out:
                return out
        return []

    # ─── public helpers used by exporters / UI ─────────────────────────

    async def list_sitemap(self) -> list[dict]:
        """Return discovered hosts/paths from the active workspace.

        Returns [] when no workspace is active or the call fails — the
        caller (exporter) treats this as 'no captured traffic yet'.
        """
        base = self.config.caido_url.rstrip("/")
        token = self.config.caido_api_key or ""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{base}/v1/sitemap",
                    headers={"Authorization": f"Bearer {token}"} if token else {},
                )
                if r.status_code != 200:
                    return []
                payload = r.json()
                # Caido returns either a list or a {"items": [...]} envelope
                # depending on version — normalize.
                if isinstance(payload, dict) and "items" in payload:
                    return list(payload["items"])
                if isinstance(payload, list):
                    return payload
                return []
        except httpx.HTTPError:
            return []

    @staticmethod
    def _extract_version(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return "?"
        if isinstance(data, dict):
            for key in ("version", "build", "release"):
                if key in data:
                    return str(data[key])
        return "?"
