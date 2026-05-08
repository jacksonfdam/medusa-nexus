"""Secret detector — regex + entropy + AKIA pair correlation.

Two tiers of patterns:

* :data:`SECRET_PATTERNS` — *confirmed*: vendor-specific shapes that almost
  never occur outside their issuer (OpenAI, Anthropic, Stripe, GitHub,
  AWS access-key IDs, FCM legacy server keys, PEM private keys, …). A
  hit is reported with confidence.
* :data:`SUSPECTED_SECRET_PATTERNS` — *suspected*: generic shapes
  (``api_key="…"``, JWT) that have a high false-positive rate. Only
  reported when (a) no confirmed match was found in the same value, and
  (b) Shannon entropy is above ``MIN_SECRET_ENTROPY``. The two filters
  together cut placeholder strings, repeated-char fillers, and
  documentation examples.

The AWS path is special: an access-key ID (``AKIA…``) on its own is
useless without the matching secret. :func:`find_aws_key_pairs`
correlates the two within a 1024-byte window and applies extra entropy /
hex-only filters to drop SHA-1 hashes that happen to look like AWS
secrets.

Some Google-API-Client SDK versions ship hardcoded *test* private keys
inside DEX string pools. They're identical across every app that uses
that SDK and are not real credentials. :func:`is_known_sdk_test_key`
recognizes them so we don't burn a CRITICAL finding on shared library
boilerplate.
"""

from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass

# Thresholds. ``MIN_SECRET_ENTROPY`` filters placeholder strings; the
# higher AWS-specific threshold reflects that AWS secret-access keys are
# 40 base64 chars and real ones land near max entropy.
MIN_SECRET_ENTROPY = 3.0
AWS_SECRET_ENTROPY = 4.25


def shannon_entropy(s: str) -> float:
    """Shannon entropy in bits/char of an arbitrary string.

    Returns 0 for the empty string. Anything below ~3.0 is dominated by
    repeated chars (placeholders, version strings, hex constants made of
    only [0-9a-f]).
    """
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    length = float(len(s))
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


# ─── Pattern catalog ───────────────────────────────────────────────────────
# Keep these in alphabetical-ish order by issuer for review-friendliness.
# When adding a new pattern, prefer the most specific prefix the issuer
# defines — generic patterns belong in SUSPECTED_SECRET_PATTERNS.

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "OpenAI API Key": re.compile(r"sk-(?:proj-|svcacct-)?[a-zA-Z0-9_-]+T3BlbkFJ[a-zA-Z0-9_-]+"),
    "Anthropic API Key": re.compile(r"sk-ant-[a-zA-Z0-9_-]{75,}"),
    "Groq API Key": re.compile(r"gsk_[a-zA-Z0-9]{48,}"),
    "xAI (Grok) API Key": re.compile(r"xai-[a-zA-Z0-9]{48,}"),
    "Cerebras API Key": re.compile(r"csk-[a-zA-Z0-9]{40,}"),
    "Openrouter API Key": re.compile(r"sk-or-v1-[a-zA-Z0-9]{64}"),
    "Replicate API Token": re.compile(r"r8_[a-zA-Z0-9]{40}"),
    "Hugging Face API Token": re.compile(r"hf_[a-zA-Z0-9]{35}"),
    "Fireworks AI Key": re.compile(r"fw_[a-zA-Z0-9]{40,}"),
    "Vercel Token": re.compile(r"vercel_[a-zA-Z0-9_]{24,}"),
    "Supabase Key": re.compile(r"sbp_[a-f0-9]{40}"),
    "DigitalOcean PAT": re.compile(r"dop_v1_[a-f0-9]{64}"),
    "Databricks Token": re.compile(r"dapi[a-f0-9]{32}"),
    "AWS Secret Access Key": re.compile(
        r"""(?ix)aws_secret_access_key["':\s=]+["']?[A-Za-z0-9/+=]{40}["']?"""
    ),
    "OneSignal API Key": re.compile(r"os_v2_(?:app|api)_[a-z0-9]{90,}"),
    "Slack Token": re.compile(r"xox[pboa]-\d{12}-\d{12}-\d{12}-[a-z0-9]{32}"),
    "GitHub Token": re.compile(r"gh[pous]_[0-9a-zA-Z]{36}"),
    "GitLab Token": re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    "SendGrid API Key": re.compile(r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}"),
    "Twilio API Key SID": re.compile(r"(?i)twilio[^a-zA-Z0-9]{0,20}SK[0-9a-fA-F]{32}"),
    "Stripe API Key": re.compile(r"sk_live_[0-9a-zA-Z]{24}"),
    # PEM private keys — DOTALL so we can span newlines inside a single value.
    "Private Key": re.compile(
        r"-----BEGIN ((?:EC|PGP|DSA|RSA|OPENSSH) )?PRIVATE KEY( BLOCK)?-----"
        r"\s*.+?\s*"
        r"-----END ((?:EC|PGP|DSA|RSA|OPENSSH) )?PRIVATE KEY( BLOCK)?-----",
        re.DOTALL,
    ),
    "FCM Server Key": re.compile(r"AAAA[A-Za-z0-9_-]{7}:[A-Za-z0-9_-]{140}"),
}


