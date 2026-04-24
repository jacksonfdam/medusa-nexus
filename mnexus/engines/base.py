"""BaseEngine — the contract every head of the hydra agrees to.

If you can't expose `health_check` + `execute` → `List[Finding]`, you don't get
a seat at the table. Heretical, yes. Effective, also yes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mnexus.config import NexusConfig
from mnexus.models.finding import Finding


@dataclass(slots=True)
class EngineStatus:
    """What `mnexus doctor` prints about one engine."""

    name: str
    installed: bool
    version: str | None
    path: str | None
    message: str  # acid one-liner on the current state, for the UI


@dataclass(slots=True)
class AnalysisContext:
    """Bag of inputs engines receive at `execute` time.

    Kept deliberately loose — engines pluck the fields they care about.
    If an engine needs more, add it here; don't invent side channels.
    """

    apk_path: Path
    workspace: Path
    package_name: str | None = None
    extras: dict[str, Any] | None = None


class BaseEngine(ABC):
    """Abstract engine. Subclass, don't subvert."""

    # ─── metadata ───

    @property
    @abstractmethod
    def name(self) -> str:
        """Short lowercase name. Used in CLI, logs, report attribution."""

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """Tags like 'decompile', 'hook', 'intercept'. Drives the pipeline router."""

    # ─── lifecycle ───

    def __init__(self, config: NexusConfig) -> None:
        self.config = config

    @abstractmethod
    async def health_check(self) -> EngineStatus:
        """Is the underlying tool installed, reachable, and not lying about its version?"""

    @abstractmethod
    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Run the analysis. Return findings. Raise on catastrophic failures only."""

    # ─── helpers ───

    def to_findings(self, raw_output: dict[str, Any]) -> list[Finding]:  # pragma: no cover - stub
        """Normalize tool-specific JSON into `Finding` objects.

        Default: overridden by each engine. The base impl is here so linters
        stop complaining about abstractness; call super at your own amusement.
        """
        _ = raw_output
        return []
