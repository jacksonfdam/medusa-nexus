"""Pure-Python protobuf wire-format codec — no `protobuf` library required.

The Google Play protocol exchanges protobuf messages on a few endpoints
(checkin, delivery, details, purchase). We don't need a full
schema-driven runtime: the messages we touch have stable, documented
field numbers, and we only consume a handful of fields. So instead of
adding the `protobuf` package as a dependency, this module implements
just the wire format from the spec at
https://protobuf.dev/programming-guides/encoding/.

Two layers:

* :class:`MessageBuilder` — encode a message field-by-field. Methods
  are named after the wire type that gets emitted, not the proto
  scalar type, so the caller decides how to map (e.g. ``add_varint``
  for both int32 and int64; ``add_fixed64`` for fixed64 / double).
* :func:`iter_fields` / :func:`find_field` / :func:`find_path` —
  decode side. Walks a buffer yielding ``(field_num, wire_type,
  payload)`` tuples; helpers find a specific field or follow a
  field-number path through nested length-delimited sub-messages.

Wire types covered:

==== ============= =====================================================
code name          payload representation
==== ============= =====================================================
 0   varint        ``int`` (already decoded — not zigzag, callers do that)
 1   fixed64       8-byte little-endian ``bytes``
 2   length-delim  ``bytes`` (sub-message, string, bytes field)
 5   fixed32       4-byte little-endian ``bytes``
==== ============= =====================================================

Wire types 3 and 4 (start-group / end-group) are deprecated in proto3
and we never see them on the Play endpoints.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from typing import Any

# Wire-type constants — exposed for readability at call sites.
WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_FIXED32 = 5


# ─── Encoding ─────────────────────────────────────────────────────────────


def encode_varint(value: int) -> bytes:
    """Encode an unsigned int as a protobuf varint.

    Negative ``value`` is encoded as its 64-bit two's-complement
    representation, matching the on-the-wire behaviour of int32 /
    int64 fields holding negative numbers.
    """
    if value < 0:
        # Convert to 64-bit two's complement so it round-trips through
        # the int64 decoder. (proto3 int32/int64 negative values
        # use 10 bytes on the wire.)
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def encode_zigzag32(value: int) -> int:
    """ZigZag-encode a signed 32-bit int — used by sint32 fields."""
    return ((value << 1) ^ (value >> 31)) & 0xFFFFFFFF


def encode_zigzag64(value: int) -> int:
    """ZigZag-encode a signed 64-bit int — used by sint64 fields."""
    return ((value << 1) ^ (value >> 63)) & 0xFFFFFFFFFFFFFFFF


def _tag(field_num: int, wire_type: int) -> bytes:
    return encode_varint((field_num << 3) | wire_type)


class MessageBuilder:
    """Build a protobuf message by appending fields one at a time.

    Methods don't validate; the caller is responsible for matching wire
    types to the schema. Repeated fields are produced by calling the
    same ``add_*`` method multiple times with the same ``field_num``.
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    # ─── primitive emitters ───

    def add_varint(self, field_num: int, value: int) -> MessageBuilder:
        """Emit any varint-typed field (int32, int64, uint32, uint64,
        bool, enum). Negative ints are 64-bit two's-complement.
        """
        self._buf.extend(_tag(field_num, WIRE_VARINT))
        self._buf.extend(encode_varint(value))
        return self

    def add_bool(self, field_num: int, value: bool) -> MessageBuilder:
        return self.add_varint(field_num, 1 if value else 0)

    def add_fixed32(self, field_num: int, value: int) -> MessageBuilder:
        self._buf.extend(_tag(field_num, WIRE_FIXED32))
        self._buf.extend(struct.pack("<I", value & 0xFFFFFFFF))
        return self

    def add_fixed64(self, field_num: int, value: int) -> MessageBuilder:
        self._buf.extend(_tag(field_num, WIRE_FIXED64))
        self._buf.extend(struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))
        return self

    def add_string(self, field_num: int, value: str) -> MessageBuilder:
        return self.add_bytes(field_num, value.encode("utf-8"))

    def add_bytes(self, field_num: int, value: bytes) -> MessageBuilder:
        self._buf.extend(_tag(field_num, WIRE_LENGTH_DELIMITED))
        self._buf.extend(encode_varint(len(value)))
        self._buf.extend(value)
        return self

    def add_message(self, field_num: int, sub: MessageBuilder | bytes) -> MessageBuilder:
        """Emit a sub-message at ``field_num``.

        ``sub`` is either another :class:`MessageBuilder` (we serialize
        it in place) or a pre-encoded ``bytes`` buffer (rare —
        primarily for tests that stash a fixture).
        """
        if isinstance(sub, MessageBuilder):
            payload = sub.to_bytes()
        else:
            payload = sub
        return self.add_bytes(field_num, payload)

    def add_repeated_string(self, field_num: int, values: list[str]) -> MessageBuilder:
        for v in values:
            self.add_string(field_num, v)
        return self

    def to_bytes(self) -> bytes:
        return bytes(self._buf)


