#!/usr/bin/env python3
"""Auto-generate MDX reference pages at build time.

Three outputs land in `pages/reference/`:

  * cli.mdx        ← walks the Click command tree (mnexus + subcommands)
  * repl.mdx       ← reads the SLASH_COMMANDS dispatch table
  * api/<tag>.mdx  ← one page per FastAPI tag, plus an api/index.mdx

This script is invoked by `npm run prebuild` (and `predev`) so the
reference cannot drift relative to the code. If the script fails the
build still proceeds with the *previous* generated files — Vercel sees
a non-zero exit, but the dev experience locally is forgiving.

Run manually:

    python3 docs-site/scripts/gen_reference.py
"""

from __future__ import annotations

import importlib
import json
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# Nextra 4 + App Router puts MDX under content/ (not pages/).
PAGES = Path(__file__).resolve().parents[1] / "content" / "reference"
PAGES.mkdir(parents=True, exist_ok=True)
(PAGES / "api").mkdir(parents=True, exist_ok=True)

# Make `import mnexus` work even when run from the docs-site dir.
sys.path.insert(0, str(ROOT))


def _safe(value: Any) -> str:
    """MDX-safe rendering for table cells — collapses newlines, escapes pipes + braces."""
    return _mdx_escape(str(value)).replace("|", "\\|").replace("\n", " ")


def _mdx_escape(text: str) -> str:
    """Escape characters MDX treats as JSX/expression syntax.

    Docstrings on FastAPI routes routinely contain `{"json": "blobs"}`
    and `{all,3rd,system}`-style braces. MDX 3 sees those as JSX
    expressions and hands them to acorn, which then explodes on the
    first non-JS character. Escape both braces and bare `<` so we
    can ship arbitrary prose without sanitising the source.
    """
    return (
        str(text)
        .replace("{", "\\{")
        .replace("}", "\\}")
        # Bare `<` is MDX's open-tag sigil. Escape unless it's clearly
        # part of `<= ` / `<- ` / `< 3` (still safe to escape there,
        # acorn doesn't care).
        .replace("<", "\\<")
    )


# ─── CLI walker ────────────────────────────────────────────────────────


def gen_cli() -> None:
    """Walk every Click command + group registered under `mnexus.cli`."""
    try:
        import click

        from mnexus.cli import cli as root
    except Exception as exc:  # noqa: BLE001
        _write_stub("cli.mdx", "CLI reference", exc)
        return

    lines: list[str] = []
    lines.append("---")
    lines.append("title: CLI reference")
    lines.append("---")
    lines.append("")
    lines.append("# CLI reference")
    lines.append("")
    lines.append(
        "Auto-generated from the live Click command tree at build time. "
        "If a flag isn't listed here it doesn't exist — either add it to the source "
        "or stop looking. To verify locally:"
    )
    lines.append("")
    lines.append("```bash")
    lines.append("mnexus --help")
    lines.append("```")
    lines.append("")

    def render(cmd: click.Command, path: list[str], depth: int = 2) -> None:
        # Click names the root group after its function (cli); the user
        # sees `mnexus` on the command line. Override the heading at the
        # root so the page reads naturally.
        full = " ".join(path) if path else ""
        heading = f"`mnexus{(' ' + full) if full else ''}`"
        lines.append(f"{'#' * depth} {heading}")
        lines.append("")
        if cmd.help:
            lines.append(_mdx_escape(cmd.help.strip()))
            lines.append("")

        # Synopsis
        usage_pieces = ["mnexus", *path]
        if isinstance(cmd, click.Group):
            usage_pieces.append("<subcommand>")
        else:
            for p in cmd.params:
                if isinstance(p, click.Argument):
                    usage_pieces.append(f"<{p.name}>")
        lines.append("```bash")
        lines.append(" ".join(usage_pieces))
        lines.append("```")
        lines.append("")

        # Options table
        opts = [p for p in cmd.params if isinstance(p, click.Option)]
        if opts:
            lines.append("| flag | type | default | description |")
            lines.append("| ---- | ---- | ------- | ----------- |")
            for o in opts:
                flag = " / ".join(f"`{n}`" for n in o.opts)
                typ = (o.type.name or "").upper() if hasattr(o.type, "name") else ""
                default = "—" if o.default in (None, "") else f"`{o.default}`"
                desc = _safe(o.help or "")
                lines.append(f"| {flag} | {typ or '—'} | {default} | {desc} |")
            lines.append("")

        # Recurse into groups
        if isinstance(cmd, click.Group):
            for sub_name in sorted(cmd.commands.keys()):
                render(cmd.commands[sub_name], [*path, sub_name], depth=min(depth + 1, 5))

    render(root, [], depth=2)

    (PAGES / "cli.mdx").write_text("\n".join(lines), encoding="utf-8")


