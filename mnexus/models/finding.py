"""Finding — the thing your client actually pays you to produce.

Every finding carries a `remediation`. For CRITICAL and HIGH severities this is
enforced at construction time — shipping a finding without guidance is exactly
the kind of noise that gave the industry a bad name.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Severity(str, Enum):
    """Severity levels. Ranked loud to quiet."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(str, Enum):
    """High-level bucket a finding belongs to. Used for report grouping + UI filters."""

    CRYPTO = "weak-cryptography"
    STORAGE = "insecure-data-storage"
    NETWORK = "network-security"
    AUTH = "authentication"
    CODE = "code-quality"
    NATIVE = "native-code"
    OBFUSCATION = "anti-tampering"
    PRIVACY = "privacy"
    IPC = "inter-process-communication"
    WEBVIEW = "webview"


class Finding(BaseModel):
    """A single security finding.

    Built by an engine, optionally confirmed by dynamic analysis, and ultimately
    rendered in the UI + report. Carries its own remediation because "fix it"
    is not actionable and nobody should have to write the mitigation twice.
    """

    id: str = Field(default_factory=lambda: f"FND-{uuid4().hex[:8].upper()}")
    title: str
    description: str
    severity: Severity
    category: FindingCategory
    source_engine: str = Field(description="Which engine detected this. e.g. 'jadx', 'mobsf', 'ghidra'.")
    evidence: str = Field(description="Code snippet, log line, disassembly — something you can paste into a report.")

    location: str | None = Field(default=None, description="File path, optionally with `:line`.")
    cwe_id: str | None = Field(default=None, description="CWE reference. e.g. 'CWE-798'.")
    owasp_mobile: str | None = Field(default=None, description="OWASP Mobile Top 10 mapping. e.g. 'M10'.")
    masvs: str | None = Field(default=None, description="OWASP MASVS control. e.g. 'MSTG-CRYPTO-1'.")

    suggested_hook: str | None = Field(default=None, description="Auto-generated Frida script for dynamic validation.")
    remediation: str | None = Field(
        default=None,
        description=(
            "Concrete, code-level remediation steps. Before/after snippets, config changes, "
            "library substitutions. No vague advice. Required for CRITICAL/HIGH severities."
        ),
    )

    platform_hint: str = Field(
        default="both",
        description="Which platform this finding applies to: 'android' | 'ios' | 'both'. Drives MASTG link routing + recipe filtering.",
    )

    confirmed: bool = Field(default=False, description="True once a dynamic run reproduced the issue.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("title", "description", "evidence")
    @classmethod
    def _no_empty_strings(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("finding fields must not be empty; silence is not a finding")
        return v

    @model_validator(mode="after")
    def _mitigation_required_for_blockers(self) -> Finding:
        """CRITICAL and HIGH findings must ship with remediation. No exceptions."""
        if self.severity in (Severity.CRITICAL, Severity.HIGH) and not (self.remediation and self.remediation.strip()):
            raise ValueError(
                f"severity={self.severity.value} findings require a `remediation` — "
                "this is the whole point of the platform. "
                "If the fix is upstream, say so: 'Vendor issue in SDK X — ticket #####'."
            )
        return self

    @property
    def severity_weight(self) -> float:
        """Risk weight used by the scoring engine. Cranked on purpose for CRITs."""
        return {
            Severity.CRITICAL: 10.0,
            Severity.HIGH: 7.5,
            Severity.MEDIUM: 4.0,
            Severity.LOW: 1.5,
            Severity.INFO: 0.0,
        }[self.severity]
