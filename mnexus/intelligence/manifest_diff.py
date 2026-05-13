"""Per-version AttackSurface diff — Mango's ``do_diff`` for Nexus projects.

Mango's diff compares raw AndroidManifest.xml text across stored
versions of the same app. Nexus has something better: an already-parsed
``AttackSurface`` with components, deeplinks, permissions, and SSL
posture broken out. Diffing those gives the analyst a far more useful
changelog than a textual diff of XML strings.

Output shape::

    {
      "components": {
        "added":   [{name, type, exported, unprotected}, …],
        "removed": [...],
        "changed": [{name, before, after, fields: [...]}, …],
      },
      "deeplinks":      {"added": [...], "removed": [...]},
      "permissions":    {"added": [...], "removed": [...]},
      "url_schemes":    {"added": [...], "removed": [...]},
      "ssl_pinning":    {
        "detected_before": bool, "detected_after": bool,
        "library_before":  str | None, "library_after":  str | None,
      },
      "native_libraries": {"added": [...], "removed": [...]},
      "summary": {
        "components_added": int, "components_removed": int,
        "deeplinks_added": int,  "deeplinks_removed": int,
        "permissions_added": int, "permissions_removed": int,
        "ssl_pinning_changed": bool,
        "any_changes": bool,
      },
    }

All shapes degrade to ``[]`` on missing inputs so the renderer never
has to nil-check.
"""

from __future__ import annotations

from typing import Any


# ─── helpers ──────────────────────────────────────────────────────────


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return list(value)


def _comp_key(c: dict[str, Any]) -> str:
    """Identity for a component diff — name + type so an Activity named
    'MainActivity' doesn't collide with a Service of the same name."""
    return f"{c.get('component_type', '?')}::{c.get('name', '')}"


def _comp_fields(c: dict[str, Any]) -> dict[str, Any]:
    """Project a component down to the fields we compare for ``changed``."""
    return {
        "name": c.get("name", ""),
        "component_type": c.get("component_type", ""),
        "exported": bool(c.get("exported", False)),
        "unprotected": bool(c.get("unprotected", False)),
        "permission": c.get("permission") or "",
    }


def _diff_set(before: list, after: list) -> dict[str, list]:
    """Diff two list-like values by simple set semantics (suitable for
    deeplinks / permissions / url_schemes — values are hashable strings)."""
    bset = set(before or [])
    aset = set(after or [])
    return {
        "added":   sorted(aset - bset),
        "removed": sorted(bset - aset),
    }


def _diff_components(before: list[dict], after: list[dict]) -> dict[str, list]:
    """Components diff with a ``changed`` slot that captures the *kind*
    of mutation (export flag flipped, permission gate added/removed, …)."""
    bmap = { _comp_key(c): c for c in before or [] }
    amap = { _comp_key(c): c for c in after or [] }

    added_keys = sorted(amap.keys() - bmap.keys())
    removed_keys = sorted(bmap.keys() - amap.keys())
    shared_keys = sorted(bmap.keys() & amap.keys())

    changed: list[dict[str, Any]] = []
    for k in shared_keys:
        bf = _comp_fields(bmap[k])
        af = _comp_fields(amap[k])
        diff_fields = [
            name for name in ("exported", "unprotected", "permission")
            if bf[name] != af[name]
        ]
        if diff_fields:
            changed.append({
                "name": af["name"],
                "type": af["component_type"],
                "before": bf,
                "after": af,
                "fields": diff_fields,
            })

    return {
        "added":   [_comp_fields(amap[k]) for k in added_keys],
        "removed": [_comp_fields(bmap[k]) for k in removed_keys],
        "changed": changed,
    }


def _native_key(lib: dict[str, Any]) -> str:
    return f"{lib.get('arch', '?')}::{lib.get('path', lib.get('name', ''))}"


def _diff_native(before: list[dict], after: list[dict]) -> dict[str, list]:
    bmap = {_native_key(lib): lib for lib in before or []}
    amap = {_native_key(lib): lib for lib in after or []}
    added_keys = sorted(amap.keys() - bmap.keys())
    removed_keys = sorted(bmap.keys() - amap.keys())
    return {
        "added":   [amap[k] for k in added_keys],
        "removed": [bmap[k] for k in removed_keys],
    }


# ─── public entry point ───────────────────────────────────────────────


def diff_surfaces(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """Diff two AttackSurface dicts (typically the ``attack_surface``
    field on a Project payload). Either side can be ``None`` — the
    helper synthesises an empty surface so the diff still produces a
    coherent ``all added`` / ``all removed`` view.
    """
    before = before or {}
    after = after or {}

    components = _diff_components(
        _as_list(before.get("exported_components")),
        _as_list(after.get("exported_components")),
    )
    deeplinks      = _diff_set(_as_list(before.get("deeplinks")),    _as_list(after.get("deeplinks")))
    permissions    = _diff_set(_as_list(before.get("permissions")),  _as_list(after.get("permissions")))
    url_schemes    = _diff_set(_as_list(before.get("url_schemes")),  _as_list(after.get("url_schemes")))
    native         = _diff_native(_as_list(before.get("native_libraries")), _as_list(after.get("native_libraries")))

    ssl = {
        "detected_before": bool(before.get("ssl_pinning_detected")),
        "detected_after":  bool(after.get("ssl_pinning_detected")),
        "library_before":  before.get("ssl_pinning_library"),
        "library_after":   after.get("ssl_pinning_library"),
    }
    ssl_changed = (
        ssl["detected_before"] != ssl["detected_after"]
        or ssl["library_before"] != ssl["library_after"]
    )

    summary = {
        "components_added":     len(components["added"]),
        "components_removed":   len(components["removed"]),
        "components_changed":   len(components["changed"]),
        "deeplinks_added":      len(deeplinks["added"]),
        "deeplinks_removed":    len(deeplinks["removed"]),
        "permissions_added":    len(permissions["added"]),
        "permissions_removed":  len(permissions["removed"]),
        "url_schemes_added":    len(url_schemes["added"]),
        "url_schemes_removed":  len(url_schemes["removed"]),
        "native_added":         len(native["added"]),
        "native_removed":       len(native["removed"]),
        "ssl_pinning_changed":  ssl_changed,
    }
    summary["any_changes"] = any(v for v in summary.values() if isinstance(v, (int, bool)))

    return {
        "components":       components,
        "deeplinks":        deeplinks,
        "permissions":      permissions,
        "url_schemes":      url_schemes,
        "native_libraries": native,
        "ssl_pinning":      ssl,
        "summary":          summary,
    }
