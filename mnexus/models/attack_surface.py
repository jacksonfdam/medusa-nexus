"""Attack surface — everything the app exposes to the hostile universe.

Built by the intelligence layer from what the static engines report. Dynamic
analysis later enriches it with confirmation or contradiction.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mnexus.models.finding import Finding


class ExportedComponent(BaseModel):
    """Manifest-declared exported activity/service/receiver/provider."""

    name: str
    component_type: str  # "activity" | "service" | "receiver" | "provider"
    permission: str | None = None
    intent_filters: list[dict[str, list[str]]] = Field(default_factory=list)
    unprotected: bool = False  # no permission + exported = trouble


class NativeLibrary(BaseModel):
    """A `.so` shipped in the APK. Ghidra will dig through it."""

    path: str
    arch: str  # armeabi-v7a | arm64-v8a | x86 | x86_64
    size_bytes: int
    jni_functions: list[str] = Field(default_factory=list)
    crypto_primitives_detected: list[str] = Field(default_factory=list)


class CryptoOperation(BaseModel):
    """A single cryptographic usage spotted by static analysis."""

    location: str
    algorithm: str  # e.g. "AES/CBC/PKCS5Padding"
    key_source: str  # "hardcoded" | "keystore" | "derived" | "external" | "unknown"
    iv_source: str | None = None  # "static" | "random" | "derived" | None


class AttackSurface(BaseModel):
    """Aggregated map of what's exposed.

    Built once per ingest, mutated by the correlator. The UI renders it as the
    graph + the Overview risk mini. Treat it as the single source of truth for
    "what could go wrong, and where".
    """

    exported_components: list[ExportedComponent] = Field(default_factory=list)
    deeplinks: list[str] = Field(default_factory=list)
    native_libraries: list[NativeLibrary] = Field(default_factory=list)
    api_endpoints: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    sdk_fingerprint: dict[str, str] = Field(default_factory=dict)  # sdk_name → version
    crypto_operations: list[CryptoOperation] = Field(default_factory=list)

    ssl_pinning_detected: bool = False
    ssl_pinning_library: str | None = None  # "okhttp" | "trustmanager" | "custom" | None
    root_detection_detected: bool = False
    root_detection_library: str | None = None  # "rootbeer" | "safetynet" | "custom" | None
    emulator_detection_detected: bool = False

    findings: list[Finding] = Field(default_factory=list)

    def findings_by_severity(self) -> dict[str, int]:
        """Counts keyed by severity value — for the Overview severity bars."""
        from collections import Counter

        return dict(Counter(f.severity.value for f in self.findings))

    def risk_score(self) -> float:
        """0–100 weighted score. The number on the big gauge.

        Returns 0.0 when there are no findings (clean slate, not broken meter).
        """
        if not self.findings:
            return 0.0
        max_weight_per_finding = 10.0  # Severity.CRITICAL.weight
        total = sum(f.severity_weight for f in self.findings)
        score = (total / (len(self.findings) * max_weight_per_finding)) * 100.0
        return round(score, 1)
