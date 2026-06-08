"""Diff two projects' Finding sets — "what got fixed and what showed up?"

Where ``manifest_diff`` compares the static surface (components,
deeplinks, permissions), this module compares the actual Findings — so
the analyst sees the security delta between v1.2 and v1.3, not just
the manifest-surface delta.

Identity rule: two findings are "the same" when they share
``(title, location)``. Severity drift on a same-identity finding counts
as a change, not as an add+remove. Remediation changes (one version
ships fix-text the other didn't) are also flagged as a change.

Output shape::

    {
      "added":   [Finding-dict, …],
      "removed": [Finding-dict, …],
      "changed": [{"key": "<title>::<location>",
                   "before": Finding-dict, "after": Finding-dict,
                   "fields": ["severity", "remediation"]}, …],
      "summary": {
        "added_count": int, "removed_count": int, "changed_count": int,
        "severity_escalated": int,  # changes where new severity is worse
        "severity_relieved": int,   # changes where new severity is better
        "remediation_added": int,
        "any_changes": bool,
      },
    }
"""

from __future__ import annotations

from typing import Any

# Severity rank — lower index = worse (matches the existing playbook
# ordering and Severity.severity_weight implicitly).
_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


def _identity(finding: dict[str, Any]) -> str:
    """Stable key for a finding — title + location."""
    title = finding.get("title", "") or ""
    location = finding.get("location", "") or ""
    return f"{title}::{location}"


def _severity_rank(sev: str | None) -> int:
    """Higher number = less severe. Unknown sev → end of the line."""
    try:
        return _SEVERITY_ORDER.index((sev or "info").lower())
    except ValueError:
        return len(_SEVERITY_ORDER)


def _as_dicts(findings: Any) -> list[dict[str, Any]]:
    """Accept Finding objects or plain dicts; coerce to dicts."""
    if not findings:
        return []
    out: list[dict[str, Any]] = []
    for f in findings:
        if isinstance(f, dict):
            out.append(f)
            continue
        if hasattr(f, "model_dump"):
            out.append(f.model_dump(mode="json"))
            continue
        # Pydantic v1 fallback / general objects.
        if hasattr(f, "dict"):
            out.append(f.dict())
            continue
        out.append({k: getattr(f, k, None) for k in ("id", "title", "severity", "location", "remediation", "category", "source_engine")})
    return out


def findings_diff(
    base: Any,
    head: Any,
) -> dict[str, Any]:
    """Diff two finding lists. Both inputs accept Findings or dicts.

    Returns the structured diff documented in this module's docstring.
    """
    base_list = _as_dicts(base)
    head_list = _as_dicts(head)

    base_by_key = {_identity(f): f for f in base_list}
    head_by_key = {_identity(f): f for f in head_list}

    added_keys = sorted(head_by_key.keys() - base_by_key.keys())
    removed_keys = sorted(base_by_key.keys() - head_by_key.keys())
    shared_keys = sorted(base_by_key.keys() & head_by_key.keys())

    added = [head_by_key[k] for k in added_keys]
    removed = [base_by_key[k] for k in removed_keys]

    changed: list[dict[str, Any]] = []
    severity_escalated = 0
    severity_relieved = 0
    remediation_added = 0

    for key in shared_keys:
        bf = base_by_key[key]
        hf = head_by_key[key]
        diff_fields: list[str] = []
        if (bf.get("severity") or "") != (hf.get("severity") or ""):
            diff_fields.append("severity")
        if (bf.get("remediation") or "") != (hf.get("remediation") or ""):
            diff_fields.append("remediation")
        if (bf.get("evidence") or "") != (hf.get("evidence") or ""):
            diff_fields.append("evidence")
        if not diff_fields:
            continue
        if "severity" in diff_fields:
            br = _severity_rank(bf.get("severity"))
            hr = _severity_rank(hf.get("severity"))
            if hr < br:
                severity_escalated += 1
            elif hr > br:
                severity_relieved += 1
        if "remediation" in diff_fields and not (bf.get("remediation") or "") and (hf.get("remediation") or ""):
            remediation_added += 1
        changed.append({
            "key": key,
            "before": bf,
            "after": hf,
            "fields": diff_fields,
        })

    summary = {
        "added_count":         len(added),
        "removed_count":       len(removed),
        "changed_count":       len(changed),
        "severity_escalated":  severity_escalated,
        "severity_relieved":   severity_relieved,
        "remediation_added":   remediation_added,
    }
    summary["any_changes"] = any(v for v in summary.values() if isinstance(v, int))

    return {
        "added":   added,
        "removed": removed,
        "changed": changed,
        "summary": summary,
    }
