"""VPhoneEngine — unit tests for the helpers + doctor.

We never spawn a real super-tart subprocess in the test suite. The engine's
public methods (start/stop/ssh/scp/install_ipa) are exercised through API
tests (`test_vphone_api.py`) where the absence of `tart` on PATH gives us
a deterministic 503 path. Here we focus on the pure-Python helpers that
shape the data the API returns.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from mnexus.config import NexusConfig
from mnexus.engines.vphone_engine import (
    VPhoneEngine,
    _normalize_list_row,
    _parse_list_table,
)


@pytest.fixture
def engine() -> VPhoneEngine:
    return VPhoneEngine(NexusConfig())


# ─── _parse_list_table ───────────────────────────────────────────────────

def test_parse_list_table_handles_header_only_output() -> None:
    out = "Source  Name  Disk  Size  State"
    assert _parse_list_table(out) == []


def test_parse_list_table_extracts_running_flag_from_state_column() -> None:
    out = (
        "Source  Name      Disk  Size  State\n"
        "local   ios-test  /tmp  18GB  running\n"
        "local   ios-cold  /tmp  18GB  stopped\n"
    )
    rows = _parse_list_table(out)
    assert len(rows) == 2
    assert rows[0]["name"] == "ios-test"
    assert rows[0]["state"] == "running"
    assert rows[0]["running"] is True
    assert rows[1]["running"] is False


def test_parse_list_table_is_tolerant_to_short_rows() -> None:
    """A row missing trailing columns should still parse (zip stops at the shorter)."""
    out = "Source  Name      Disk  Size  State\nlocal   broken-row\n"
    rows = _parse_list_table(out)
    assert len(rows) == 1
    assert rows[0]["name"] == "broken-row"
    # Missing columns get padded as empty strings, so `running` is False.
    assert rows[0]["running"] is False


# ─── _normalize_list_row ────────────────────────────────────────────────

def test_normalize_list_row_handles_capitalized_keys() -> None:
    row = {"Name": "vphone-13", "State": "running", "Source": "local"}
    norm = _normalize_list_row(row)
    assert norm["name"] == "vphone-13"
    assert norm["running"] is True


def test_normalize_list_row_defaults_state_to_stopped() -> None:
    norm = _normalize_list_row({"name": "fresh-vm"})
    assert norm["state"] == "stopped"
    assert norm["running"] is False


# ─── _resolve_tart_bin ──────────────────────────────────────────────────

def test_resolve_tart_bin_prefers_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "tart"
    fake.write_text("#!/bin/sh\necho 1.0")
    fake.chmod(0o755)
    cfg = NexusConfig(tart_bin=fake)
    eng = VPhoneEngine(cfg)
    monkeypatch.delenv("MNEXUS_TART_BIN", raising=False)
    assert eng._resolve_tart_bin() == fake


def test_resolve_tart_bin_falls_back_to_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "tart"
    fake.write_text("")
    eng = VPhoneEngine(NexusConfig())
    monkeypatch.setenv("MNEXUS_TART_BIN", str(fake))
    assert eng._resolve_tart_bin() == fake


def test_resolve_tart_bin_returns_none_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEXUS_TART_BIN", raising=False)
    eng = VPhoneEngine(NexusConfig())
    # Final fallback would be ~/.mnexus/tools/vphone/bin/tart — point HOME at
    # an empty dir so that path doesn't exist.
    monkeypatch.setenv("HOME", "/tmp/__mnexus_no_home__")
    assert eng._resolve_tart_bin() is None


# ─── doctor health_check ───────────────────────────────────────────────

def test_health_check_reports_setup_hint_when_unconfigured(
    engine: VPhoneEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MNEXUS_TART_BIN", raising=False)
    monkeypatch.setenv("HOME", "/tmp/__mnexus_no_home__")
    status = asyncio.run(engine.health_check())
    assert status.installed is False
    assert "setup-vphone" in status.message


def test_health_check_returns_path_when_binary_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use a tiny shell stub that fakes `tart --version` + `tart list`."""
    fake = tmp_path / "tart"
    fake.write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        '  --version) echo "tart 0.0.0-test" ;;\n'
        '  list) echo "Source  Name  Disk  Size  State"; echo "local   testvm  /tmp  10G  stopped" ;;\n'
        '  *) echo "" ;;\n'
        'esac\n'
    )
    fake.chmod(0o755)
    cfg = NexusConfig(tart_bin=fake)
    eng = VPhoneEngine(cfg)
    monkeypatch.delenv("MNEXUS_TART_BIN", raising=False)

    status = asyncio.run(eng.health_check())
    assert status.installed is True
    assert "tart 0.0.0-test" in (status.version or "")
    assert "research mode" in status.message
    assert "1 VM" in status.message  # one row in our fake `tart list`
    assert status.path == str(fake)


# ─── execute always returns [] ─────────────────────────────────────────

def test_execute_never_produces_findings(engine: VPhoneEngine) -> None:
    from mnexus.engines.base import AnalysisContext
    ctx = AnalysisContext(apk_path=Path("/dev/null"), workspace=Path("/tmp"))
    findings = asyncio.run(engine.execute(ctx))
    assert findings == []