# ─── REPL walker ───────────────────────────────────────────────────────


def gen_repl() -> None:
    """Pull the slash-command table out of `mnexus.cli.SLASH_COMMANDS`."""
    try:
        from mnexus.cli import SLASH_COMMANDS
    except Exception as exc:  # noqa: BLE001
        _write_stub("repl.mdx", "REPL slash commands", exc)
        return

    lines: list[str] = []
    lines.append("---")
    lines.append("title: REPL slash commands")
    lines.append("---")
    lines.append("")
    lines.append("# REPL slash commands")
    lines.append("")
    lines.append(
        "Auto-generated from `SLASH_COMMANDS` in `mnexus/cli.py`. Launch the "
        "REPL with bare `mnexus` and type `/help` for the same table inside "
        "the terminal."
    )
    lines.append("")
    lines.append("| command | what it does |")
    lines.append("| ------- | ------------ |")

    # Group aliases together — `play-accounts → play-account`, etc.
    by_handler: dict[int, list[str]] = defaultdict(list)
    for name, fn in SLASH_COMMANDS.items():
        by_handler[id(fn)].append(name)

    seen: set[int] = set()
    for name, fn in SLASH_COMMANDS.items():
        if id(fn) in seen:
            continue
        seen.add(id(fn))
        names = sorted(by_handler[id(fn)], key=len)
        primary, *aliases = names
        # Pull the first line of the docstring as the description.
        doc = (fn.__doc__ or "").strip().splitlines()
        desc = doc[0] if doc else ""
        # Strip leading backtick-name from docstrings like "`/scan <apk>` — …".
        if desc.startswith("`"):
            try:
                desc = desc.split("—", 1)[1].strip()
            except IndexError:
                pass
        alias_str = ""
        if aliases:
            alias_str = " *(aliases: " + ", ".join(f"`/{a}`" for a in aliases) + ")*"
        lines.append(f"| `/{primary}`{alias_str} | {_safe(desc)} |")
    lines.append("")
    lines.append("> Tip: prefix-matching works — `/doc` is `/doctor`, `/find` is `/findings`.")
    lines.append("")

    (PAGES / "repl.mdx").write_text("\n".join(lines), encoding="utf-8")


# ─── API walker — FastAPI OpenAPI ──────────────────────────────────────


