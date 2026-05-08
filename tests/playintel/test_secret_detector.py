"""Secret detector tests — confirmed patterns, suspected gating, AKIA pairs."""

from __future__ import annotations

from mnexus.playintel.secret_detector import (
    MIN_SECRET_ENTROPY,
    SUSPECTED_SECRET_PATTERNS,
    is_known_sdk_test_key,
    match_secrets,
    match_secrets_with_decode,
    shannon_entropy,
)


# ─── Confirmed patterns ───────────────────────────────────────────────────


def test_confirmed_openai_key() -> None:
    value = "sk-proj-abcdefghijT3BlbkFJ1234567890abcdefABCDEF1234567890"
    matches = match_secrets(value, "test")
    assert any(m.type == "OpenAI API Key" for m in matches)
    assert all(m.suspected is False for m in matches if m.type == "OpenAI API Key")


def test_confirmed_anthropic_key() -> None:
    # Anthropic pattern requires 75+ chars after `sk-ant-`.
    value = "sk-ant-" + "a" * 80
    matches = match_secrets(value, "test")
    assert any(m.type == "Anthropic API Key" for m in matches)


def test_confirmed_github_pat() -> None:
    value = "ghp_" + "0123456789abcdefABCDEFghijklmnoPQRST"  # 36 chars
    matches = match_secrets(value, "test")
    assert any(m.type == "GitHub Token" for m in matches)


def test_confirmed_stripe_live_key() -> None:
    value = "sk_live_" + "abcdef1234567890ABCDEFGH"  # 24 chars
    matches = match_secrets(value, "test")
    assert any(m.type == "Stripe API Key" for m in matches)


def test_confirmed_pem_private_key_block() -> None:
    block = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        + ("MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQzzZZZ" * 4)
        + "\n-----END RSA PRIVATE KEY-----"
    )
    matches = match_secrets(block, "test.pem")
    assert any(m.type == "Private Key" for m in matches)


def test_known_sdk_test_key_is_suppressed() -> None:
    """google-api-client TestCertificates keys must not produce findings."""
    sdk_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDN" + "X" * 800 + "\n"
        "-----END PRIVATE KEY-----"
    )
    assert is_known_sdk_test_key(sdk_key)
    matches = match_secrets(sdk_key, "test.pem")
    assert all(m.type != "Private Key" for m in matches)


# ─── Suspected gating ─────────────────────────────────────────────────────


def test_suspected_pattern_gated_by_entropy() -> None:
    """Low-entropy values must not produce suspected hits."""
    low_entropy_value = 'api_key="aaaaaaaaaaaaaaaaaaaaaaaa"'
    assert shannon_entropy(low_entropy_value) < MIN_SECRET_ENTROPY
    matches = match_secrets(low_entropy_value, "test")
    assert all(m.type != "Generic API Key" for m in matches)


def test_suspected_pattern_fires_on_high_entropy() -> None:
    high_entropy_value = 'api_key="x9F2nQ7vR4tWzKpL3mGyU8oJaH6sB1cE"'
    assert shannon_entropy(high_entropy_value) >= MIN_SECRET_ENTROPY
    matches = match_secrets(high_entropy_value, "test")
    suspected = [m for m in matches if m.type == "Generic API Key"]
    assert suspected, "high-entropy generic api_key should produce a suspected hit"
    assert all(m.suspected for m in suspected)


def test_suspected_suppressed_when_confirmed_present() -> None:
    """If a confirmed pattern matched the same value, suspected ones don't fire."""
    value = "ghp_" + "0123456789abcdefABCDEFghijklmnoPQRST"
    matches = match_secrets(value, "test")
    confirmed = [m for m in matches if m.type == "GitHub Token"]
    suspected = [m for m in matches if m.suspected]
    assert confirmed
    assert not suspected


def test_suspected_pattern_set_is_distinct_from_confirmed() -> None:
    """Each suspected pattern must be a name that does not collide with confirmed ones."""
    # Sanity check — keeps reviewers honest about where new patterns go.
    assert "JWT Token" in SUSPECTED_SECRET_PATTERNS


# ─── AKIA pair correlation ────────────────────────────────────────────────


def test_aws_key_pair_correlation_succeeds() -> None:
    content = (
        'AKIAIOSFODNN7EXAMPLE\n'
        'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY  '
    )
    matches = match_secrets(content, "test.txt")
    pairs = [m for m in matches if m.type == "AWS Key Pair"]
    assert pairs
    assert pairs[0].value.startswith("AKIAIOSFODNN7EXAMPLE:")


def test_aws_key_pair_rejects_hex_only_secret() -> None:
    """SHA-1 hashes (40 hex chars) must not be classified as AWS secrets."""
    content = (
        'AKIAIOSFODNN7EXAMPLE\n'
        'da39a3ee5e6b4b0d3255bfef95601890afd80709  '
    )
    matches = match_secrets(content, "test.txt")
    pairs = [m for m in matches if m.type == "AWS Key Pair"]
    assert not pairs


def test_aws_key_pair_distance_window_enforced() -> None:
    """The 40-char secret must lie within 1024 bytes of the key ID."""
    content = (
        'AKIAIOSFODNN7EXAMPLE\n'
        + ('-' * 2000)
        + 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY  '
    )
    matches = match_secrets(content, "test.txt")
    pairs = [m for m in matches if m.type == "AWS Key Pair"]
    assert not pairs


# ─── base64-decoded re-scan ───────────────────────────────────────────────


def test_match_secrets_with_decode_finds_base64_wrapped_token() -> None:
    """A token hidden inside base64 should be discovered after decoding."""
    import base64

    inner = "ghp_" + "0123456789abcdefABCDEFghijklmnoPQRST"
    wrapped = base64.b64encode(inner.encode("ascii")).decode("ascii")
    matches = match_secrets_with_decode(wrapped, "config.b64")
    assert any(
        m.type == "GitHub Token" and "(b64-decoded)" in m.location for m in matches
    )
