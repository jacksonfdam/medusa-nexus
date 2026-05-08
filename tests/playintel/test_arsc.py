"""ARSC parser tests.

Combines defensive tests on the safety paths (empty/short/non-table
inputs must not raise) with a positive round-trip test that builds a
minimal but valid ``resources.arsc`` blob and feeds it through the
parser.

The encoder helper :func:`_build_minimal_arsc` is intentionally small
— it produces the smallest valid ARSC the parser will accept. Anyone
reading these tests can reason about what's in the byte stream without
opening an APK.
"""

from __future__ import annotations

import struct

from mnexus.playintel.arsc import parse_arsc


# ─── Defensive parses ─────────────────────────────────────────────────────


def test_parse_empty_returns_empty_struct() -> None:
    """An empty buffer must not raise — scanners must keep going."""
    result = parse_arsc(b"")
    assert result.project_id == ""
    assert result.resources == {}


def test_parse_too_short_returns_empty_struct() -> None:
    result = parse_arsc(b"\x00\x00\x00\x00")
    assert result.project_id == ""
    assert result.resources == {}


def test_parse_non_table_chunk_returns_empty_struct() -> None:
    """First chunk must be ``RES_TABLE_TYPE`` (0x0002); anything else is a no-op."""
    blob = b"\x01\x00\x0c\x00" + b"\x00" * 8
    result = parse_arsc(blob)
    assert result.project_id == ""
    assert result.resources == {}


# ─── Round-trip: synthetic ARSC blob ──────────────────────────────────────


def test_round_trip_minimal_arsc_recovers_project_and_keys() -> None:
    """Build a tiny ARSC, parse it, recover the project_id and keys."""
    # Two string-type resource entries: project_id and google_api_key.
    arsc = _build_minimal_arsc(
        global_strings=[
            "synthetic-test-project",
            "AIzaSyzABCdef0123456789xyzABCdef01234567",
        ],
        keys=["project_id", "google_api_key"],
        # entries: (key_index_in_keys_pool, value_index_in_global_pool)
        entries=[(0, 0), (1, 1)],
    )

    parsed = parse_arsc(arsc)
    assert parsed.project_id == "synthetic-test-project"
    assert parsed.resources["project_id"] == "synthetic-test-project"
    assert parsed.resources["google_api_key"].startswith("AIza")


def test_round_trip_arsc_no_project_id_key() -> None:
    """A resource table with no `project_id` key still resolves
    other resources but leaves :attr:`ParsedArsc.project_id` empty.
    """
    arsc = _build_minimal_arsc(
        global_strings=["AIzaSyzABCdef0123456789xyzABCdef01234567"],
        keys=["google_api_key"],
        entries=[(0, 0)],
    )
    parsed = parse_arsc(arsc)
    assert parsed.project_id == ""
    assert parsed.resources["google_api_key"].startswith("AIza")


# ─── Synthetic ARSC encoder (UTF-8 string pool flavor) ────────────────────


def _build_minimal_arsc(
    *,
    global_strings: list[str],
    keys: list[str],
    entries: list[tuple[int, int]],
) -> bytes:
    """Build a minimal-but-valid ``resources.arsc`` blob.

    Layout produced::

        ResTable header (12B)
        Global StringPool chunk (UTF-8 flagged)
        Package chunk
            (type strings pool — single entry "string")
            (key strings pool — `keys`)
            Type chunk
                offset array (one slot per entry)
                entries: 8B header + 8B Res_value per entry

    All string pools use the UTF-8 short-prefix encoding (1-byte char
    length + 1-byte byte length + bytes + NUL) so each string must be
    at most 127 ASCII characters. Sufficient for tests.
    """
    sp_global = _build_utf8_string_pool(global_strings)
    sp_type = _build_utf8_string_pool(["string"])
    sp_key = _build_utf8_string_pool(keys)
    type_chunk = _build_type_chunk(entries=entries, key_count=len(keys))
    package = _build_package(sp_type=sp_type, sp_key=sp_key, type_chunk=type_chunk)

    table_size = 12 + len(sp_global) + len(package)
    table_header = struct.pack(
        "<HHII",
        0x0002,      # type = RES_TABLE_TYPE
        12,          # header size (matches len(table_header))
        table_size,  # total table chunk size
        1,           # package_count
    )
    return table_header + sp_global + package


