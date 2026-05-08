"""PlayScanRecord — a persisted history entry for one PlayIntel run.

Every successful ``/v1/playintel/scan`` (and the ``-upload`` variant)
saves one of these so the analyst can:

* See what was scanned, when, and against which Play account
* Re-open old scans without re-running them
* Diff results across versions ("did this credential land in 3.44 or
  was it already in 3.43?")
* Generate per-app reports across the full history

The full JSON response from the engine lives in ``payload``; the
denormalised counts on the side make the listing endpoint cheap (no
JSON parse per row).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class PlayScanRecord(BaseModel):
    """One row of scan history."""

    id: str = Field(default_factory=lambda: f"PSC-{uuid4().hex[:10].upper()}")
    package: str = Field(description="Android package id at the time of the scan.")
    version_name: str = Field(default="", description="versionName from the manifest, when available.")
    version_code: int = Field(default=0, description="versionCode from the manifest, when available.")
    source: str = Field(description="One of: play | local | upload.")
    source_label: str = Field(description="Human-readable source detail: 'play:research-1', 'upload:McD_3.44.apk', …")
    apk_sha256: str = Field(default="", description="sha256 of the APK bytes when the source was a local file.")
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Denormalised counts so the listing endpoint can rank/filter
    # without re-parsing payload JSON for every row.
    firebase_project_count: int = 0
    confirmed_secrets_count: int = 0
    suspected_secrets_count: int = 0
    vulnerability_count: int = 0
    findings_count: int = 0
    saved_files_count: int = 0

    payload: dict[str, Any] = Field(default_factory=dict, description="Full /scan JSON response.")

    def summary(self) -> dict[str, Any]:
        """Listing-friendly view — payload stripped, dates ISO-formatted."""
        return {
            "id": self.id,
            "package": self.package,
            "version_name": self.version_name,
            "version_code": self.version_code,
            "source": self.source,
            "source_label": self.source_label,
            "apk_sha256": self.apk_sha256,
            "scanned_at": self.scanned_at.isoformat(),
            "firebase_project_count": self.firebase_project_count,
            "confirmed_secrets_count": self.confirmed_secrets_count,
            "suspected_secrets_count": self.suspected_secrets_count,
            "vulnerability_count": self.vulnerability_count,
            "findings_count": self.findings_count,
            "saved_files_count": self.saved_files_count,
        }
