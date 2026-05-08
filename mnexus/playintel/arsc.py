"""ARSC — parser for Android compiled resource tables (``resources.arsc``).

``resources.arsc`` is the binary form of everything in ``res/values/*.xml``.
The Android runtime uses it to resolve ``R.string.foo`` etc. without
re-parsing XML, and Firebase / Maps / Crashlytics SDKs ship their
configuration as plain string resources. That makes ``resources.arsc`` the
single richest source of credentials and project identifiers in any APK.

This module is a focused port of the Go reference implementation
(``pkg/googleplay/arsc.go``). It only extracts **simple string entries** —
enough to recover Firebase configuration and run secret-pattern matching
against every other resource string — and deliberately skips:

* Complex entries (style / array / plurals) — different layout, no
  ``Res_value`` to read.
* Compact entries (Android 14+) — value is packed into the entry header
  in a different encoding; misreading would produce garbage.
* Non-string ``Res_value`` types (int, dimen, color, …) — irrelevant to
  credential discovery.

The format is documented only in AOSP's
``frameworks/base/libs/androidfw/include/androidfw/ResourceTypes.h``.
This implementation is correct against real-world APKs but is not a full
re-implementation of ``aapt2 dump resources``.

Output shape::

    parsed = parse_arsc(blob)
    parsed.project_id           # value of the "project_id" key, if present
    parsed.resources["google_api_key"]  # any string resource by key name
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# ─── Chunk types from AOSP ResourceTypes.h ─────────────────────────────────
_TYPE_STRING_POOL = 0x0001
_TYPE_TABLE = 0x0002
_TYPE_PACKAGE = 0x0200
_TYPE_TYPE = 0x0201
_TYPE_TYPESPEC = 0x0202

# ResTable_entry.flags (uint16)
_ENTRY_FLAG_COMPLEX = 0x0001
_ENTRY_FLAG_COMPACT = 0x0008

# ResTable_type.flags (uint8 at +9)
_TYPE_FLAG_SPARSE = 0x01

# Res_value dataType byte
_VALUE_TYPE_STRING = 0x03

# Sentinel for "no entry at this slot" in the dense offset array.
_NO_ENTRY = 0xFFFFFFFF


@dataclass(slots=True)
class ParsedArsc:
    """Result of parsing one ``resources.arsc`` blob.

    ``project_id`` is filled in only when a key string named ``"project_id"``
    is found in the resource table — the Firebase Gradle plugin stores it
    that way. ``resources`` is a flat ``key → value`` map of every simple
    string entry across all type chunks. Multiple entries with the same
    key (e.g. translations of the same resource) collapse into the last
    parsed value; that is acceptable for our use case where we only care
    about the existence and content of project-config strings.
    """

    project_id: str = ""
    resources: dict[str, str] = field(default_factory=dict)


# ─── Public entry point ────────────────────────────────────────────────────


def parse_arsc(data: bytes) -> ParsedArsc:
    """Parse an in-memory ``resources.arsc`` blob into a :class:`ParsedArsc`.

    Returns an empty :class:`ParsedArsc` (no exception) on any
    ill-formed input — credential scanners are expected to keep going
    even when an APK ships a partially corrupt resource table.
    """
    parsed = ParsedArsc()
    if len(data) < 12:
        return parsed

    res_type = _u16(data, 0)
    if res_type != _TYPE_TABLE:
        return parsed

    header_size = _u16(data, 2)
    pos = header_size

    # First chunk after the table header is the global string pool
    # (table values live here).
    global_strings, pos = _parse_string_pool(data, pos)

    # Then 1+ Package chunks. Real APKs only ship one (the user package,
    # 0x7F) but the loop below tolerates more.
    while pos + 8 <= len(data):
        chunk_type = _u16(data, pos)
        chunk_size = _u32(data, pos + 4)
        if chunk_size <= 0 or pos + chunk_size > len(data):
            break

        if chunk_type == _TYPE_PACKAGE:
            _parse_package(data, pos, chunk_size, global_strings, parsed)

        pos += chunk_size

    return parsed


# ─── Package + Type chunk parsing ──────────────────────────────────────────


def _parse_package(
    data: bytes,
    pkg_pos: int,
    pkg_size: int,
    global_strings: list[str],
    parsed: ParsedArsc,
) -> None:
    """Walk the per-package key string pool and every Type chunk inside it."""
    pkg_header_size = _u16(data, pkg_pos + 2)

    # Per-package key string pool (resource names: "app_name",
    # "google_api_key", …). Offset is at +276 in the package header for
    # the standard layout AOSP ships.
    if pkg_pos + 280 > len(data):
        return
    key_strings_offset = _u32(data, pkg_pos + 276)
    keys, _ = _parse_string_pool(data, pkg_pos + key_strings_offset)

    # Locate the index of "project_id" in the key pool so the matching
    # entry value can be promoted to ParsedArsc.project_id.
    project_id_key_index = -1
    for i, k in enumerate(keys):
        if k == "project_id":
            project_id_key_index = i
            break

    sub_pos = pkg_pos + pkg_header_size
    pkg_end = pkg_pos + pkg_size
    while sub_pos + 8 <= pkg_end:
        sub_type = _u16(data, sub_pos)
        sub_size = _u32(data, sub_pos + 4)
        if sub_size <= 0 or sub_pos + sub_size > pkg_end:
            break

        if sub_type == _TYPE_TYPE:
            _parse_type_chunk(
                data,
                sub_pos,
                sub_size,
                keys,
                global_strings,
                project_id_key_index,
                parsed,
            )
        # _TYPE_TYPESPEC chunks declare per-entry flag overrides; we don't
        # need them to read values, so skip silently.

        sub_pos += sub_size


def _parse_type_chunk(  # noqa: C901 — parser branches stay together
    data: bytes,
    sub_pos: int,
    sub_size: int,
    keys: list[str],
    global_strings: list[str],
    project_id_key_index: int,
    parsed: ParsedArsc,
) -> None:
    """Iterate every entry in one ``ResTable_type`` chunk.

    Handles both the dense (uint32-per-slot) and sparse
    (idx+offset/4 pair) offset arrays. Skips entries that are flagged
    COMPLEX or COMPACT — their trailing bytes are not a plain
    ``Res_value`` and would deserialize to nonsense.
    """
    type_header_size = _u16(data, sub_pos + 2)
    type_flags = data[sub_pos + 9]
    res_count = _u32(data, sub_pos + 12)
    entries_start = _u32(data, sub_pos + 16)
    sparse = bool(type_flags & _TYPE_FLAG_SPARSE)
    sub_end = sub_pos + sub_size

    for i in range(res_count):
        # Resolve where this entry lives.
        if sparse:
            off_pos = sub_pos + type_header_size + (i * 4)
            if off_pos + 4 > sub_end:
                break
            entry_off = _u16(data, off_pos + 2) * 4
        else:
            off_pos = sub_pos + type_header_size + (i * 4)
            if off_pos + 4 > sub_end:
                break
            raw = _u32(data, off_pos)
            if raw == _NO_ENTRY:
                continue
            entry_off = raw

        actual = sub_pos + entries_start + entry_off
        if actual + 8 > sub_end:
            break

        e_size = _u16(data, actual)
        e_flags = _u16(data, actual + 2)

        # Complex entries store a parent + map[]; compact entries pack
        # the value bytes inside the header itself. Either way the layout
        # below would misread them.
        if e_flags & (_ENTRY_FLAG_COMPLEX | _ENTRY_FLAG_COMPACT):
            continue

        e_key = _u32(data, actual + 4)
        if e_key < 0 or e_key >= len(keys):
            continue
        key_name = keys[e_key]

        val_pos = actual + e_size
        if val_pos + 8 > sub_end:
            continue

        v_type = data[val_pos + 3]
        v_data = _u32(data, val_pos + 4)
        if v_type != _VALUE_TYPE_STRING:
            continue
        if v_data < 0 or v_data >= len(global_strings):
            continue

        value = global_strings[v_data]
        parsed.resources[key_name] = value
        if project_id_key_index != -1 and e_key == project_id_key_index:
            parsed.project_id = value


# ─── String pool ───────────────────────────────────────────────────────────


def _parse_string_pool(data: bytes, pos: int) -> tuple[list[str], int]:
    """Decode a ``ResStringPool`` chunk at ``pos``.

    Returns ``(strings, next_position)``. Slots that fail to decode keep
    their position in the returned list (as ``""``) so consumers that
    index by the original ``ResStringPool_ref`` keep resolving correctly.
    """
    if pos < 0 or pos + 28 > len(data):
        return [], pos

    chunk_type = _u16(data, pos)
    if chunk_type != _TYPE_STRING_POOL:
        return [], pos

    header_size = _u16(data, pos + 2)
    chunk_size = _u32(data, pos + 4)
    string_count = _u32(data, pos + 8)
    flags = _u32(data, pos + 16)
    string_start = _u32(data, pos + 20)

    if pos + chunk_size > len(data):
        return [], pos

    is_utf8 = bool(flags & (1 << 8))

    offsets: list[int] = [-1] * string_count
    for i in range(string_count):
        off_pos = pos + header_size + (i * 4)
        if off_pos + 4 > len(data):
            break
        offsets[i] = _u32(data, off_pos)

    strings: list[str] = [""] * string_count
    pool_data_start = pos + string_start
    chunk_end = pos + chunk_size

    for i, off in enumerate(offsets):
        if off < 0:
            continue
        s_pos = pool_data_start + off
        if s_pos < 0 or s_pos >= chunk_end or s_pos >= len(data):
            continue

        if is_utf8:
            # UTF-8 layout: [u16-length-in-chars][u8-length-in-bytes][bytes][\0]
            _u16len, s_pos = _decode_len8(data, s_pos)
            byte_len, s_pos = _decode_len8(data, s_pos)
            if 0 <= s_pos and s_pos + byte_len <= len(data):
                strings[i] = data[s_pos : s_pos + byte_len].decode("utf-8", errors="replace")
        else:
            # UTF-16-LE layout: [u16-length-in-chars][u16 chars][\0\0]
            char_len, s_pos = _decode_len16(data, s_pos)
            if 0 <= s_pos and s_pos + (char_len * 2) <= len(data):
                strings[i] = data[s_pos : s_pos + (char_len * 2)].decode(
                    "utf-16-le", errors="replace"
                )

    return strings, pos + chunk_size


# ─── Bounded little-endian primitive readers ───────────────────────────────


def _u16(data: bytes, pos: int) -> int:
    if pos < 0 or pos + 2 > len(data):
        return 0
    return struct.unpack_from("<H", data, pos)[0]


def _u32(data: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(data):
        return 0
    return struct.unpack_from("<I", data, pos)[0]


def _decode_len8(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a UTF-8 string-pool variable-length prefix.

    The high bit of the first byte signals a 2-byte length: in that case
    the value is ``((b0 & 0x7F) << 8) | b1`` and 2 bytes are consumed.
    """
    if pos < 0 or pos >= len(data):
        return 0, pos
    val = data[pos]
    if val & 0x80:
        if pos + 1 >= len(data):
            return val & 0x7F, pos + 1
        return ((val & 0x7F) << 8) | data[pos + 1], pos + 2
    return val, pos + 1


def _decode_len16(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a UTF-16 string-pool variable-length prefix (little-endian).

    Mirrors :func:`_decode_len8` but on uint16s. The high bit of the
    first uint16 signals a 4-byte length.
    """
    if pos < 0 or pos + 2 > len(data):
        return 0, pos
    val = _u16(data, pos)
    if val & 0x8000:
        if pos + 4 > len(data):
            return val & 0x7FFF, pos + 2
        return ((val & 0x7FFF) << 16) | _u16(data, pos + 2), pos + 4
    return val, pos + 2
