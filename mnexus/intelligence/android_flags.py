"""Android flag decoder — Mango's ``decodeflag`` ported in.

Tables and the ``decode/describe`` helpers are lifted from ch0pin/medusa's
``libraries/android_flags.py`` (MIT-equivalent in that project) and adapted
to return structured dicts the API + UI can render — Mango's version
prints to stdout and isn't reusable from a service.

Three flag namespaces overlap (some bits mean different things in
different contexts), which is exactly why the analyst needs the decoder:
``0x00000001`` on an Intent is ``FLAG_GRANT_READ_URI_PERMISSION``; on a
ContentResolver query it's ``QUERY_SORT_DESCENDING``. Caller passes the
``kind`` they care about, or ``all`` to see every interpretation.
"""

from __future__ import annotations

from typing import Iterable


# Intent flags (Activity + Broadcast — Android maps them to the same int).
INTENT_FLAGS: dict[str, int] = {
    "FLAG_GRANT_READ_URI_PERMISSION":         0x00000001,
    "FLAG_GRANT_WRITE_URI_PERMISSION":        0x00000002,
    "FLAG_FROM_BACKGROUND":                   0x00000004,
    "FLAG_DEBUG_LOG_RESOLUTION":              0x00000008,
    "FLAG_EXCLUDE_STOPPED_PACKAGES":          0x00000010,
    "FLAG_INCLUDE_STOPPED_PACKAGES":          0x00000020,
    "FLAG_GRANT_PERSISTABLE_URI_PERMISSION":  0x00000040,
    "FLAG_GRANT_PREFIX_URI_PERMISSION":       0x00000080,
    "FLAG_DIRECT_BOOT_AUTO":                  0x00000100,
    "FLAG_IGNORE_EPHEMERAL":                  0x00000200,
    "FLAG_ACTIVITY_NO_HISTORY":               0x40000000,
    "FLAG_ACTIVITY_SINGLE_TOP":               0x20000000,
    "FLAG_ACTIVITY_NEW_TASK":                 0x10000000,
    "FLAG_ACTIVITY_MULTIPLE_TASK":            0x08000000,
    "FLAG_ACTIVITY_CLEAR_TOP":                0x04000000,
    "FLAG_ACTIVITY_FORWARD_RESULT":           0x02000000,
    "FLAG_ACTIVITY_PREVIOUS_IS_TOP":          0x01000000,
    "FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS":     0x00800000,
    "FLAG_ACTIVITY_BROUGHT_TO_FRONT":         0x00400000,
    "FLAG_ACTIVITY_RESET_TASK_IF_NEEDED":     0x00200000,
    "FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY":    0x00100000,
    "FLAG_ACTIVITY_NEW_DOCUMENT":             0x00080000,
    "FLAG_ACTIVITY_NO_USER_ACTION":           0x00040000,
    "FLAG_ACTIVITY_REORDER_TO_FRONT":         0x00020000,
    "FLAG_ACTIVITY_NO_ANIMATION":             0x00010000,
    "FLAG_ACTIVITY_CLEAR_TASK":               0x00008000,
    "FLAG_ACTIVITY_TASK_ON_HOME":             0x00004000,
    "FLAG_ACTIVITY_RETAIN_IN_RECENTS":        0x00002000,
}

# Broadcast receiver flags — collide on bit positions with activity flags,
# kept in a separate namespace so the decoder labels them honestly.
RECEIVER_FLAGS: dict[str, int] = {
    "FLAG_RECEIVER_REGISTERED_ONLY":          0x40000000,
    "FLAG_RECEIVER_REPLACE_PENDING":          0x20000000,
    "FLAG_RECEIVER_FOREGROUND":               0x10000000,
    "FLAG_RECEIVER_NO_ABORT":                 0x08000000,
    "FLAG_RECEIVER_EXCLUDE_BACKGROUND":       0x00800000,
    "FLAG_RECEIVER_INCLUDE_BACKGROUND":       0x00400000,
    "FLAG_RECEIVER_VISIBLE_TO_INSTANT_APPS":  0x00200000,
}

PENDING_INTENT_FLAGS: dict[str, int] = {
    "FLAG_ONE_SHOT":                          0x40000000,
    "FLAG_NO_CREATE":                         0x20000000,
    "FLAG_CANCEL_CURRENT":                    0x10000000,
    "FLAG_UPDATE_CURRENT":                    0x08000000,
    "FLAG_IMMUTABLE":                         0x04000000,
    "FLAG_MUTABLE":                           0x02000000,
}

CONTENT_FLAGS: dict[str, int] = {
    # URI-grant modes (same bit positions as Intent flags — a security
    # gotcha worth surfacing on its own).
    "FLAG_GRANT_READ_URI_PERMISSION":         0x00000001,
    "FLAG_GRANT_WRITE_URI_PERMISSION":        0x00000002,
    "FLAG_GRANT_PERSISTABLE_URI_PERMISSION":  0x00000040,
    "FLAG_GRANT_PREFIX_URI_PERMISSION":       0x00000080,
    "QUERY_SORT_DESCENDING":                  0x00000001,
    "QUERY_SORT_ASCENDING":                   0x00000002,
    "RESOLVER_USE_CREDENTIALS":               0x00000004,
    "RESOLVER_IGNORE_SECURITY":               0x00000008,
    "CONTEXT_INCLUDE_CODE":                   0x00000001,
    "CONTEXT_IGNORE_SECURITY":                0x00000002,
    "CONTEXT_RESTRICTED":                     0x00000004,
}


# Dispatch table the API exposes — the value's namespace is operator-
# selected ("intent" / "receiver" / "pending_intent" / "content" / "all").
_NAMESPACES: dict[str, dict[str, int]] = {
    "intent":         INTENT_FLAGS,
    "receiver":       RECEIVER_FLAGS,
    "pending_intent": PENDING_INTENT_FLAGS,
    "content":        CONTENT_FLAGS,
}


def parse_flag_value(raw: str | int) -> int:
    """Accept ``0x10000000``, ``"0x10000000"``, ``"268435456"``, ``"0o…"``.

    Anything that fails to parse raises ValueError. Empty / whitespace
    strings also raise so the caller can 400 cleanly.
    """
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"unsupported flag input type: {type(raw).__name__}")
    s = raw.strip()
    if not s:
        raise ValueError("flag value is empty")
    # int(s, 0) auto-detects base from the 0x/0o/0b prefix; falls back
    # to base 10 otherwise.
    return int(s, 0)


def decode_one(value: int, table: dict[str, int]) -> list[str]:
    """Return the symbolic names whose bits are set in ``value``."""
    return [name for name, bit in table.items() if value & bit]


def decode(value: int, namespaces: Iterable[str] | None = None) -> dict[str, list[str]]:
    """Decode ``value`` against the requested namespaces.

    ``namespaces=None`` returns every interpretation — useful when the
    analyst doesn't know the source context yet. Passing a list like
    ``["intent", "receiver"]`` narrows the result. Unknown namespace
    names are silently dropped (the API layer validates upstream).
    """
    if namespaces is None:
        keys = list(_NAMESPACES.keys())
    else:
        keys = [k for k in namespaces if k in _NAMESPACES]
    out: dict[str, list[str]] = {}
    for ns in keys:
        out[ns] = decode_one(value, _NAMESPACES[ns])
    return out


def supported_namespaces() -> list[str]:
    return list(_NAMESPACES.keys())
