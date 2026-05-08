"""PlayAccount model + ArtifactStore CRUD tests.

These are pure unit tests — no FastAPI, no HTTP — exercising the
storage contract directly. The API-layer tests live in
``test_play_account_api.py``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mnexus.core.artifact_store import ArtifactStore
from mnexus.models.play_account import PlayAccount


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    s = ArtifactStore(tmp_path / "nexus.sqlite3")
    yield s
    s.close()


# ─── model validators ────────────────────────────────────────────────────


def test_name_validator_rejects_empty() -> None:
    with pytest.raises(ValueError, match="not be empty"):
        PlayAccount(name="", email="x@y.com", aas_token="aas_et/x")


def test_name_validator_rejects_special_characters() -> None:
    """Names ride through CLI args + URL paths; restrict to safe chars."""
    with pytest.raises(ValueError, match="alphanumeric"):
        PlayAccount(name="bad name!", email="x@y.com", aas_token="aas_et/x")


def test_name_validator_accepts_dashes_and_underscores() -> None:
    a = PlayAccount(name="research_1-qa", email="x@y.com", aas_token="aas_et/x")
    assert a.name == "research_1-qa"


def test_name_validator_caps_length() -> None:
    with pytest.raises(ValueError, match="64 characters"):
        PlayAccount(name="x" * 65, email="x@y.com", aas_token="aas_et/x")


def test_email_validator_requires_at_sign() -> None:
    with pytest.raises(ValueError, match="address"):
        PlayAccount(name="ok", email="not-an-email", aas_token="aas_et/x")


def test_aas_validator_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        PlayAccount(name="ok", email="x@y.com", aas_token="")


def test_redact_strips_token_and_splits_email() -> None:
    a = PlayAccount(name="acc", email="alice@example.com", aas_token="aas_et/SECRET")
    redacted = a.redact()
    # Token must NOT appear under any key.
    assert "aas_et/SECRET" not in str(redacted)
    assert redacted["email_local"] == "alice"
    assert redacted["email_domain"] == "example.com"
    assert redacted["gsfid_present"] is False


# ─── storage CRUD ────────────────────────────────────────────────────────


def test_save_and_get_round_trip(store: ArtifactStore) -> None:
    a = PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A")
    store.save_play_account(a)
    got = store.get_play_account("alpha")
    assert got is not None
    assert got.email == "a@b.com"
    assert got.aas_token == "aas_et/A"


def test_get_missing_returns_none(store: ArtifactStore) -> None:
    assert store.get_play_account("never-existed") is None


def test_save_is_idempotent_on_name(store: ArtifactStore) -> None:
    """Saving with an existing name updates instead of erroring out."""
    a1 = PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/v1")
    a2 = PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/v2", notes="rotated")
    store.save_play_account(a1)
    store.save_play_account(a2)
    got = store.get_play_account("alpha")
    assert got.aas_token == "aas_et/v2"
    assert got.notes == "rotated"


def test_save_default_demotes_other_defaults(store: ArtifactStore) -> None:
    """Promoting one account flips every other ``is_default`` to False."""
    store.save_play_account(PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A", is_default=True))
    store.save_play_account(PlayAccount(name="beta", email="b@b.com", aas_token="aas_et/B", is_default=True))
    assert store.get_play_account("alpha").is_default is False
    assert store.get_play_account("beta").is_default is True


def test_set_default_promotes_existing_account(store: ArtifactStore) -> None:
    store.save_play_account(PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A", is_default=True))
    store.save_play_account(PlayAccount(name="beta", email="b@b.com", aas_token="aas_et/B"))
    assert store.set_default_play_account("beta") is True
    assert store.get_default_play_account().name == "beta"
    assert store.get_play_account("alpha").is_default is False


def test_set_default_returns_false_for_missing(store: ArtifactStore) -> None:
    assert store.set_default_play_account("ghost") is False


def test_delete_removes_account(store: ArtifactStore) -> None:
    store.save_play_account(PlayAccount(name="x", email="x@y.com", aas_token="aas_et/x"))
    assert store.delete_play_account("x") is True
    assert store.get_play_account("x") is None


def test_delete_is_idempotent(store: ArtifactStore) -> None:
    """A second delete on the same name reports False, not an error."""
    store.save_play_account(PlayAccount(name="x", email="x@y.com", aas_token="aas_et/x"))
    assert store.delete_play_account("x") is True
    assert store.delete_play_account("x") is False


def test_list_orders_default_first_then_alpha(store: ArtifactStore) -> None:
    """The default account always sorts to the top; the rest are alpha."""
    store.save_play_account(PlayAccount(name="zeta", email="z@b.com", aas_token="aas_et/Z"))
    store.save_play_account(PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A"))
    store.save_play_account(PlayAccount(name="beta", email="b@b.com", aas_token="aas_et/B", is_default=True))
    names = [a.name for a in store.list_play_accounts()]
    assert names == ["beta", "alpha", "zeta"]


def test_get_default_returns_none_when_unset(store: ArtifactStore) -> None:
    assert store.get_default_play_account() is None
    store.save_play_account(PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A"))
    # Saving without is_default leaves no default set.
    assert store.get_default_play_account() is None


def test_partial_unique_index_enforces_one_default(tmp_path: Path) -> None:
    """If an attacker bypassed the application layer and tried to mark two
    rows as default directly via SQL, the index must reject the second."""
    s = ArtifactStore(tmp_path / "raw.sqlite3")
    s.save_play_account(PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A", is_default=True))
    # Bypassing the app helper to attempt a second is_default=1.
    with pytest.raises(sqlite3.IntegrityError):
        s._conn.execute(  # noqa: SLF001 — testing the DB-level invariant
            "INSERT INTO play_accounts(name, email, aas_token, gsfid, locale, notes, "
            "is_default, created_at, updated_at) "
            "VALUES (?, ?, ?, '', 'en-US', '', 1, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            ("beta", "b@b.com", "aas_et/B"),
        )
        s._conn.commit()  # noqa: SLF001
    s.close()


def test_update_runtime_state_persists_gsfid(store: ArtifactStore) -> None:
    """A freshly minted GSFID from /checkin should round-trip without a
    full save call (the runtime path uses this from inside PlayClient)."""
    store.save_play_account(PlayAccount(name="alpha", email="a@b.com", aas_token="aas_et/A"))
    store.update_play_account_runtime_state("alpha", gsfid="abcdef0123")
    assert store.get_play_account("alpha").gsfid == "abcdef0123"
