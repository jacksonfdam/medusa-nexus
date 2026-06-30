"""Workspace string locator — answer 'which file inside the APK contains X?'

The static engines surface findings with a generic ``location`` ("DEX
strings", "AndroidManifest.xml") because doing a deep file-tree grep on
every match would be expensive at ingest time. This module runs the
grep on demand: feed it a project id and a pattern (string or regex),
get back ``(file_path, line_number, line_text)`` tuples covering every
artefact the workspace contains.

Searched trees, in priority order:

  1. ``<workspace>/<pid>/jadx/``      — decompiled Java/Kotlin sources
  2. ``<workspace>/<pid>/apktool/``   — smali + decoded resources
  3. ``<workspace>/<pid>/apktool-manifest/``  — manifest cache
  4. ``<workspace>/secrets/<package>/``       — PlayIntel-saved bearing files
  5. ``<workspace>/upload-*-<name>``  — the original APK / IPA (raw bytes)

The walker filters by file extension to keep the search fast; the
default extension list covers everything a static finding would point
at (.java, .kt, .smali, .xml, .json, .js, .properties, .txt, .arsc).
Pass extensions=None to search every file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# File extensions that meaningfully contain readable strings. Filtering
# by extension keeps the walker fast on heavy projects (a release APK
# can have 100k+ files post-decompile).
_DEFAULT_EXTENSIONS: frozenset[str] = frozenset({
    ".java", ".kt", ".kts",      # decompiled JVM
    ".smali",                    # apktool output
    ".xml",                      # manifests, layouts, configs
    ".json", ".yaml", ".yml",    # resource bundles
    ".properties", ".txt",       # build configs, raw text
    ".js", ".ts", ".html",       # JS/TS bundles inside WebView assets
    ".plist",                    # iOS plists
    ".pem", ".crt",              # bundled certs
})

_MAX_RESULTS_DEFAULT = 200
_SNIPPET_CONTEXT = 80   # chars before/after the match in the snippet


@dataclass(frozen=True)
class LocatorHit:
    """One match. ``file`` is workspace-relative; ``line`` is 1-indexed."""

    file: str
    line: int
    snippet: str
    tree: str   # "jadx" | "apktool" | "manifest-cache" | "secrets" | "raw"


def find_in_workspace(
    workspace_dir: Path,
    project_id: str,
    pattern: str,
    *,
    regex: bool = False,
    case_insensitive: bool = False,
    max_results: int = _MAX_RESULTS_DEFAULT,
    extensions: Iterable[str] | None = None,
    package_name: str | None = None,
) -> list[LocatorHit]:
    """Walk the project's workspace tree for ``pattern``.

    ``pattern`` is matched as a substring by default. Pass ``regex=True``
    to interpret it as a Python regex. ``case_insensitive`` is honoured
    in both modes.

    ``max_results`` caps the output so a too-broad query doesn't melt
    memory. The walker stops as soon as the cap is hit; downstream
    callers see whether the cap tripped via ``len(hits) >= max_results``.

    ``package_name`` is optional — when provided, the walker also
    searches ``<workspace>/secrets/<package>/`` (PlayIntel-saved files).
    """
    if extensions is None:
        ext_set = _DEFAULT_EXTENSIONS
    elif not extensions:
        ext_set = frozenset()   # empty → search every file (no filter)
    else:
        ext_set = frozenset(e.lower() if e.startswith(".") else f".{e.lower()}"
                            for e in extensions)

    if regex:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            needle: re.Pattern[str] = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
    else:
        if case_insensitive:
            needle_lc = pattern.lower()
            needle = None  # signal substring path
        else:
            needle_lc = pattern
            needle = None

    project_dir = workspace_dir / project_id
    trees: list[tuple[str, Path]] = [
        ("jadx",           project_dir / "jadx"),
        ("apktool",        project_dir / "apktool"),
        ("manifest-cache", project_dir / "apktool-manifest"),
    ]
    if package_name:
        trees.append(("secrets", workspace_dir / "secrets" / package_name))

    hits: list[LocatorHit] = []
    for tree_name, root in trees:
        if not root.exists():
            continue
        for path in _walk_files(root, ext_set):
            try:
                # Read up to 2 MB per file. Larger files are unlikely
                # to host the kind of string we're looking for and the
                # cost of reading them dominates the walker's wall-clock.
                blob = path.read_bytes()[:2 * 1024 * 1024]
                text = blob.decode("utf-8", errors="replace")
            except OSError:
                continue

            for hit in _scan_text(text, needle, needle_lc if not regex else None, case_insensitive):
                rel = path.relative_to(workspace_dir).as_posix()
                hits.append(LocatorHit(
                    file=rel,
                    line=hit[0],
                    snippet=hit[1],
                    tree=tree_name,
                ))
                if len(hits) >= max_results:
                    return hits
    return hits


def _walk_files(root: Path, ext_set: frozenset[str]) -> Iterable[Path]:
    """rglob the tree, filter by extension. Skip the .git-like clutter."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ext_set and path.suffix.lower() not in ext_set:
            continue
        yield path


def _scan_text(
    text: str,
    needle_re: re.Pattern[str] | None,
    needle_lc: str | None,
    case_insensitive: bool,
) -> Iterable[tuple[int, str]]:
    """Yield (line_no, snippet) for every match in ``text``."""
    if needle_re is not None:
        for match in needle_re.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            yield line_no, _make_snippet(text, match.start(), match.end())
    else:
        haystack = text.lower() if case_insensitive else text
        assert needle_lc is not None
        start = 0
        while True:
            idx = haystack.find(needle_lc, start)
            if idx < 0:
                return
            line_no = text.count("\n", 0, idx) + 1
            yield line_no, _make_snippet(text, idx, idx + len(needle_lc))
            start = idx + 1


def _make_snippet(text: str, start: int, end: int) -> str:
    """Build a context window around the match."""
    a = max(0, start - _SNIPPET_CONTEXT)
    b = min(len(text), end + _SNIPPET_CONTEXT)
    snippet = text[a:b]
    # Collapse newlines so the snippet fits in a table row.
    snippet = snippet.replace("\n", " ⏎ ").replace("\r", "")
    if a > 0:
        snippet = "…" + snippet
    if b < len(text):
        snippet = snippet + "…"
    return snippet.strip()
