"""Live runtime — Frida sessions, hooks, event streaming.

This is the dynamic counterpart to ``mnexus.engines`` (which is mostly
static analysis tools). Lives in its own package because ``frida`` is
optional at install time — projects that only care about static scans
shouldn't have to install the C extension.

Public surface::

    from mnexus.runtime import FridaSession, session_registry, FRIDA_AVAILABLE
"""

from __future__ import annotations

from mnexus.runtime.frida_session import (
    FRIDA_AVAILABLE,
    FridaNotInstalled,
    FridaSession,
    FridaSessionError,
    NoDeviceError,
    session_registry,
)

__all__ = [
    "FRIDA_AVAILABLE",
    "FridaNotInstalled",
    "FridaSession",
    "FridaSessionError",
    "NoDeviceError",
    "session_registry",
]