def gen_api() -> None:
    """One MDX page per FastAPI tag (or 'misc' for untagged endpoints)."""
    try:
        # Import the app and ask for its OpenAPI schema. The app reads env
        # at import time — point it at a throwaway DB so we don't touch
        # the real one.
        import os
        import tempfile

        tmp = tempfile.mkdtemp(prefix="mnexus-docs-")
        os.environ.setdefault("MNEXUS_WORKSPACE", f"{tmp}/workspace")
        os.environ.setdefault("MNEXUS_DB_PATH", f"{tmp}/db.sqlite3")

        from mnexus.api import main as api_main

        importlib.reload(api_main)
        schema = api_main.app.openapi()
    except Exception as exc:  # noqa: BLE001
        _write_stub("api/index.mdx", "API reference", exc)
        return

    def derive_tag(path: str, op: dict) -> str:
        """Prefer explicit OpenAPI tag; otherwise derive from URL shape.

        /v1/projects/{id}/findings → 'projects'
        /v1/dynamic/sessions/…     → 'dynamic'
        /v1/firebase/probe         → 'firebase'
        / and /docs/*              → 'meta'
        """
        explicit = op.get("tags") or []
        if explicit:
            return explicit[0]
        parts = [p for p in path.split("/") if p and not p.startswith("{")]
        if not parts:
            return "meta"
        # /v1/<bucket>/... → bucket; /v1/<single> → single; / → meta.
        if parts[0] == "v1" and len(parts) >= 2:
            return parts[1]
        return parts[0]

    by_tag: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch"}:
                continue
            by_tag[derive_tag(path, op)].append((path, method.upper(), op))

    # Index
    idx: list[str] = [
        "---",
        "title: API reference",
        "---",
        "",
        "# API reference",
        "",
        "Auto-generated from the FastAPI OpenAPI schema at build time. "
        "Each endpoint here is wired to a live handler — the canonical, "
        "browsable version is at `/docs` on a running server.",
        "",
        "```bash",
        "mnexus serve --port 8765",
        "open http://127.0.0.1:8765/docs",
        "```",
        "",
        "## Tags",
        "",
        "| tag | endpoints |",
        "| --- | --------- |",
    ]
    for tag in sorted(by_tag):
        slug = _slug(tag)
        idx.append(f"| [`{tag}`](/reference/api/{slug}) | {len(by_tag[tag])} |")
    idx.append("")
    (PAGES / "api" / "index.mdx").write_text("\n".join(idx), encoding="utf-8")

    # Per-tag pages
    meta = {"index": "Overview"}
    for tag, rows in sorted(by_tag.items()):
        slug = _slug(tag)
        meta[slug] = tag
        out: list[str] = [
            "---",
            f"title: {tag} · API",
            "---",
            "",
            f"# `{tag}` endpoints",
            "",
            "Auto-generated from FastAPI OpenAPI. The descriptions are "
            "lifted from the route docstrings — edit the Python source, "
            "not this page.",
            "",
        ]
        for path, method, op in sorted(rows, key=lambda r: (r[0], r[1])):
            out.append(f"## `{method} {path}`")
            out.append("")
            summary = op.get("summary") or ""
            desc = op.get("description") or ""
            if summary:
                out.append(f"**{_mdx_escape(summary)}**")
                out.append("")
            if desc:
                out.append(_mdx_escape(desc.strip()))
                out.append("")
            params = op.get("parameters") or []
            if params:
                out.append("| parameter | in | required | type | description |")
                out.append("| --------- | -- | -------- | ---- | ----------- |")
                for p in params:
                    schema_obj = p.get("schema") or {}
                    typ = schema_obj.get("type") or schema_obj.get("$ref", "—")
                    out.append(
                        f"| `{p.get('name', '')}` | {p.get('in', '')} | "
                        f"{'yes' if p.get('required') else 'no'} | {typ} | "
                        f"{_safe(p.get('description', ''))} |"
                    )
                out.append("")
            request_body = op.get("requestBody")
            if request_body:
                content = list((request_body.get("content") or {}).keys())
                out.append(f"**Request body:** {', '.join(f'`{c}`' for c in content) or '—'}")
                out.append("")
            responses = op.get("responses") or {}
            if responses:
                out.append("**Responses:**")
                for code, body in sorted(responses.items()):
                    desc = body.get("description") or ""
                    out.append(f"- `{code}` — {_safe(desc)}")
                out.append("")
        (PAGES / "api" / f"{slug}.mdx").write_text("\n".join(out), encoding="utf-8")

    (PAGES / "api" / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _slug(tag: str) -> str:
    return (
        tag.lower()
        .replace(" ", "-")
        .replace("/", "-")
        .replace("_", "-")
    )


def _write_stub(name: str, title: str, exc: Exception) -> None:
    """Last-ditch fallback so the build never explodes when mnexus can't import.

    Crucially: we only write a stub when there's nothing already on disk.
    A previously generated reference page is better than a freshly-broken
    one — keeps the docs usable when the local Python env is misconfigured.
    """
    target = PAGES / name
    if target.exists():
        print(f"  skip stub for {name}: previous output preserved ({exc.__class__.__name__})")
        return
    body = (
        f"---\ntitle: {title}\n---\n\n"
        f"# {title}\n\n"
        f"> ⚠️ Auto-generation failed at build time:\n>\n"
        f"> ```\n> {exc.__class__.__name__}: {exc}\n> ```\n\n"
        "Run `python3 docs-site/scripts/gen_reference.py` locally and fix the import error.\n"
    )
    target.write_text(body, encoding="utf-8")


def main() -> int:
    print("→ generating CLI reference…")
    try:
        gen_cli()
    except Exception:
        traceback.print_exc()
    print("→ generating REPL reference…")
    try:
        gen_repl()
    except Exception:
        traceback.print_exc()
    print("→ generating API reference…")
    try:
        gen_api()
    except Exception:
        traceback.print_exc()
    print(f"✓ reference written to {PAGES.relative_to(PAGES.parents[1])}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
