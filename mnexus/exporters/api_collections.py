"""API-collection exporters: Postman, Caido, Burp items, Moxy.

Each exporter accepts a `Project` and emits a string ready to write to
disk. The endpoint set is `project.attack_surface.api_endpoints` plus,
for the network-aware exporters, a derived list of GET requests against
each unique URL.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from mnexus.models.project import Project

# ─── helpers ────────────────────────────────────────────────────────────


def _endpoints(project: Project) -> list[str]:
    surface = project.attack_surface
    if not surface:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for url in surface.api_endpoints:
        url = (url or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        # Normalise: drop tracking fragments + duplicate ports
        parsed = urlparse(url)
        canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"
        if parsed.query:
            canonical += f"?{parsed.query}"
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _deeplinks(project: Project) -> list[str]:
    surface = project.attack_surface
    if not surface:
        return []
    return list(dict.fromkeys(d.strip() for d in surface.deeplinks if d and d.strip()))


def _meta(project: Project) -> dict:
    return {
        "project_id": project.id,
        "package": project.package_name,
        "version": project.version_name,
        "platform": project.platform,
        "exported_at": datetime.now(UTC).isoformat(),
        "tagline": "exported by MEDUSA NEXUS — every head sees a different angle",
    }


# ─── Postman v2.1 collection ───────────────────────────────────────────


def to_postman(project: Project) -> str:
    """Postman v2.1 JSON collection.

    One folder per host, one request per (method, url). Methods default
    to GET because that's what static analysis recovered; testers tweak
    bodies/headers in Postman afterwards.
    """
    endpoints = _endpoints(project)
    deeplinks = _deeplinks(project)

    by_host: dict[str, list[dict]] = {}
    for url in endpoints:
        host = urlparse(url).netloc or "unknown"
        by_host.setdefault(host, []).append(_postman_request(url, method="GET"))

    folders = [
        {
            "name": host,
            "item": items,
        }
        for host, items in sorted(by_host.items())
    ]

    if deeplinks:
        folders.append({
            "name": "deeplinks (informational)",
            "description": "These are URI schemes to fire via `adb shell am start`, not HTTP — Postman won't replay them, but having them in one place is convenient.",
            "item": [
                {
                    "name": link,
                    "request": {
                        "method": "GET",
                        "url": {"raw": link},
                        "description": "deep link / app URI scheme",
                    },
                }
                for link in deeplinks
            ],
        })

    collection = {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": f"MEDUSA NEXUS · {project.package_name} {project.version_name}",
            "description": _description_blurb(project),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
        "_mnexus": _meta(project),
    }
    return json.dumps(collection, indent=2)


def _postman_request(url: str, method: str) -> dict:
    parsed = urlparse(url)
    return {
        "name": f"{method} {parsed.path or '/'}",
        "request": {
            "method": method,
            "header": [],
            "url": {
                "raw": url,
                "protocol": parsed.scheme,
                "host": parsed.netloc.split("."),
                "path": [p for p in parsed.path.split("/") if p],
                "query": _postman_query(parsed.query),
            },
        },
    }


def _postman_query(qs: str) -> list[dict]:
    if not qs:
        return []
    out = []
    for pair in qs.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        out.append({"key": k, "value": v})
    return out


# ─── Caido sitemap (importable) ────────────────────────────────────────


def to_caido(project: Project) -> str:
    """Caido import format — list of HTTP entries that Caido's
    `Workbench → Replay → Import` understands.

    Caido's importer is permissive about JSON shape; we ship the same
    `{requests: [{method, url, headers, body}]}` envelope used by their
    `caidoctl import` command.
    """
    endpoints = _endpoints(project)
    return json.dumps(
        {
            "version": 1,
            "exporter": "medusa-nexus",
            "metadata": _meta(project),
            "requests": [
                {
                    "id": f"{project.id}-{i:04d}",
                    "method": "GET",
                    "url": url,
                    "headers": [
                        {"name": "User-Agent", "value": "MedusaNexus/0.1 (+https://github.com/jacksonfdam/medusa-nexus)"},
                        {"name": "X-Mnexus-Project", "value": project.id},
                    ],
                    "body": None,
                    "tags": [project.package_name, project.platform],
                }
                for i, url in enumerate(endpoints)
            ],
        },
        indent=2,
    )


# ─── Burp Suite items XML (importable) ────────────────────────────────


def to_burp_items(project: Project) -> str:
    """Burp 'items' XML — the format Burp's *Send to Repeater → Import* uses.

    Hand-rolled (no `xml.etree` because Burp's parser is picky about the
    `base64` flag attribute and we want to control the exact whitespace).
    Each `<item>` carries an URL and a base64-encoded raw HTTP/1.1 GET.
    """
    import base64

    endpoints = _endpoints(project)

    items_xml: list[str] = []
    for url in endpoints:
        parsed = urlparse(url)
        host = parsed.netloc
        port = "443" if parsed.scheme == "https" else "80"
        protocol = "https" if parsed.scheme == "https" else "http"
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw_request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: MedusaNexus/0.1\r\n"
            f"X-Mnexus-Project: {project.id}\r\n"
            f"Connection: close\r\n\r\n"
        )
        b64 = base64.b64encode(raw_request.encode("utf-8")).decode("ascii")

        items_xml.append(
            "  <item>\n"
            f"    <url><![CDATA[{url}]]></url>\n"
            f"    <host ip=\"\">{host}</host>\n"
            f"    <port>{port}</port>\n"
            f"    <protocol>{protocol}</protocol>\n"
            "    <method><![CDATA[GET]]></method>\n"
            f"    <path><![CDATA[{path}]]></path>\n"
            f"    <request base64=\"true\"><![CDATA[{b64}]]></request>\n"
            "    <response base64=\"true\"><![CDATA[]]></response>\n"
            "    <comment><![CDATA[exported by MEDUSA NEXUS]]></comment>\n"
            "  </item>"
        )

    return (
        "<?xml version=\"1.0\"?>\n"
        f"<!-- exported by MEDUSA NEXUS · {project.package_name} {project.version_name} · {datetime.now(UTC).isoformat()} -->\n"
        "<items burpVersion=\"\">\n"
        + "\n".join(items_xml)
        + "\n</items>\n"
    )


# ─── Moxy ruleset YAML ──────────────────────────────────────────────────


def to_moxy_config(project: Project) -> str:
    """Moxy (https://github.com/matank001/Moxy) ruleset.

    Moxy is an mITM proxy aimed at mobile apps; rules are YAML with a
    `match` predicate (URL substring or regex) and an action. We ship a
    log-only config that records every request hitting one of the
    discovered hosts. Users add `mutate`/`block` rules manually.
    """
    endpoints = _endpoints(project)
    hosts = sorted({urlparse(url).netloc for url in endpoints if urlparse(url).netloc})

    lines: list[str] = []
    lines.append("# Moxy ruleset · MEDUSA NEXUS export")
    lines.append(f"# project: {project.id}  package: {project.package_name}  version: {project.version_name}")
    lines.append(f"# generated: {datetime.now(UTC).isoformat()}")
    lines.append("")
    lines.append("listen: 0.0.0.0:8080")
    lines.append("rules:")
    if not hosts:
        lines.append("  # no hosts recovered from the APK yet")
    for host in hosts:
        lines.append(f"  - name: log {host}")
        lines.append("    match:")
        lines.append(f"      host: {host}")
        lines.append("    action: log")
    lines.append("")
    lines.append("# To enrich:")
    lines.append("# - replace `action: log` with `action: replace_response` and inline a body")
    lines.append("# - add `match.path: ^/v2/.*` to scope a rule")
    lines.append("# - add a `block` rule for analytics endpoints to compare app behaviour")
    return "\n".join(lines) + "\n"


# ─── shared blurb ──────────────────────────────────────────────────────


def _description_blurb(project: Project) -> str:
    surface = project.attack_surface
    if not surface:
        return "MEDUSA NEXUS export — no attack surface available."
    return (
        f"Endpoints recovered from {project.package_name} v{project.version_name} "
        f"({project.platform}) by MEDUSA NEXUS. "
        f"{len(surface.api_endpoints)} URLs, {len(surface.deeplinks)} deep links. "
        f"Every URL here is a candidate for testing — replay with auth headers from a real session, "
        f"flip GET → POST where appropriate, and let your proxy do the rest."
    )
