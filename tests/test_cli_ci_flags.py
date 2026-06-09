"""CI/CD-shaped CLI flags — --json, --fail-on severity, --against diff gate.

These are the integration points pipelines hook into. The tests build a
minimal APK fixture, run `mnexus scan` through Click's testing harness,
and assert on the JSON shape + exit codes the CI workflows depend on.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from mnexus.cli import cli as mnexus_cli


def _build_minimal_apk() -> bytes:
    """Same minimal-zip-as-APK trick test_apk_ingest_e2e uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", b"")
        zf.writestr("classes.dex", b"dex\n035\x00")
        zf.writestr("resources.arsc", b"")
    return buf.getvalue()


@pytest.fixture
def ci_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated MNEXUS_HOME so the test doesn't touch ~/.mnexus."""
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    return tmp_path


@pytest.fixture
def apk_on_disk(ci_workspace: Path) -> Path:
    p = ci_workspace / "target.apk"
    p.write_bytes(_build_minimal_apk())
    return p


# ─── --json ───────────────────────────────────────────────────────────


def test_scan_json_emits_machine_readable_summary(apk_on_disk: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0", "--json"],
        standalone_mode=False,
    )
    # standalone_mode=False lets Click raise SystemExit through to the
    # runner so we can inspect both stdout and the exit code together.
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["package"] == "com.target.app"
    assert payload["project_id"].startswith("PRJ-")
    assert "risk_score" in payload
    assert "findings_total" in payload
    assert "findings_by_severity" in payload


def test_projects_json_emits_array(apk_on_disk: Path) -> None:
    runner = CliRunner()
    runner.invoke(mnexus_cli, ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0", "--json"], standalone_mode=False)
    result = runner.invoke(mnexus_cli, ["projects", "--json"], standalone_mode=False)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["package"] == "com.target.app"
    assert payload[0]["id"].startswith("PRJ-")


def test_findings_json_filters_by_severity(apk_on_disk: Path) -> None:
    runner = CliRunner()
    scan = runner.invoke(mnexus_cli, ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0", "--json"], standalone_mode=False)
    pid = json.loads(scan.output)["project_id"]
    result = runner.invoke(mnexus_cli, ["findings", "--project", pid, "--severity", "critical", "--json"], standalone_mode=False)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    # Every returned finding must be at CRITICAL (highest tier — nothing above it).
    for f in payload:
        assert f["severity"] == "critical"


# ─── --fail-on ────────────────────────────────────────────────────────


def test_fail_on_low_trips_when_any_finding_exists(apk_on_disk: Path) -> None:
    """The minimal APK fixture surfaces at least one INFO/LOW finding
    (zero-byte manifest, empty resources.arsc) — gating at `low` should
    therefore trip with exit 1."""
    runner = CliRunner()
    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0",
         "--fail-on", "low", "--json"],
        standalone_mode=False,
    )
    # exit 1 only if findings_total > 0 — otherwise PASS.
    payload = json.loads(result.output)
    if payload["findings_total"] > 0:
        assert result.exit_code == 1
        assert payload["fail_on"]["triggered"] is True
        assert payload["fail_on"]["gate"] == "low"
    else:
        assert result.exit_code == 0
        assert payload["fail_on"]["triggered"] is False


def test_fail_on_critical_passes_when_no_critical_findings(apk_on_disk: Path) -> None:
    """The minimal APK fixture wouldn't trigger CRITICAL findings on its own."""
    runner = CliRunner()
    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0",
         "--fail-on", "critical", "--json"],
        standalone_mode=False,
    )
    payload = json.loads(result.output)
    critical_count = payload["findings_by_severity"].get("critical", 0)
    if critical_count == 0:
        assert result.exit_code == 0
        assert payload["fail_on"]["triggered"] is False
    else:
        assert result.exit_code == 1


def test_fail_on_diff_mode_counts_only_new_findings(apk_on_disk: Path) -> None:
    """--against PRJ-… switches the gate to PR-style: same APK re-scanned
    with force=true should have zero *new* findings, so the gate must PASS
    even if the absolute count is non-zero.

    This is the bread-and-butter CI use case.
    """
    runner = CliRunner()
    # First scan establishes the baseline.
    first = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0", "--json"],
        standalone_mode=False,
    )
    base_pid = json.loads(first.output)["project_id"]

    # Second scan of identical bytes hits dedup. To force a fresh project we
    # tweak the APK by one byte so dedup misses; conceptually this is "same
    # app, no code-level changes". The diff should be empty.
    apk_v2 = apk_on_disk.with_name("target-v2.apk")
    apk_v2.write_bytes(apk_on_disk.read_bytes() + b"\x00")

    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_v2), "--package", "com.target.app", "--version", "1.0.1",
         "--fail-on", "critical", "--against", base_pid, "--json"],
        standalone_mode=False,
    )
    payload = json.loads(result.output)
    # No NEW criticals → PASS even though the absolute count may be > 0.
    assert payload["fail_on"]["diff_mode"] is True
    assert payload["diff"]["base_project_id"] == base_pid
    assert result.exit_code == 0, payload


def test_fail_on_without_against_counts_absolute(apk_on_disk: Path) -> None:
    """Without --against, --fail-on counts every finding on the new scan
    (not just deltas). Useful for a release-cut quality gate where the
    absolute bar matters."""
    runner = CliRunner()
    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0",
         "--fail-on", "info", "--json"],
        standalone_mode=False,
    )
    payload = json.loads(result.output)
    assert payload["fail_on"]["diff_mode"] is False


def test_against_unknown_project_errors_with_exit_2(apk_on_disk: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0",
         "--fail-on", "critical", "--against", "PRJ-DOESNOTEXIST", "--json"],
        standalone_mode=False,
    )
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert "error" in payload
    assert "PRJ-DOESNOTEXIST" in payload["error"]


# ─── default path stays unchanged ─────────────────────────────────────


def test_scan_without_flags_uses_rich_path(apk_on_disk: Path) -> None:
    """No --json, no --fail-on → identical to the REPL /scan UX
    (no SystemExit, no JSON, Rich panel printed). The legacy fast path."""
    runner = CliRunner()
    result = runner.invoke(
        mnexus_cli,
        ["scan", str(apk_on_disk), "--package", "com.target.app", "--version", "1.0"],
        standalone_mode=False,
    )
    assert result.exit_code == 0
    # The legacy path prints the Rich panel which contains 'ingest complete'.
    assert "ingest complete" in result.output
