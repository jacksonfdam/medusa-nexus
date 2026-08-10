"""Source reader — pull one decompiled class out of the workspace on disk.

``workspace_locator`` answers *"which file contains X"*. This module answers
the other half an analyst — or an AI client driving the MCP server — keeps
asking: *"show me the whole class"* and *"what classes match <keyword>"*.
Together they turn a static report into something you can actually read
your way through, without ever launching a jadx GUI.

Nothing is decompiled here. A class only exists on disk if a prior pass ran
``jadx.decompile()`` / ``apktool d`` into ``<workspace>/<pid>/{jadx,apktool}/``.
A miss returns ``None`` — this module never fabricates a class body it can't
point at a file for.

The ``fqcn`` arrives from an MCP client, i.e. it is attacker-influenced. Every
resolved path is confined to the project subtree: ``..`` traversal, absolute
paths, and symlink escapes all resolve outside the root and are rejected
before a single byte is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# jadx emits Java by default and Kotlin when it can recover it. Smali is the
# apktool side. Anything past half a meg in a single class is already a
# reverse-engineering war crime, but we cap rather than refuse.
_JAVA_SUFFIXES: tuple[str, ...] = (".java", ".kt")
_MAX_SOURCE_BYTES = 512 * 1024


@dataclass(frozen=True)
class ClassSource:
    """One resolved class body. ``file`` is workspace-relative, posix."""

    fqcn: str
    file: str
    lang: str   # "java" | "kotlin" | "smali"
    text: str
    truncated: bool


@dataclass(frozen=True)
class ClassHit:
    """A class-name match from :func:`search_classes`."""

    fqcn: str
    file: str
    lang: str


def _valid_fqcn(fqcn: str | None) -> str | None:
    """Return a cleaned fqcn, or ``None`` if it isn't a plausible class name.

    ``$`` is allowed (inner classes); every other segment char must be
    identifier-safe, which is what keeps a path like ``../../etc/passwd``
    from ever surviving the split.
    """
    fqcn = (fqcn or "").strip().strip(".")
    if not fqcn:
        return None
    for seg in fqcn.split("."):
        if not seg or not seg.replace("$", "_").isidentifier():
            return None
    return fqcn


def _confined(candidate: Path, root: Path) -> Path | None:
    """Resolve ``candidate`` and hand it back only if it stays inside ``root``
    and is a regular file. Kills ``..``, absolute, and symlink escapes."""
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if resolved != root_resolved and root_resolved not in resolved.parents:
        return None
    return resolved if resolved.is_file() else None


def resolve_class_file(
    workspace_dir: Path,
    project_id: str,
    fqcn: str,
    fmt: str = "java",
) -> tuple[Path, str] | None:
    """Map ``fqcn`` to a decompiled file on disk. Returns ``(path, lang)``.

    ``fmt="java"`` walks the jadx tree (inner classes fold into their outer
    file); ``fmt="smali"`` walks every ``apktool/smali*`` directory. A fast
    candidate-path probe covers the canonical layouts; a confined ``rglob``
    fallback catches the rest without ever leaving the project subtree.
    """
    valid = _valid_fqcn(fqcn)
    if valid is None:
        return None
    rel = valid.replace(".", "/")
    project_dir = workspace_dir / project_id

    if fmt == "smali":
        base = project_dir / "apktool"
        if not base.exists():
            return None
        # apktool splits large apps into smali/, smali_classes2/, … smali_classesN/.
        for smali_root in sorted(base.glob("smali*")):
            hit = _confined(smali_root / f"{rel}.smali", base)
            if hit is not None:
                return hit, "smali"
        # Fallback: odd layout — match by leaf name, then confirm the full
        # package path so a same-named class in another package can't win.
        leaf = valid.rsplit(".", 1)[-1]
        for cand in base.rglob(f"{leaf}.smali"):
            if cand.as_posix().endswith(f"{rel}.smali"):
                hit = _confined(cand, base)
                if hit is not None:
                    return hit, "smali"
        return None

    # java/kotlin — inner classes (Outer$Inner) live in the outer file.
    outer = rel.split("$", 1)[0]
    jadx = project_dir / "jadx"
    if not jadx.exists():
        return None
    # Real jadx writes under sources/; minimal/test layouts drop the class
    # straight under jadx/. Probe both before paying for an rglob.
    for prefix in (jadx / "sources", jadx):
        for suffix in _JAVA_SUFFIXES:
            hit = _confined(prefix / f"{outer}{suffix}", jadx)
            if hit is not None:
                return hit, ("kotlin" if suffix == ".kt" else "java")
    leaf = outer.rsplit("/", 1)[-1]
    for suffix in _JAVA_SUFFIXES:
        for cand in jadx.rglob(f"{leaf}{suffix}"):
            if cand.as_posix().endswith(f"{outer}{suffix}"):
                hit = _confined(cand, jadx)
                if hit is not None:
                    return hit, ("kotlin" if suffix == ".kt" else "java")
    return None


def read_class_source(
    workspace_dir: Path,
    project_id: str,
    fqcn: str,
    fmt: str = "java",
    *,
    max_bytes: int = _MAX_SOURCE_BYTES,
) -> ClassSource | None:
    """Resolve ``fqcn`` and return its body, or ``None`` if it isn't on disk."""
    resolved = resolve_class_file(workspace_dir, project_id, fqcn, fmt)
    if resolved is None:
        return None
    path, lang = resolved
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    truncated = len(blob) > max_bytes
    text = blob[:max_bytes].decode("utf-8", errors="replace")
    return ClassSource(
        fqcn=_valid_fqcn(fqcn) or fqcn,
        file=path.relative_to(workspace_dir).as_posix(),
        lang=lang,
        text=text,
        truncated=truncated,
    )


def search_classes(
    workspace_dir: Path,
    project_id: str,
    keyword: str = "",
    *,
    fmt: str = "java",
    limit: int = 200,
) -> list[ClassHit]:
    """List decompiled classes whose fqcn contains ``keyword`` (empty = all).

    Matching is a case-insensitive substring over the fully-qualified name,
    deduped, capped at ``limit``. ``fmt`` picks the jadx (java) or apktool
    (smali) tree.
    """
    project_dir = workspace_dir / project_id

    roots: list[Path] = []
    if fmt == "smali":
        base = project_dir / "apktool"
        if base.exists():
            roots = sorted(base.glob("smali*"))
        suffixes: tuple[str, ...] = (".smali",)
    else:
        jadx = project_dir / "jadx"
        base = jadx / "sources" if (jadx / "sources").exists() else jadx
        if base.exists():
            roots = [base]
        suffixes = _JAVA_SUFFIXES

    kw = keyword.lower()
    seen: set[str] = set()
    out: list[ClassHit] = []
    for root in roots:
        for cand in root.rglob("*"):
            if not cand.is_file() or cand.suffix.lower() not in suffixes:
                continue
            fq = cand.relative_to(root).as_posix().rsplit(".", 1)[0].replace("/", ".")
            if kw and kw not in fq.lower():
                continue
            if fq in seen:
                continue
            seen.add(fq)
            lang = "smali" if fmt == "smali" else ("kotlin" if cand.suffix == ".kt" else "java")
            out.append(ClassHit(
                fqcn=fq,
                file=cand.relative_to(workspace_dir).as_posix(),
                lang=lang,
            ))
            if len(out) >= limit:
                return out
    return out