# ─── Decoding ─────────────────────────────────────────────────────────────


def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode one varint starting at ``pos``.

    Returns ``(value, next_pos)``. Negative values come back as their
    64-bit two's-complement positive form; sign-extension is the
    caller's responsibility.
    """
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        # Protobuf caps varints at 10 bytes (64 bits + continuation).
        if shift >= 70:
            raise ValueError("varint exceeds 10-byte limit")
    raise ValueError("truncated varint")


def decode_zigzag32(value: int) -> int:
    """Reverse :func:`encode_zigzag32`. Returns a signed int."""
    v = value & 0xFFFFFFFF
    return (v >> 1) ^ -(v & 1)


def decode_zigzag64(value: int) -> int:
    v = value & 0xFFFFFFFFFFFFFFFF
    return (v >> 1) ^ -(v & 1)


def varint_to_signed_int32(value: int) -> int:
    """Re-interpret a varint payload as int32 (handles 2's-complement)."""
    v = value & 0xFFFFFFFFFFFFFFFF  # int32 negatives are stored as int64 on the wire
    if v >= (1 << 63):
        v -= 1 << 64
    if v >= (1 << 31):
        v -= 1 << 32
    if v < -(1 << 31):
        v += 1 << 32
    return v


def varint_to_signed_int64(value: int) -> int:
    v = value & 0xFFFFFFFFFFFFFFFF
    if v >= (1 << 63):
        v -= 1 << 64
    return v


def iter_fields(data: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield every ``(field_num, wire_type, payload)`` in ``data``.

    Payload shape per wire type:

    * ``WIRE_VARINT`` → ``int`` (raw varint value, not sign-corrected)
    * ``WIRE_FIXED64`` → ``bytes`` (8 bytes)
    * ``WIRE_LENGTH_DELIMITED`` → ``bytes`` (the payload only, prefix
      stripped)
    * ``WIRE_FIXED32`` → ``bytes`` (4 bytes)

    Fields that use unsupported wire types raise ``ValueError``.
    """
    pos = 0
    while pos < len(data):
        tag, pos = decode_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7
        if wire_type == WIRE_VARINT:
            value, pos = decode_varint(data, pos)
            yield field_num, wire_type, value
        elif wire_type == WIRE_FIXED64:
            yield field_num, wire_type, data[pos : pos + 8]
            pos += 8
        elif wire_type == WIRE_LENGTH_DELIMITED:
            length, pos = decode_varint(data, pos)
            yield field_num, wire_type, data[pos : pos + length]
            pos += length
        elif wire_type == WIRE_FIXED32:
            yield field_num, wire_type, data[pos : pos + 4]
            pos += 4
        else:
            raise ValueError(f"unsupported wire type {wire_type} at field {field_num}")


def find_field(data: bytes, field_num: int) -> Any:
    """Return the *first* payload for ``field_num``, or ``None``.

    For varint fields the returned value is an ``int`` (raw); for
    length-delimited fields it's ``bytes``. Repeated fields require
    iterating ``iter_fields`` directly.
    """
    for fn, _wt, payload in iter_fields(data):
        if fn == field_num:
            return payload
    return None


def find_all_fields(data: bytes, field_num: int) -> list[Any]:
    """Return every payload for ``field_num`` (use for ``repeated``)."""
    return [payload for fn, _wt, payload in iter_fields(data) if fn == field_num]


def find_path(data: bytes, *field_path: int) -> Any:
    """Walk a chain of length-delimited fields and return the final
    payload, or ``None`` if any link is missing.

    ``find_path(buf, 1, 21, 2)`` reads ``buf.payload(1).deliveryResponse(21).appDeliveryData(2)``.

    Tolerates partial malformations: if an intermediate payload is a
    bare string / varint that the caller thought was a sub-message,
    or a sub-message that happens to be truncated at the boundary,
    we return ``None`` rather than raising.
    """
    cur: Any = data
    for fn in field_path:
        if not isinstance(cur, (bytes, bytearray)):
            return None
        try:
            cur = find_field(cur, fn)
        except ValueError:
            return None
        if cur is None:
            return None
    return cur


def get_string(data: bytes, field_num: int) -> str:
    """Read a string field. Empty if missing."""
    payload = find_field(data, field_num)
    if not isinstance(payload, (bytes, bytearray)):
        return ""
    return bytes(payload).decode("utf-8", errors="replace")


def get_int(data: bytes, field_num: int) -> int:
    """Read a varint field as a (possibly signed) Python int. 0 if missing."""
    payload = find_field(data, field_num)
    if not isinstance(payload, int):
        return 0
    return varint_to_signed_int64(payload)


def get_uint64_fixed(data: bytes, field_num: int) -> int:
    """Read a fixed64 field as an unsigned 64-bit int. 0 if missing."""
    payload = find_field(data, field_num)
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != 8:
        return 0
    return struct.unpack("<Q", bytes(payload))[0]