SUSPECTED_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "Branch.io Key": re.compile(r"key_(?:live|test)_[a-zA-Z0-9]{32}"),
    "Generic API Key": re.compile(
        r"""(?i)api[_-]?key["':\s=]+["']?([a-zA-Z0-9_-]{20,64})["']?"""
    ),
    "Generic Secret": re.compile(
        r"""(?i)secret["':\s=]+["']?([a-zA-Z0-9_-]{20,64})["']?"""
    ),
    "JWT Token": re.compile(r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+"),
}


# AWS access-key ID + secret correlation. The key ID prefix is one of the
# documented AWS prefixes (AKIA = long-term, ASIA = STS session, ABIA =
# bedrock, ACCA = console). The "secret" pattern is intentionally loose
# — 40 base64 chars not glued to other base64 — and is filtered later by
# entropy + hex-only checks.
_AWS_KEY_RE = re.compile(r"\b((?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16})\b")
_AWS_SECRET_RE = re.compile(r"(?:[^A-Za-z0-9+/]|\A)([A-Za-z0-9+/]{40})(?:[^A-Za-z0-9+/]|\Z)")
_AWS_FALSE_POS_HEX = re.compile(r"^[a-f0-9]{40}$")


@dataclass(slots=True)
class SecretMatch:
    """A single secret hit with all the context a finding needs."""

    type: str
    """Human-readable label, e.g. ``"OpenAI API Key"`` or ``"AWS Key Pair"``."""

    value: str
    """The matched secret. For AWS pairs, ``key_id:secret``."""

    location: str
    """Where the hit came from — file path, optionally with a resource key."""

    suspected: bool = False
    """``True`` if it came from :data:`SUSPECTED_SECRET_PATTERNS`."""


# ─── Public matching API ───────────────────────────────────────────────────


def match_secrets(value: str, location: str) -> list[SecretMatch]:
    """Run all single-line patterns against ``value``.

    Confirmed patterns are reported unconditionally. Suspected patterns
    only fire if (a) no confirmed pattern matched the same value, and
    (b) Shannon entropy is at least :data:`MIN_SECRET_ENTROPY`.

    AWS access-key IDs trigger :func:`find_aws_key_pairs` which looks
    for the matching secret in the same string.
    """
    matches: list[SecretMatch] = []
    confirmed = False

    for secret_type, pattern in SECRET_PATTERNS.items():
        for hit in pattern.findall(value):
            # ``re.findall`` returns the first group when the pattern has
            # capturing groups; for the Private Key pattern that's a
            # tuple. Normalize back to the full match by re-running.
            full_match = _full_match(pattern, value, hit)
            if not full_match:
                continue
            if secret_type == "Private Key" and is_known_sdk_test_key(full_match):
                continue
            matches.append(SecretMatch(type=secret_type, value=full_match, location=location))
            confirmed = True

    matches.extend(find_aws_key_pairs(value, location))

    if not confirmed and shannon_entropy(value) >= MIN_SECRET_ENTROPY:
        for secret_type, pattern in SUSPECTED_SECRET_PATTERNS.items():
            for hit in pattern.findall(value):
                full_match = _full_match(pattern, value, hit)
                if not full_match:
                    continue
                matches.append(
                    SecretMatch(
                        type=secret_type,
                        value=full_match,
                        location=location,
                        suspected=True,
                    )
                )

    return matches


def match_secrets_multiline(content: str, location: str) -> list[SecretMatch]:
    """Like :func:`match_secrets` but designed for multi-line content.

    The PEM private-key pattern, in particular, only fires reliably when
    the entire ``-----BEGIN…-----END-----`` block is present in one
    string. Use this for whole files; use :func:`match_secrets` for
    individual resource values.
    """
    return match_secrets(content, location)


def match_secrets_with_decode(value: str, location: str) -> list[SecretMatch]:
    """Run :func:`match_secrets` on ``value`` *and* on any base64-decoded
    substrings found within it.

    Some apps store secrets as a base64-encoded blob inside another
    config field. Decoding and re-scanning catches those without
    requiring a second pass elsewhere.
    """
    matches = match_secrets(value, location)
    for sub in _extract_base64_substrings(value, min_len=24):
        try:
            decoded = base64.b64decode(sub, validate=True)
        except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
            try:
                # Tolerate missing padding.
                decoded = base64.b64decode(sub + "===", validate=False)
            except Exception:  # noqa: BLE001
                continue
        if len(decoded) < 10 or not _is_printable_ascii(decoded):
            continue
        decoded_str = decoded.decode("ascii", errors="replace")
        matches.extend(match_secrets(decoded_str, location + " (b64-decoded)"))
    return matches


