"""Intelligence layer — the brain *between* engines.

Cross-engine correlation + auto-generated Frida hooks. This is the value add;
everything else is just wrapping other people's tools.
"""

from mnexus.intelligence.correlator import FindingCorrelator
from mnexus.intelligence.hook_generator import HookGenerator

__all__ = ["FindingCorrelator", "HookGenerator"]
