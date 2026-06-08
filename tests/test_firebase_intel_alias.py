"""FirebaseIntelEngine — canonical name with PlayIntelEngine as legacy alias.

The rename is cosmetic (the analyser code is identical) but the
contract needs pinning so nobody accidentally splits the two engines
into separate instances with different state.

Coverage:
  * Orchestrator registers ONE engine instance under both keys
  * doctor() dedupes — only one Firebase row in the output
  * FirebaseIntelEngine.capabilities lists 'firebase' first
  * PlayIntelEngine still importable for back-compat
  * pipeline_executor's ('playintel', 'scan') handler still resolves
"""

from __future__ import annotations

import asyncio

import pytest

from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus
from mnexus.engines import FirebaseIntelEngine, PlayIntelEngine


def test_firebase_and_playintel_keys_share_one_instance(tmp_path) -> None:
    cfg = NexusConfig(workspace=tmp_path / "workspace", db_path=tmp_path / "nexus.sqlite3")
    nexus = MedusaNexus(cfg)
    fb = nexus.engines["firebase"]
    legacy = nexus.engines["playintel"]
    # Same Python object — not two engines, just two keys pointing at one.
    assert fb is legacy
    assert isinstance(fb, FirebaseIntelEngine)


def test_doctor_dedupes_alias(tmp_path) -> None:
    cfg = NexusConfig(workspace=tmp_path / "workspace", db_path=tmp_path / "nexus.sqlite3")
    nexus = MedusaNexus(cfg)
    rows = asyncio.new_event_loop().run_until_complete(nexus.doctor())
    names = [r["name"] for r in rows]
    # 'playintel' appears exactly once even though engines dict has two keys.
    assert names.count("playintel") == 1


def test_firebase_capabilities_list_firebase_first() -> None:
    """Surface signal: FirebaseIntelEngine.capabilities[0] should
    advertise 'firebase' so /doctor's capability column reads sensibly."""
    cfg = NexusConfig()
    engine = FirebaseIntelEngine(cfg)
    caps = engine.capabilities
    assert caps[0] == "firebase"
    # Active probes get a top-level slot now that they're a real
    # capability rather than buried under 'firebase'.
    assert "active-probes" in caps


def test_playintel_class_still_importable_for_back_compat() -> None:
    """The class name shipped in v0; downstream tooling may import
    `from mnexus.engines import PlayIntelEngine`. Keep that working."""
    from mnexus.engines import PlayIntelEngine as _PIE
    assert _PIE is PlayIntelEngine
    # And the engine instance is a subclass of it — so isinstance
    # checks against the legacy class still pass.
    cfg = NexusConfig()
    engine = FirebaseIntelEngine(cfg)
    assert isinstance(engine, PlayIntelEngine)


def test_pipeline_executor_playintel_handler_still_resolves() -> None:
    """The pipeline executor's handler table keys on ('playintel', 'scan').
    Renaming shouldn't break existing YAML pipelines that reference
    the old engine name."""
    from mnexus.runtime.pipeline_executor import _STAGE_HANDLERS
    assert ("playintel", "scan") in _STAGE_HANDLERS