def _build_utf8_string_pool(strings: list[str]) -> bytes:
    """Encode a UTF-8 string pool chunk.

    Each entry is laid out as ``[u8 char_len][u8 byte_len][bytes][\\0]``
    — the AOSP short-prefix UTF-8 form. ``char_len`` for ASCII strings
    equals ``byte_len``; non-ASCII isn't needed for tests.
    """
    pieces: list[bytes] = []
    offsets: list[int] = []
    cursor = 0
    for s in strings:
        encoded = s.encode("utf-8")
        if len(encoded) >= 0x80 or len(s) >= 0x80:
            raise ValueError(
                "test helper only supports strings <128 bytes — increase if needed"
            )
        offsets.append(cursor)
        entry = bytes([len(s), len(encoded)]) + encoded + b"\x00"
        pieces.append(entry)
        cursor += len(entry)

    data = b"".join(pieces)
    # 4-byte alignment of the data block keeps consumers happy.
    pad = (-len(data)) % 4
    data += b"\x00" * pad

    header_size = 28
    offset_array = struct.pack(f"<{len(strings)}I", *offsets) if strings else b""
    strings_start = header_size + len(offset_array)
    chunk_size = strings_start + len(data)
    flags = 1 << 8  # UTF-8 flag

    header = struct.pack(
        "<HHIIIIII",
        0x0001,         # RES_STRING_POOL_TYPE
        header_size,
        chunk_size,
        len(strings),   # string_count
        0,              # style_count
        flags,
        strings_start,
        0,              # styles_start
    )
    return header + offset_array + data


def _build_package(*, sp_type: bytes, sp_key: bytes, type_chunk: bytes) -> bytes:
    """Encode a Package chunk with a type-string pool, key-string pool,
    and one type chunk inside it.
    """
    package_header_size = 288
    type_strings_offset = package_header_size
    key_strings_offset = type_strings_offset + len(sp_type)
    body = sp_type + sp_key + type_chunk
    chunk_size = package_header_size + len(body)

    # The package header is 288 bytes total: type(2) + hdrsize(2) +
    # chunksize(4) + id(4) + name(256) + type_off(4) + last_pub_type(4)
    # + key_off(4) + last_pub_key(4) + type_id_offset(4).
    name_blob = (b"com.test\x00" * 32)[:256]  # 128 utf-16 chars worth
    header = struct.pack(
        "<HHII",
        0x0200,            # RES_TABLE_PACKAGE_TYPE
        package_header_size,
        chunk_size,
        0x7F,              # package id (user app)
    )
    header += name_blob
    header += struct.pack(
        "<IIIII",
        type_strings_offset,
        1,                  # last_public_type
        key_strings_offset,
        2,                  # last_public_key
        0,                  # type_id_offset
    )
    assert len(header) == package_header_size, (
        f"package header size mismatch: {len(header)} vs {package_header_size}"
    )
    return header + body


def _build_type_chunk(*, entries: list[tuple[int, int]], key_count: int) -> bytes:
    """Encode one Type chunk with `entries` simple string entries.

    Each entry resolves to ``Res_value`` of type STRING (0x03), with
    the data field pointing at the supplied global-string index.
    Sparse mode is not used.
    """
    _ = key_count  # Not encoded into the chunk itself, but documents intent.
    type_header_size = 20
    res_count = len(entries)
    offset_array_size = res_count * 4
    entries_start = type_header_size + offset_array_size
    entry_blob = bytearray()
    offsets: list[int] = []
    for key_idx, value_idx in entries:
        offsets.append(len(entry_blob))
        entry_header = struct.pack(
            "<HHI",
            8,         # entry size (header is 8 bytes)
            0,         # entry flags
            key_idx,   # ResStringPool_ref into the key pool
        )
        # Res_value: size(2)=8, res0(1)=0, dataType(1)=0x03 STRING, data(4)
        res_value = struct.pack("<HBBI", 8, 0, 0x03, value_idx)
        entry_blob.extend(entry_header + res_value)

    body = struct.pack(f"<{res_count}I", *offsets) + bytes(entry_blob)
    chunk_size = type_header_size + len(body)
    header = struct.pack(
        "<HHIBBHII",
        0x0201,           # RES_TABLE_TYPE_TYPE
        type_header_size,
        chunk_size,
        1,                # type_id (1 = "string" — matches type pool index)
        0,                # flags (no SPARSE)
        0,                # padding
        res_count,
        entries_start,
    )
    return header + body
