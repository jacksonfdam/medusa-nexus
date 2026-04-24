"""Burp engine — proxy everything, trust nothing.

Talks to Burp Suite Professional over its REST API. Auto-configures device
proxy via ADB, pushes the CA cert, streams traffic history back to the UI.
"""

from __future__ import annotations

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.finding import Finding


class BurpEngine(BaseEngine):
    @property
    def name(self) -> str:
        return "burp"

    @property
    def capabilities(self) -> list[str]:
        return ["proxy", "intercept", "scan", "traffic_history"]

    async def health_check(self) -> EngineStatus:  # pragma: no cover - stub
        return EngineStatus(
            name=self.name,
            installed=False,
            version=None,
            path=self.config.burp_url,
            message="stub — wire to Burp REST once a real token lands",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:  # pragma: no cover - stub
        _ = context
        return []
