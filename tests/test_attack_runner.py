"""Attack runner — fires the adb subset, maps output to CONFIRMED/DISPROVEN."""

from __future__ import annotations

import pytest

from mnexus.intelligence.attack_runner import run_attacks, runnable, verdict_summary
from mnexus.models.exploit import ExploitAttempt, ExploitVerdict, PocKind


def _adb(poc: str = "adb shell am start -n com.t/.A") -> ExploitAttempt:
    return ExploitAttempt(
        technique="exported-activity", title="t", target="com.t/.A",
        verdict=ExploitVerdict.PROVABLE, poc_kind=PocKind.ADB, poc=poc,
        rationale="r", mitigation="m", requires_device=True,
    )


def _frida() -> ExploitAttempt:
    return ExploitAttempt(
        technique="ssl-pin-bypass", title="t", verdict=ExploitVerdict.PROVABLE,
        poc_kind=PocKind.FRIDA, poc="Java.perform(()=>{})", rationale="r",
        mitigation="m", requires_device=True,
    )


def test_runnable_picks_only_adb_device_pocs() -> None:
    attempts = [_adb(), _frida()]
    r = runnable(attempts)
    assert len(r) == 1
    assert r[0].poc_kind is PocKind.ADB


@pytest.mark.asyncio
async def test_no_device_fires_nothing() -> None:
    attempts = [_adb()]
    fired = await run_attacks(attempts, _fail_if_called, device_connected=False)
    assert fired == []
    assert attempts[0].verdict is ExploitVerdict.PROVABLE  # untouched


@pytest.mark.asyncio
async def test_clean_output_confirms() -> None:
    attempts = [_adb()]
    fired = await run_attacks(attempts, _ok, device_connected=True)
    assert len(fired) == 1
    assert attempts[0].verdict is ExploitVerdict.CONFIRMED
    assert attempts[0].executed is True
    assert "Status: ok" in attempts[0].evidence


@pytest.mark.asyncio
async def test_permission_denial_disproves() -> None:
    attempts = [_adb()]
    await run_attacks(attempts, _denied, device_connected=True)
    assert attempts[0].verdict is ExploitVerdict.DISPROVEN


@pytest.mark.asyncio
async def test_frida_is_never_auto_fired() -> None:
    attempts = [_frida()]
    fired = await run_attacks(attempts, _fail_if_called, device_connected=True)
    assert fired == []
    assert attempts[0].verdict is ExploitVerdict.PROVABLE


@pytest.mark.asyncio
async def test_run_error_is_captured_as_disproven() -> None:
    attempts = [_adb()]
    await run_attacks(attempts, _boom, device_connected=True)
    assert attempts[0].executed is True
    assert "execution error" in attempts[0].evidence
    assert attempts[0].verdict is ExploitVerdict.DISPROVEN


def test_verdict_summary_counts() -> None:
    a, b = _adb(), _adb()
    a.verdict = ExploitVerdict.CONFIRMED
    assert verdict_summary([a, b]) == {"confirmed": 1, "provable": 1}


async def _ok(_poc: str) -> str:
    return "Starting: Intent { ... }\nStatus: ok\nActivity: com.t/.A"


async def _denied(_poc: str) -> str:
    return "Starting: Intent { ... }\nSecurityException: Permission Denial: starting Intent"


async def _boom(_poc: str) -> str:
    raise RuntimeError("adb died")


async def _fail_if_called(_poc: str) -> str:
    raise AssertionError("run_poc should not have been called")
