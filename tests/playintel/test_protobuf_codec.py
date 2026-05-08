"""Protobuf wire-format codec tests.

The codec is the foundation under PlayClient; if it's wrong, the
entire Play protocol path silently misbehaves. Cover varint edges,
length-delimited round-trip, signed-int re-interpretation, fixed
widths, repeated fields, find_path traversal, and a synthetic
ResponseWrapper that mimics the real `/fdfe/delivery` response shape.
"""

from __future__ import annotations

import struct

import pytest

from mnexus.playintel.protobuf_codec import (
    MessageBuilder,
    decode_varint,
    decode_zigzag32,
    decode_zigzag64,
    encode_varint,
    encode_zigzag32,
    encode_zigzag64,
    find_all_fields,
    find_field,
    find_path,
    get_int,
    get_string,
    get_uint64_fixed,
    iter_fields,
    varint_to_signed_int32,
    varint_to_signed_int64,
)


# ─── Varint ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected_len"),
    [(0, 1), (127, 1), (128, 2), (16383, 2), (16384, 3), (2**40, 6), (2**63 - 1, 9)],
)
def test_varint_round_trip(value: int, expected_len: int) -> None:
    encoded = encode_varint(value)
    assert len(encoded) == expected_len
    decoded, next_pos = decode_varint(encoded, 0)
    assert decoded == value
    assert next_pos == expected_len


def test_varint_negative_uses_64_bit_two_complement() -> None:
    """Negative ints must encode to 10 bytes via 64-bit 2's complement."""
    encoded = encode_varint(-1)
    assert len(encoded) == 10
    decoded, _ = decode_varint(encoded, 0)
    assert varint_to_signed_int64(decoded) == -1


def test_varint_truncated_raises() -> None:
    """A buffer that ends mid-varint must raise, not silently return."""
    with pytest.raises(ValueError, match="truncated varint"):
        decode_varint(b"\x80\x80", 0)


def test_varint_overlong_raises() -> None:
    """A varint that needs more than 10 bytes is invalid per spec."""
    overlong = b"\xff" * 11
    with pytest.raises(ValueError, match="exceeds 10-byte"):
        decode_varint(overlong, 0)


# ─── Zigzag ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [0, 1, -1, 2147483647, -2147483648])
def test_zigzag32_round_trip(value: int) -> None:
    assert decode_zigzag32(encode_zigzag32(value)) == value


@pytest.mark.parametrize("value", [0, 1, -1, 2**63 - 1, -(2**63)])
def test_zigzag64_round_trip(value: int) -> None:
    assert decode_zigzag64(encode_zigzag64(value)) == value


# ─── Sign-correction helpers ──────────────────────────────────────────────


def test_varint_to_signed_int32_handles_negative_wire_form() -> None:
    """int32 negative values come over the wire as 10-byte unsigned."""
    encoded = encode_varint(-42 & 0xFFFFFFFFFFFFFFFF)
    raw, _ = decode_varint(encoded, 0)
    assert varint_to_signed_int32(raw) == -42


def test_varint_to_signed_int64_passes_positive_through() -> None:
    raw, _ = decode_varint(encode_varint(123456789), 0)
    assert varint_to_signed_int64(raw) == 123456789


# ─── Builder + Reader round-trip ──────────────────────────────────────────


def test_round_trip_varint_string_message() -> None:
    """A representative mixed message survives encode → iterate."""
    inner = MessageBuilder().add_varint(1, 99).add_string(2, "leaf")
    outer = (
        MessageBuilder()
        .add_varint(1, 42)
        .add_string(2, "hello")
        .add_message(3, inner)
        .add_bool(4, True)
    )
    buf = outer.to_bytes()
    fields = list(iter_fields(buf))
    assert fields[0] == (1, 0, 42)
    assert fields[1][0] == 2 and bytes(fields[1][2]) == b"hello"
    # Sub-message is length-delimited; we expect to be able to parse
    # the payload again recursively.
    assert fields[2][0] == 3
    assert get_int(bytes(fields[2][2]), 1) == 99
    assert get_string(bytes(fields[2][2]), 2) == "leaf"
    # Bool comes back as a varint payload.
    assert fields[3] == (4, 0, 1)


def test_repeated_fields_via_find_all() -> None:
    """Repeated entries with the same field number stack."""
    b = MessageBuilder()
    b.add_string(7, "first")
    b.add_string(7, "second")
    b.add_string(7, "third")
    payloads = [bytes(p).decode("utf-8") for p in find_all_fields(b.to_bytes(), 7)]
    assert payloads == ["first", "second", "third"]


def test_find_path_walks_nested_messages() -> None:
    """Mimics ResponseWrapper(1).payload(2).deliveryResponse(21).appDeliveryData(2)."""
    app_delivery = (
        MessageBuilder()
        .add_varint(1, 1024)
        .add_string(3, "https://cdn/test")
        .to_bytes()
    )
    delivery_response = MessageBuilder().add_message(2, app_delivery).to_bytes()
    payload = MessageBuilder().add_message(21, delivery_response).to_bytes()
    response_wrapper = MessageBuilder().add_message(1, payload).to_bytes()

    inner = find_path(response_wrapper, 1, 21, 2)
    assert isinstance(inner, (bytes, bytearray))
    assert get_int(bytes(inner), 1) == 1024
    assert get_string(bytes(inner), 3) == "https://cdn/test"


def test_find_path_returns_none_on_missing_link() -> None:
    """Any missing link in the chain returns None — never raises."""
    buf = MessageBuilder().add_string(1, "x").to_bytes()
    assert find_path(buf, 1, 2, 3) is None


def test_find_field_returns_first_match() -> None:
    """When a field is repeated, find_field returns the first one."""
    buf = MessageBuilder().add_string(1, "a").add_string(1, "b").to_bytes()
    payload = find_field(buf, 1)
    assert isinstance(payload, (bytes, bytearray))
    assert bytes(payload) == b"a"


# ─── Fixed widths ─────────────────────────────────────────────────────────


def test_fixed64_round_trip() -> None:
    """fixed64 — the wire format for AndroidCheckinResponse.androidId."""
    expected = 0x123456789ABCDEF0
    buf = MessageBuilder().add_fixed64(7, expected).to_bytes()
    assert get_uint64_fixed(buf, 7) == expected


def test_fixed32_round_trip_via_iter() -> None:
    buf = MessageBuilder().add_fixed32(5, 0xDEADBEEF).to_bytes()
    fields = list(iter_fields(buf))
    assert len(fields) == 1
    assert fields[0][0] == 5 and fields[0][1] == 5  # field=5, wire=5 (fixed32)
    assert struct.unpack("<I", bytes(fields[0][2]))[0] == 0xDEADBEEF


# ─── Reader robustness ────────────────────────────────────────────────────


def test_iter_fields_rejects_unsupported_wire_type() -> None:
    """Wire types 3/4 (deprecated groups) must raise — proto3 never emits them."""
    # Hand-craft tag for field=1, wire=3.
    bad = bytes([(1 << 3) | 3])
    with pytest.raises(ValueError, match="unsupported wire type"):
        list(iter_fields(bad))


def test_get_string_returns_empty_for_missing_field() -> None:
    assert get_string(b"", 1) == ""


def test_get_int_returns_zero_for_missing_field() -> None:
    assert get_int(b"", 1) == 0


def test_get_uint64_fixed_returns_zero_for_missing_field() -> None:
    assert get_uint64_fixed(b"", 1) == 0
