"""Cross-engine correlator.

Example correlations we want to emit eventually:

1. JADX finds `SecretKeySpec` with hardcoded key
   + Ghidra finds the same bytes in `.rodata` of a `.so`
   = CONFIRMED: key is truly hardcoded, not runtime-derived.

2. MobSF flags an exported Activity
   + JADX shows it handles deep links with user input
   + no input validation observed
   = ESCALATED: deep link injection → potential account takeover.

3. Static: SSL pinning detected (OkHttp CertificatePinner)
   + Dynamic: Frida bypass succeeds
   = CONFIRMED: bypassable, interception viable.

The shipped skeleton covers the data model; the detection rules are stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass

from mnexus.models.finding import Finding, Severity


@dataclass(slots=True)
class CorrelatedFinding:
    """A chain of related findings. Higher confidence than any one in isolation."""

    findings: list[Finding]
    confidence: float  # 0.0–1.0
    attack_narrative: str  # human-readable chain description
    combined_severity: Severity


class FindingCorrelator:
    """Rule-based correlator. Open to new rules, closed to magic."""

    def correlate(self, all_findings: list[Finding]) -> list[CorrelatedFinding]:
        """Group related findings + promote severity where signals stack."""
        chains: list[CorrelatedFinding] = []

        # Stub rules — expand in iteration 2.
        by_location = self._group_by_location(all_findings)
        for loc, group in by_location.items():
            if len(group) > 1:
                chains.append(
                    CorrelatedFinding(
                        findings=group,
                        confidence=min(1.0, 0.5 + 0.1 * len(group)),
                        attack_narrative=f"{len(group)} findings share location {loc} — likely same root cause",
                        combined_severity=max((f.severity for f in group), key=lambda s: list(Severity).index(s)),
                    )
                )
        return chains

    def _group_by_location(self, findings: list[Finding]) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in findings:
            if f.location:
                out.setdefault(f.location, []).append(f)
        return out
