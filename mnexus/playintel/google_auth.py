"""Email + password → AAS master token, in pure Python.

Replaces the apkeep / gpapi-python dependency for users who don't yet
have an AAS token. The flow:

1. Encrypt ``"<email>\\0<password>"`` with Google's hardcoded
   GMS public key using RSA-OAEP-SHA1 and prepend a 5-byte tag
   (``0x00`` + first 4 bytes of ``sha1(pubkey_bytes)``); base64-url the
   whole thing.
2. POST to ``https://android.clients.google.com/auth`` with
   ``service=ac2dm`` (the AAS scope). The text response carries
   ``Token=aas_et/...`` — that's the long-lived master token.
3. Cache it in :class:`PlayCredentials` for subsequent /auth calls.

The hardcoded ``GOOGLE_GMS_PUBKEY`` is the well-known value used by
every Android device (and every third-party Play client). The
RSA-OAEP-SHA1 + MGF1-SHA1 pair is standard PKCS#1 v2.2 — implemented
here on top of stdlib ``hashlib`` and Python's built-in ``pow``
modular-exponentiation, so we add zero new dependencies.

This is the single piece of crypto in the playintel stack. Reviewers
should verify against RFC 8017 §7.1 (RSAES-OAEP-Encrypt) and Appendix B
(MGF1).
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

import httpx

# ─── Google GMS RSA public key ────────────────────────────────────────────
# Standard, public-by-design constant. Anyone running an Android Play
# client uses this exact key. Format: 4 bytes BE = len(N), N (1024-bit
# modulus, 128 bytes), 4 bytes BE = len(E), E (typically 3 bytes for
# 0x010001).
GOOGLE_GMS_PUBKEY_B64 = (
    "AAAAgMom/1a/v0lblO2Ubrt60J2gcuXSljGFQXgcyZWveWLEwo6prwgi3iJIZdod"
    "yhKZQrNWp5nKJ3srRXcUW+F1BD3baEVGcmEgqaLZUNBjm057pKRI16kB0YppeGx5"
    "qIQ5QjKzsR8ETQbKLNWgRY0QRNVz34kMJR3P/LgHax/6rmf5AAAAAwEAAQ=="
)

_PLAY_AUTH_URL = "https://android.clients.google.com/auth"
_AAS_SERVICE = "ac2dm"  # the scope that mints AAS master tokens
_HASH_LEN_SHA1 = 20  # bytes


# ─── Google public-key parsing ────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class _RSAPubKey:
    n: int
    e: int
    raw: bytes
    """Raw bytes of the encoded key — needed for the sha1 prefix tag."""

    @property
    def key_size_bytes(self) -> int:
        return (self.n.bit_length() + 7) // 8


def _parse_gms_pubkey(b64: str = GOOGLE_GMS_PUBKEY_B64) -> _RSAPubKey:
    raw = base64.b64decode(b64)
    if len(raw) < 8:
        raise ValueError("GMS pubkey blob is too short")
    n_len = int.from_bytes(raw[0:4], "big")
    if 4 + n_len + 4 > len(raw):
        raise ValueError("GMS pubkey: declared modulus length exceeds blob")
    n = int.from_bytes(raw[4 : 4 + n_len], "big")
    e_len_off = 4 + n_len
    e_len = int.from_bytes(raw[e_len_off : e_len_off + 4], "big")
    e_off = e_len_off + 4
    if e_off + e_len > len(raw):
        raise ValueError("GMS pubkey: declared exponent length exceeds blob")
    e = int.from_bytes(raw[e_off : e_off + e_len], "big")
    return _RSAPubKey(n=n, e=e, raw=raw)


# ─── PKCS#1 v2.2 OAEP-SHA1 encryption ─────────────────────────────────────


def _sha1(data: bytes) -> bytes:
    return hashlib.sha1(data, usedforsecurity=False).digest()


def _mgf1_sha1(seed: bytes, mask_len: int) -> bytes:
    """RFC 8017 §B.2.1 MGF1 with SHA-1 as the hash."""
    if mask_len < 0:
        raise ValueError("mask_len must be non-negative")
    out = bytearray()
    counter = 0
    while len(out) < mask_len:
        out.extend(_sha1(seed + counter.to_bytes(4, "big")))
        counter += 1
    return bytes(out[:mask_len])


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _oaep_encode(
    message: bytes,
    k: int,
    *,
    seed_override: bytes | None = None,
) -> bytes:
    """RFC 8017 §7.1.1 EME-OAEP encoding with empty label and SHA-1.

    ``k`` is the RSA modulus length in bytes; output is ``k`` bytes.
    ``seed_override`` is exposed only so deterministic tests can pin
    the random seed; production callers must leave it ``None`` so
    ``os.urandom`` provides a fresh seed.
    """
    if len(message) > k - 2 * _HASH_LEN_SHA1 - 2:
        raise ValueError("message too long for OAEP envelope")
    l_hash = _sha1(b"")  # empty label
    ps_len = k - len(message) - 2 * _HASH_LEN_SHA1 - 2
    db = l_hash + (b"\x00" * ps_len) + b"\x01" + message
    seed = seed_override if seed_override is not None else os.urandom(_HASH_LEN_SHA1)
    if len(seed) != _HASH_LEN_SHA1:
        raise ValueError(f"seed must be {_HASH_LEN_SHA1} bytes")
    db_mask = _mgf1_sha1(seed, k - _HASH_LEN_SHA1 - 1)
    masked_db = _xor_bytes(db, db_mask)
    seed_mask = _mgf1_sha1(masked_db, _HASH_LEN_SHA1)
    masked_seed = _xor_bytes(seed, seed_mask)
    return b"\x00" + masked_seed + masked_db


def _rsa_encrypt(pubkey: _RSAPubKey, message: bytes) -> bytes:
    """OS2IP → modular exponentiation → I2OSP, all on built-in big ints."""
    em = _oaep_encode(message, pubkey.key_size_bytes)
    m = int.from_bytes(em, "big")
    c = pow(m, pubkey.e, pubkey.n)
    return c.to_bytes(pubkey.key_size_bytes, "big")


# ─── Public API ───────────────────────────────────────────────────────────


def encrypt_credentials(email: str, password: str, *, pubkey: _RSAPubKey | None = None) -> str:
    """Build the ``EncryptedPasswd=`` parameter for ``POST /auth``.

    The format is well-documented across third-party Play clients::

        base64url(0x00 || sha1(pubkey_bytes)[:4] || RSA-OAEP-SHA1(email\\0password))

    Returns the URL-safe base64 string ready to drop into the form
    body.
    """
    pk = pubkey or _parse_gms_pubkey()
    plaintext = email.encode("utf-8") + b"\x00" + password.encode("utf-8")
    ciphertext = _rsa_encrypt(pk, plaintext)
    key_hash = _sha1(pk.raw)
    blob = bytes([0x00]) + key_hash[:4] + ciphertext
    return base64.urlsafe_b64encode(blob).decode("ascii")


def mint_aas_token(
    email: str,
    password: str,
    *,
    http_client: httpx.Client | None = None,
    timeout_s: float = 30.0,
) -> str:
    """Exchange an email + password for an AAS master token.

    The token returned here is the long-lived ``aas_et/...`` string
    that goes in ``apkeep.ini`` / ``playintel.ini`` and never has to
    be regenerated unless the user changes their Google password.

    Raises :class:`GoogleAuthError` for any failure mode mappable to
    Google's response (bad password, captcha required, account locked,
    etc.).
    """
    encrypted = encrypt_credentials(email, password)
    params = {
        "Email": email,
        "EncryptedPasswd": encrypted,
        "add_account": "1",
        "service": _AAS_SERVICE,
        "source": "android",
        "device_country": "us",
        "lang": "en",
        "sdk_version": "17",
        "has_permission": "1",
        "accountType": "HOSTED_OR_GOOGLE",
        "google_play_services_version": "203615037",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": (
            "GoogleAuth/1.4 (Pixel 7a TQ2A.230505.002); gzip"
        ),
    }

    own_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout_s, follow_redirects=False)
    try:
        resp = client.post(_PLAY_AUTH_URL, data=params, headers=headers)
    finally:
        if own_client:
            client.close()

    if resp.status_code != 200:
        raise GoogleAuthError(
            f"/auth returned HTTP {resp.status_code}. "
            f"Body: {resp.text[:300]}"
        )

    fields = _parse_keyvalue_response(resp.text)
    token = fields.get("Token", "")
    if not token:
        # Common failure modes: BadAuthentication (wrong password),
        # NeedsBrowser (captcha), NotVerified (2FA), CaptchaRequired.
        err = fields.get("Error", "")
        if err == "BadAuthentication":
            raise GoogleAuthError(
                "BadAuthentication — Google rejected the password. "
                "Note: app passwords (https://myaccount.google.com/apppasswords) "
                "may be required if 2FA is enabled."
            )
        if err in ("NeedsBrowser", "CaptchaRequired"):
            raise GoogleAuthError(
                f"{err} — Google requires browser-based verification "
                "(visit https://accounts.google.com/DisplayUnlockCaptcha first, "
                "or use an app password)."
            )
        raise GoogleAuthError(
            f"/auth response did not include Token=. "
            f"Error={err or '<missing>'}. Raw: {resp.text[:300]}"
        )
    return token


# ─── Helpers ──────────────────────────────────────────────────────────────


def _parse_keyvalue_response(body: str) -> dict[str, str]:
    """Parse the line-oriented ``key=value`` text Google returns."""
    out: dict[str, str] = {}
    for line in body.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


class GoogleAuthError(RuntimeError):
    """Raised when /auth refuses to mint an AAS token. Carries the
    Google-side reason verbatim where available."""


__all__ = [
    "GOOGLE_GMS_PUBKEY_B64",
    "GoogleAuthError",
    "encrypt_credentials",
    "mint_aas_token",
]