# ─── AWS access-key + secret correlation ──────────────────────────────────


def find_aws_key_pairs(content: str, location: str) -> list[SecretMatch]:
    """Search for ``AKIA…`` / ``ASIA…`` IDs and the matching 40-char secret.

    A hit is only reported when:

    * The ID's 16-char suffix has both letters and digits (filters
      AKIA-prefixed identifier strings used in tutorials).
    * The candidate secret is within 1024 bytes of the ID.
    * Entropy of the secret ≥ 4.25 (eliminates repeated chars).
    * Secret is not a 40-char hex string (eliminates SHA-1 hashes).
    * Secret doesn't itself look like another known token (no
      ``AKIA``/``sk-`` prefix).
    """
    matches: list[SecretMatch] = []
    key_iter = list(_AWS_KEY_RE.finditer(content))
    if not key_iter:
        return matches

    secrets_iter = list(_AWS_SECRET_RE.finditer(content))
    if not secrets_iter:
        return matches

    for key_match in key_iter:
        key_id = key_match.group(1)
        suffix = key_id[4:]
        has_digit = any(c.isdigit() for c in suffix)
        has_letter = any(c.isalpha() for c in suffix)
        if not (has_digit and has_letter):
            continue
        if shannon_entropy(suffix) < 3.5:
            continue

        for sec_match in secrets_iter:
            secret = sec_match.group(1)
            sec_start = sec_match.start(1)
            sec_end = sec_match.end(1)

            # Distance between the secret and the key ID, either direction.
            if sec_start >= key_match.end():
                dist = sec_start - key_match.end()
            else:
                dist = key_match.start() - sec_end
            if dist > 1024:
                continue

            if shannon_entropy(secret) < AWS_SECRET_ENTROPY:
                continue
            if _AWS_FALSE_POS_HEX.match(secret):
                continue
            if secret.startswith("AKIA") or secret.startswith("sk-"):
                continue

            matches.append(
                SecretMatch(
                    type="AWS Key Pair",
                    value=f"{key_id}:{secret}",
                    location=location,
                )
            )
            break  # one secret per key ID

    return matches


# ─── SDK test-key allow-list ──────────────────────────────────────────────


# google-api-client ships TestCertificates.java which embeds two PEM
# private keys for unit tests. They appear in DEX string pools across
# every app that uses the SDK; flagging them would generate noise on
# essentially every Android app. Match on the first 50ish bytes after
# the PEM header — that's enough to uniquely identify each test key.
_KNOWN_SDK_TEST_KEY_PREFIXES = (
    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDN",
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCzFVKJ",
)


def is_known_sdk_test_key(pem_block: str) -> bool:
    """Return ``True`` if ``pem_block`` is one of the well-known
    google-api-client test fixtures.
    """
    body = pem_block
    # Try several PEM-header terminators; APK string pools sometimes
    # represent newlines as escape sequences instead of real bytes.
    for marker in ("-----\n", "-----\\n"):
        idx = body.find(marker)
        if idx != -1:
            body = body[idx + len(marker) :]
            break
    else:
        idx = body.find("-----")
        if idx != -1:
            body = body[idx + 5 :].lstrip()
    return any(body.startswith(prefix) for prefix in _KNOWN_SDK_TEST_KEY_PREFIXES)


# ─── Internals ─────────────────────────────────────────────────────────────


_B64_CHARSET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
)


def _extract_base64_substrings(s: str, min_len: int) -> list[str]:
    """Find contiguous runs of base64 characters at least ``min_len`` long."""
    out: list[str] = []
    start = -1
    for i, ch in enumerate(s):
        if ch in _B64_CHARSET:
            if start == -1:
                start = i
        else:
            if start != -1 and i - start >= min_len:
                out.append(s[start:i])
            start = -1
    if start != -1 and len(s) - start >= min_len:
        out.append(s[start:])
    return out


def _is_printable_ascii(data: bytes) -> bool:
    """Heuristic: ≥85% of bytes are printable ASCII or whitespace."""
    if not data:
        return False
    printable = sum(1 for b in data if 32 <= b <= 126 or b in (9, 10, 13))
    return printable / len(data) > 0.85


def _full_match(pattern: re.Pattern[str], value: str, group_or_full: object) -> str:
    """Resolve ``re.findall`` results back to the full pattern match.

    ``re.findall`` returns groups when the pattern has capturing groups —
    that loses the leading prefix for some of our patterns (e.g. AWS
    Secret Access Key). Re-run the pattern with ``search`` over a
    bounded window to recover the full match.
    """
    # Fast path — no capture groups.
    if isinstance(group_or_full, str) and pattern.groups == 0:
        return group_or_full

    # The hit may have come from any position; do a search from the
    # start. Multiple hits are handled by the caller.
    m = pattern.search(value)
    if m:
        return m.group(0)
    return ""
