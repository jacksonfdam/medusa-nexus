"""PlayAccount — one stored Google Play identity.

Multiple accounts can be stored at once (e.g. ``research-1``,
``qa-pixel7a``, ``offshore``); ``is_default`` marks the one the
``play-scan`` command targets when no name is given. A single ``name``
is unique per store and is the only handle the CLI / API exposes —
``email`` and especially ``aas_token`` never get echoed back outside
the ``show`` path.

The model is deliberately a Pydantic ``BaseModel`` for parity with the
rest of the project and to get free JSON serialization (used by both
the SQLite storage layer and the FastAPI surface). The ``redact()``
helper strips secrets so the listing endpoint can't accidentally leak
a token through a misuse.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PlayAccount(BaseModel):
    """One stored Play identity. Created/managed by `mnexus play-account`."""

    name: str = Field(description="Short human handle. Unique. Used as the CLI/API key.")
    email: str = Field(description="Gmail address tied to this Play identity.")
    aas_token: str = Field(description="Long-lived AAS master token (sensitive).")
    gsfid: str = Field(default="", description="Google Services Framework ID; minted by /checkin.")
    locale: str = Field(default="en-US")
    notes: str = Field(default="", description="Free-form note: 'qa rig', 'research-2026-q2', …")
    is_default: bool = Field(default=False, description="True for the account play-scan uses by default.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("name")
    @classmethod
    def _name_is_simple(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name must not be empty")
        # Keep names URL- and shell-safe so they can flow through the
        # API path and CLI args without escaping.
        if not all(ch.isalnum() or ch in "-_" for ch in v):
            raise ValueError("name must be alphanumeric / '-' / '_' only")
        if len(v) > 64:
            raise ValueError("name must be <= 64 characters")
        return v

    @field_validator("email")
    @classmethod
    def _email_present(cls, v: str) -> str:
        v = (v or "").strip()
        if "@" not in v:
            raise ValueError("email must look like an address")
        return v

    @field_validator("aas_token")
    @classmethod
    def _aas_token_non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("aas_token must not be empty")
        return v

    def redact(self) -> dict[str, Any]:
        """Public-safe view of the account. Strips the AAS token entirely
        and shows only the local-part of the email so the listing UI
        can render it without leaking enough to authenticate."""
        local, _, _domain = self.email.partition("@")
        return {
            "name": self.name,
            "email_local": local,
            "email_domain": _domain,
            "gsfid_present": bool(self.gsfid),
            "locale": self.locale,
            "notes": self.notes,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
