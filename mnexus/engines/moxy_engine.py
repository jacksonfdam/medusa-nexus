"""Moxy engine — pulls captured HTTP flows from matank001/Moxy.

Moxy is an open-source MITM proxy + web UI built on mitmproxy. It ships a
small Flask API at the same origin as the UI (default ``http://localhost:5000``)
that exposes captured requests with full ``raw_request`` / ``raw_response``
bodies — exactly what the Network tab wants.

The API surface we touch is small on purpose:

* ``GET /api/projects``                  — list workspaces (id + name).
* ``GET /api/projects/{id}/requests``    — paginated flows for one workspace.

Each captured flow comes back as::

    {
        "id": 405,
        "flow_id": "a4150360-...",
        "method": "GET",
        "url": "http://play.googleapis.com/generate_204",
        "status_code": 204,
        "duration_ms": 36,
        "timestamp": "2026-05-11T17:26:18.524425",
        "completed_at": "2026-05-11T17:26:18.564321",
        "raw_request":  "GET /generate_204 HTTP/1.1\\r\\n...",
        "raw_response": "HTTP/1.1 204 No Content\\r\\n..."
    }

We flatten that into the same dict shape the Burp / Frida ``dynamic_events``
channel uses (``method`` / ``host`` / ``path`` / ``status`` / ``size`` /
``ms`` / ``ts``) so the Network tab can render Moxy rows alongside Burp rows
without a second code path. Nothing here is destructive — we never push to
Moxy, only read.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class MoxyEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "moxy"

    @property
    def capabilities(self) -> list[str]:
        return ["proxy", "capture", "replay"]

    async def health_check(self) -> EngineStatus:
        base = self.config.moxy_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                # /api/projects is unauthenticated and always present (the
                # 'Default Project' row is seeded on first container boot).
                r = await client.get(f"{base}/api/projects")
                if r.status_code != 200:
                    return EngineStatus(
                        name=self.name,
                        installed=False,
                        version=None,
                        path=base,
                        message=f"Moxy answered {r.status_code} on /api/projects — running on {base}?",
                    )
                projects = r.json() if isinstance(r.json(), list) else []
                proxy_hint = f"{self.config.moxy_proxy_host}:{self.config.moxy_proxy_port}"
                return EngineStatus(
                    name=self.name,
                    installed=True,
                    version=None,
                    path=base,
                    message=f"online · {len(projects)} project(s) · device → {proxy_hint}",
                )
        except httpx.HTTPError as exc:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=base,
                message=f"Moxy unreachable: {exc.__class__.__name__} — run scripts/setup.sh --moxy",
            )

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []

    # ─── public helpers used by the API / UI ──────────────────────────────

    async def list_projects(self) -> list[dict[str, Any]]:
        """Return the raw project list straight from Moxy. Empty on any error."""
        base = self.config.moxy_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{base}/api/projects")
                if r.status_code != 200:
                    return []
                data = r.json()
                return data if isinstance(data, list) else []
        except httpx.HTTPError:
            return []

    async def pick_project(self, package_name: str | None) -> dict[str, Any] | None:
        """Best-effort match: prefer a workspace named after the package, else
        fall back to the most recently updated one. Returns ``None`` only if
        Moxy is unreachable or has no workspaces at all (it always seeds one)."""
        projects = await self.list_projects()
        if not projects:
            return None
        if package_name:
            pkg = package_name.lower()
            for p in projects:
                name = str(p.get("name", "")).lower()
                if name == pkg or pkg in name or name in pkg:
                    return p
        # Fall back to the freshest (Moxy returns updated_at; sort desc).
        projects_sorted = sorted(
            projects,
            key=lambda p: str(p.get("updated_at") or p.get("created_at") or ""),
            reverse=True,
        )
        return projects_sorted[0]

    async def fetch_flows(
        self,
        project_id: int,
        *,
        limit: int = 1000,
        hosts: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Pull captured flows for one Moxy workspace, normalised to the same
        shape the Burp/Frida ``dynamic_events`` channel uses.

        ``hosts`` (optional) limits results to flows whose URL host matches one
        of the project's known endpoints — useful when Moxy is collecting
        ambient traffic and you only want to see what's relevant to this APK.
        """
        base = self.config.moxy_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{base}/api/projects/{project_id}/requests",
                    params={"limit": limit},
                )
                if r.status_code != 200:
                    return []
                payload = r.json()
        except httpx.HTTPError:
            return []

        raw_flows = payload.get("requests", []) if isinstance(payload, dict) else []
        out: list[dict[str, Any]] = []
        for flow in raw_flows:
            row = _normalise_flow(flow)
            if hosts and row["host"] and row["host"] not in hosts:
                row["matches_project"] = False
            else:
                row["matches_project"] = True
            out.append(row)
        return out


def _normalise_flow(flow: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Moxy ``request`` row into the shape the Network tab renders."""
    url = str(flow.get("url") or "")
    host, path = "", "/"
    if url:
        parts = urlsplit(url)
        host = parts.netloc or host
        # Re-join path + query so the table shows the full request line.
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"

    status = flow.get("status_code")
    raw_response = flow.get("raw_response") or ""
    size = _size_from_raw_response(raw_response)

    return {
        "method": str(flow.get("method") or "GET").upper(),
        "host": host,
        "path": path,
        "url": url,
        "status": int(status) if isinstance(status, int) else status,
        "size": size,
        "ms": flow.get("duration_ms"),
        "ts": flow.get("timestamp") or flow.get("completed_at"),
        "flow_id": flow.get("flow_id"),
        "origin": "moxy",
        # Lightweight severity heuristic so the UI can paint the row.
        "severity": _severity_for(status),
    }


def _size_from_raw_response(raw: str) -> int:
    """Best-effort response body size.

    Prefer the ``Content-Length`` header when present (cheap, exact); fall back
    to the byte length of whatever lives after the first ``\\r\\n\\r\\n`` (the
    end of the header block in raw HTTP). Returns 0 when the response is empty
    or malformed — never raises.
    """
    if not raw:
        return 0
    head, _, body = raw.partition("\r\n\r\n")
    for line in head.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                break
    return len(body.encode("utf-8", errors="replace"))


def _severity_for(status: Any) -> str:
    """Map HTTP status → severity bucket used by the UI palette."""
    try:
        code = int(status)
    except (TypeError, ValueError):
        return "info"
    if code >= 500:
        return "crit"
    if code >= 400:
        return "high"
    if code >= 300:
        return "medium"
    return "info"
