"""MCP driver — expose MedusaNexus as a Model Context Protocol server.

This is the cable between Nexus and AI assistants (Claude Desktop,
Cursor, Zed, …). Speaks JSON-RPC 2.0 over stdio, the protocol MCP
defines. No ``mcp`` Python dep — the wire format is small enough to
implement directly, which keeps the venv lean and avoids version
pinning headaches.

What the assistant can do once wired:

  * ``list_projects``        — every Project in the workspace
  * ``get_project``          — risk score + finding counts + surface
  * ``list_findings``        — filtered by severity / category
  * ``get_finding``          — full body + evidence + remediation
  * ``list_recipes``         — built-ins + Medusa modules
  * ``decode_android_flag``  — Mango flag decoder
  * ``manifest_diff``        — surface delta against the prior scan
  * ``findings_diff``        — security delta against the prior scan
  * ``firebase_probe``       — standalone RTDB / Firestore / Storage check

Every tool hits the local FastAPI server (default ``localhost:8765``)
via ``urllib.request`` — we don't reach into the orchestrator
directly because the assistant may be talking to a remote Nexus
instance via the same MCP entry point.

Wire it in ``~/Library/Application Support/Claude/claude_desktop_config.json``:

::

    {
      "mcpServers": {
        "medusa-nexus": {
          "command": "mnexus",
          "args": ["mcp-serve"],
          "env": {"MNEXUS_API_BASE": "http://127.0.0.1:8765"}
        }
      }
    }

Then ask the assistant: "list every CRITICAL finding on PRJ-355151DF".
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("mnexus.mcp")

# MCP protocol revision we declare. The wire format is stable enough
# that older / newer clients still talk to us; the assistant downgrades
# gracefully when it doesn't recognise a capability.
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "medusa-nexus"
SERVER_VERSION = "0.1.0"


def _api_base() -> str:
    return os.environ.get("MNEXUS_API_BASE", "http://127.0.0.1:8765").rstrip("/")


def _api(method: str, path: str, *, body: Any = None, form: dict | None = None, timeout: float = 60.0) -> tuple[int, Any]:
    """Hit the local Nexus API and return ``(status, json_or_text)``."""
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(_api_base() + path, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(payload)
            except json.JSONDecodeError:
                return r.status, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            return exc.code, json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return exc.code, payload or str(exc)
    except urllib.error.URLError as exc:
        return 0, f"Nexus API not reachable at {_api_base()}: {exc.reason}"


# ─── tool catalogue ────────────────────────────────────────────────────


# Tool descriptors as MCP expects them. Each entry maps to a handler
# function defined below. Keep schemas tight — the assistant infers
# usage from the description + properties.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_projects",
        "description": "List every Project in the workspace with risk scores and finding counts.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_project",
        "description": "Get one Project's full overview: risk score, severity counts, attack surface summary.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "e.g. PRJ-355151DF"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "list_findings",
        "description": "List findings for a project, optionally filtered by severity (critical|high|medium|low|info) or category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "severity":   {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                "category":   {"type": "string"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_finding",
        "description": "Fetch one finding by id including evidence and remediation. Looked up globally — project_id is optional context for the response envelope.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "e.g. FND-7B22A91C"},
                "project_id": {"type": "string", "description": "optional — passed through to the response"},
            },
            "required": ["finding_id"],
        },
    },
    {
        "name": "list_recipes",
        "description": "Browse the recipe catalogue (built-ins + Medusa modules) with optional platform filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["android", "ios", "both"]},
                "category": {"type": "string", "description": "substring match against the category field"},
            },
        },
    },
    {
        "name": "decode_android_flag",
        "description": "Decode an Android Intent / Receiver / PendingIntent / Content flag integer into symbolic names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "value":      {"type": "string", "description": "hex (0x…), decimal, octal (0o…), or binary (0b…)"},
                "namespaces": {"type": "array", "items": {"type": "string"}, "description": "subset of intent | receiver | pending_intent | content"},
            },
            "required": ["value"],
        },
    },
    {
        "name": "manifest_diff",
        "description": "Diff a project's static surface against the most recent prior scan of the same package.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "against":    {"type": "string", "description": "explicit base project id (optional)"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "findings_diff",
        "description": "Diff a project's findings against the most recent prior scan of the same package.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "against":    {"type": "string"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "firebase_probe",
        "description": "Run RTDB / Firestore / Storage probes against a Firebase config (no APK scan needed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id":     {"type": "string", "description": "Firebase project id (not the Nexus PRJ-…)"},
                "api_key":        {"type": "string"},
                "storage_bucket": {"type": "string"},
                "database_url":   {"type": "string"},
            },
        },
    },
    {
        "name": "doctor",
        "description": "Engine health check — which engines are installed, configured, and reachable.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _handle_list_projects(_: dict[str, Any]) -> dict[str, Any]:
    status, body = _api("GET", "/v1/projects")
    return {"status": status, "projects": body}


def _handle_get_project(args: dict[str, Any]) -> dict[str, Any]:
    pid = args["project_id"]
    status, body = _api("GET", f"/v1/projects/{urllib.parse.quote(pid)}")
    return {"status": status, "project": body}


def _handle_list_findings(args: dict[str, Any]) -> dict[str, Any]:
    pid = args["project_id"]
    params = {k: v for k, v in args.items() if k in ("severity", "category") and v}
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    status, body = _api("GET", f"/v1/projects/{urllib.parse.quote(pid)}/findings{qs}")
    return {"status": status, "findings": body}


def _handle_get_finding(args: dict[str, Any]) -> dict[str, Any]:
    # The API resolves a finding by id alone (it walks every project),
    # so we pass project_id only for the response envelope — the lookup
    # itself is global.
    fid = args["finding_id"]
    status, body = _api("GET", f"/v1/findings/{urllib.parse.quote(fid)}")
    return {"status": status, "project_id": args.get("project_id"), "finding": body}


def _handle_list_recipes(args: dict[str, Any]) -> dict[str, Any]:
    qs = ""
    if args.get("platform"):
        qs = "?" + urllib.parse.urlencode({"platform": args["platform"]})
    status, body = _api("GET", f"/v1/recipes{qs}")
    if isinstance(body, list) and args.get("category"):
        needle = args["category"].lower()
        body = [r for r in body if needle in (r.get("category") or "").lower()]
    return {"status": status, "recipes": body}


def _handle_decode_android_flag(args: dict[str, Any]) -> dict[str, Any]:
    payload = {"value": args["value"]}
    if args.get("namespaces"):
        payload["namespaces"] = args["namespaces"]
    status, body = _api("POST", "/v1/mango/decode-flags", body=payload)
    return {"status": status, "decoded": body}


def _handle_manifest_diff(args: dict[str, Any]) -> dict[str, Any]:
    pid = args["project_id"]
    qs = ""
    if args.get("against"):
        qs = "?" + urllib.parse.urlencode({"against": args["against"]})
    status, body = _api("GET", f"/v1/projects/{urllib.parse.quote(pid)}/manifest-diff{qs}")
    return {"status": status, "diff": body}


def _handle_findings_diff(args: dict[str, Any]) -> dict[str, Any]:
    pid = args["project_id"]
    qs = ""
    if args.get("against"):
        qs = "?" + urllib.parse.urlencode({"against": args["against"]})
    status, body = _api("GET", f"/v1/projects/{urllib.parse.quote(pid)}/findings-diff{qs}")
    return {"status": status, "diff": body}


def _handle_firebase_probe(args: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in args.items() if k in ("project_id", "api_key", "storage_bucket", "database_url") and v}
    status, body = _api("POST", "/v1/firebase/probe", body=payload)
    return {"status": status, "probe": body}


def _handle_doctor(_: dict[str, Any]) -> dict[str, Any]:
    status, body = _api("GET", "/v1/doctor")
    return {"status": status, "doctor": body}


_HANDLERS = {
    "list_projects":       _handle_list_projects,
    "get_project":         _handle_get_project,
    "list_findings":       _handle_list_findings,
    "get_finding":         _handle_get_finding,
    "list_recipes":        _handle_list_recipes,
    "decode_android_flag": _handle_decode_android_flag,
    "manifest_diff":       _handle_manifest_diff,
    "findings_diff":       _handle_findings_diff,
    "firebase_probe":      _handle_firebase_probe,
    "doctor":              _handle_doctor,
}


# ─── JSON-RPC dispatch ─────────────────────────────────────────────────


def dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC request, return the response dict (or None
    for notifications without an id field)."""
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "notifications/initialized":
        # No response — it's a notification.
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {}) or {}
        handler = _HANDLERS.get(tool_name)
        if handler is None:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32602, "message": f"unknown tool: {tool_name}"},
            }
        try:
            result = handler(tool_args)
        except KeyError as exc:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32602, "message": f"missing argument: {exc}"},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32603, "message": f"{exc.__class__.__name__}: {exc}"},
            }
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        # Pretty-print so the assistant has structured data
                        # it can quote back; keep it under a reasonable size.
                        "text": json.dumps(result, indent=2, default=str)[:60_000],
                    }
                ],
            },
        }

    # Unknown method.
    return {
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def serve_stdio() -> int:
    """Read JSON-RPC messages from stdin, dispatch, write to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"parse error: {exc}"},
            }) + "\n")
            sys.stdout.flush()
            continue
        response = dispatch(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0
