"""Email + password → AAS token flow.

Full RSA decryption needs the matching private key (which Google
keeps), so we can't end-to-end-test the encryption against a known
plaintext. Instead the tests verify *structural* correctness:

* The GMS public-key blob parses to a 1024-bit modulus + 0x10001
  exponent (the canonical values).
* OAEP encoding of a known message with a fixed seed is deterministic
  — re-running yields identical bytes.
* The output of :func:`encrypt_credentials` has the documented layout
  (``0x00`` + 4-byte sha1 prefix + 128-byte ciphertext, base64-url).
* The HTTP shim's response parser recognises both successful
  ``Token=`` lines and the documented ``Error=`` codes.

Live ``/auth`` calls are mocked through :class:`httpx.MockTransport` so
the test suite stays offline.
"""

from __future__ import annotations

import base64
import hashlib

import httpx
import pytest

from mnexus.playintel.google_auth import (
    GOOGLE_GMS_PUBKEY_B64,
    GoogleAuthError,
    _mgf1_sha1,
    _oaep_encode,
    _parse_gms_pubkey,
    _parse_keyvalue_response,
    encrypt_credentials,
    mint_aas_token,
)


# ─── Public-key parsing ──────────────────────────────────────────────────


def test_gms_pubkey_parses_to_1024_bit_modulus_and_e_65537() -> None:
    pk = _parse_gms_pubkey()
    assert pk.n.bit_length() == 1024
    assert pk.key_size_bytes == 128
    assert pk.e == 0x10001  # standard public exponent


def test_gms_pubkey_raw_bytes_match_decoded_b64() -> None:
    pk = _parse_gms_pubkey()
    assert pk.raw == base64.b64decode(GOOGLE_GMS_PUBKEY_B64)


# ─── MGF1 + OAEP primitives ──────────────────────────────────────────────


def test_mgf1_sha1_known_vector() -> None:
    """RFC 8017 Appendix B.2.1 — first MGF1 chunk is sha1(seed || 0x00000000)."""
    seed = b"\x00" * 20
    expected_first_block = hashlib.sha1(seed + b"\x00\x00\x00\x00", usedforsecurity=False).digest()
    out = _mgf1_sha1(seed, 20)
    assert out == expected_first_block


def test_mgf1_extends_across_block_boundaries() -> None:
    """Output longer than one hash block concatenates Hash(seed||0), Hash(seed||1), …"""
    seed = b"abc"
    full = _mgf1_sha1(seed, 50)
    assert len(full) == 50
    block_a = hashlib.sha1(seed + b"\x00\x00\x00\x00", usedforsecurity=False).digest()
    block_b = hashlib.sha1(seed + b"\x00\x00\x00\x01", usedforsecurity=False).digest()
    block_c = hashlib.sha1(seed + b"\x00\x00\x00\x02", usedforsecurity=False).digest()
    assert full == (block_a + block_b + block_c)[:50]


def test_oaep_encode_is_deterministic_with_fixed_seed() -> None:
    """Same seed + message → same envelope bytes."""
    em1 = _oaep_encode(b"hello", 128, seed_override=b"\xa0" * 20)
    em2 = _oaep_encode(b"hello", 128, seed_override=b"\xa0" * 20)
    assert em1 == em2
    assert len(em1) == 128
    # First byte must always be 0x00 per RFC 8017 §7.1.1 step (i).
    assert em1[0] == 0


def test_oaep_envelope_first_byte_is_zero_random_seed() -> None:
    """Even with a real random seed, the leading 0x00 is mandatory."""
    em = _oaep_encode(b"hi", 128)
    assert em[0] == 0
    assert len(em) == 128


def test_oaep_rejects_message_too_long() -> None:
    """k - 2*hLen - 2 = 86 for 1024-bit RSA + SHA-1; 200 bytes must fail."""
    with pytest.raises(ValueError, match="too long"):
        _oaep_encode(b"x" * 200, 128)


def test_oaep_rejects_wrong_seed_length() -> None:
    with pytest.raises(ValueError, match="seed must be"):
        _oaep_encode(b"x", 128, seed_override=b"\xff" * 5)


# ─── encrypt_credentials envelope layout ─────────────────────────────────


def test_encrypt_credentials_envelope_layout() -> None:
    """Envelope = 0x00 || sha1(pubkey)[:4] || 128-byte ciphertext, base64-url."""
    pk = _parse_gms_pubkey()
    blob = encrypt_credentials("user@example.com", "p4ssw0rd")
    raw = base64.urlsafe_b64decode(blob)
    assert len(raw) == 1 + 4 + pk.key_size_bytes
    assert raw[0] == 0x00
    expected_prefix = hashlib.sha1(pk.raw, usedforsecurity=False).digest()[:4]
    assert raw[1:5] == expected_prefix


def test_encrypt_credentials_uses_random_seed() -> None:
    """Two calls with the same inputs must produce different ciphertexts —
    OAEP randomization is what gives it CCA security."""
    a = encrypt_credentials("a@b.com", "pw")
    b = encrypt_credentials("a@b.com", "pw")
    assert a != b


# ─── Response parser ─────────────────────────────────────────────────────


def test_parse_keyvalue_handles_blank_lines_and_whitespace() -> None:
    body = "  Token =  aas_et/abc \nExpiry=1700000000\n\nIgnored\n"
    parsed = _parse_keyvalue_response(body)
    assert parsed["Token"] == "aas_et/abc"
    assert parsed["Expiry"] == "1700000000"


# ─── mint_aas_token (mocked HTTP) ────────────────────────────────────────


def _mock_transport(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_mint_aas_token_returns_token_on_success() -> None:
    """Happy path: /auth returns Token=… → mint_aas_token returns the value."""

    def handler(request: httpx.Request) -> httpx.Response:
        # The encrypted credential should ride in the form body.
        assert b"EncryptedPasswd=" in request.content
        assert b"service=ac2dm" in request.content
        return httpx.Response(200, text="Token=aas_et/synthetic\nExpiry=0\n")

    with _mock_transport(handler) as client:
        token = mint_aas_token("user@example.com", "pw", http_client=client)
    assert token == "aas_et/synthetic"


def test_mint_aas_token_raises_on_bad_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, text="Error=BadAuthentication\n")

    with _mock_transport(handler) as client, pytest.raises(GoogleAuthError, match="BadAuthentication"):
        mint_aas_token("user@example.com", "wrong", http_client=client)


def test_mint_aas_token_surfaces_captcha_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, text="Error=CaptchaRequired\n")

    with _mock_transport(handler) as client, pytest.raises(GoogleAuthError, match="CaptchaRequired"):
        mint_aas_token("user@example.com", "pw", http_client=client)


def test_mint_aas_token_raises_on_non_200_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(500, text="server error")

    with _mock_transport(handler) as client, pytest.raises(GoogleAuthError, match="HTTP 500"):
        mint_aas_token("user@example.com", "pw", http_client=client)
