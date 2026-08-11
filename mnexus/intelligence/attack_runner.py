"""Attack runner — fire the device-executable subset and record verdicts.

The planner produces PROVABLE attempts with runnable PoCs. This runner takes
the ones that are safe to auto-fire against a bridged device — the adb
invocations (exported components, deep links) — runs them, and upgrades each
to CONFIRMED or DISPROVEN based on what the device said.

Deliberately narrow. Frida PoCs stay PROVABLE (script attached) because they
belong to the live ``/dynamic`` session, and the Firebase ``curl`` stays
PROVABLE because auto-firing a request at someone's backend is a decision a
human opts into, not a side effect of a scan. The caller injects ``run_poc``
so this module never imports adb or shells out itself — keeps it testable and
keeps the "am I allowed to touch a device" decision at the edge.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from mnexus.models.exploit import ExploitAttempt, ExploitVerdict, PocKind

# Substrings in adb/am output that mean the trigger was rejected. Presence =
# the control held (DISPROVEN); absence = it fired (CONFIRMED).
_FAILURE_MARKERS = (
    "permission denial",
    "does not exist",
    "securityexception",
    "java.lang.",
    "exception",
    "error:",
    "error type",
    "not found",
    "unable to resolve",
    "no activities found",
)

RunPoc = Callable[[str], Awaitable[str]]


def runnable(attempts: list[ExploitAttempt]) -> list[ExploitAttempt]:
    """The subset this runner will fire: adb PoCs that need a device."""
    return [a for a in attempts if a.poc_kind is PocKind.ADB and a.requires_device]


async def run_attacks(
    attempts: list[ExploitAttempt],
    run_poc: RunPoc,
    *,
    device_connected: bool,
) -> list[ExploitAttempt]:
    """Execute the runnable subset in place; return the ones that fired.

    Non-runnable attempts (Frida / curl / MANUAL) are left untouched at their
    PROVABLE/MANUAL verdict. When no device is connected nothing fires and the
    plan is returned unchanged.
    """
    fired: list[ExploitAttempt] = []
    if not device_connected:
        return fired
    for a in runnable(attempts):
        try:
            out = await run_poc(a.poc)
        except Exception as exc:  # noqa: BLE001 — a bad command shouldn't abort the run
            out = f"execution error: {exc.__class__.__name__}: {exc}"
        a.executed = True
        a.evidence = out[:4000]
        a.verdict = _verdict_from_output(out)
        fired.append(a)
    return fired


def _verdict_from_output(output: str) -> ExploitVerdict:
    low = output.lower()
    if any(marker in low for marker in _FAILURE_MARKERS):
        return ExploitVerdict.DISPROVEN
    return ExploitVerdict.CONFIRMED


def verdict_summary(attempts: list[ExploitAttempt]) -> dict[str, int]:
    """Count attempts by verdict — the header the report + UI show."""
    out: dict[str, int] = {}
    for a in attempts:
        out[a.verdict.value] = out.get(a.verdict.value, 0) + 1
    return out
