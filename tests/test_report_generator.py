"""Report generator: every render carries the Mitigation Playbook."""

from __future__ import annotations

import json
from pathlib import Path

from mnexus.models.project import Project
from mnexus.reporting.generator import ReportFormat, ReportGenerator, ReportTemplate


def test_markdown_report_contains_mitigation_playbook(sample_project: Project, tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    ReportGenerator(sample_project).generate(ReportTemplate.TECHNICAL, ReportFormat.MARKDOWN, str(out))

    text = out.read_text()
    assert "Mitigation Playbook" in text
    assert "Android Keystore" in text  # from the fixture's remediation
    assert "CRITICAL" in text.upper()


def test_json_report_contains_mitigation_playbook(sample_project: Project, tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    ReportGenerator(sample_project).generate(ReportTemplate.TECHNICAL, ReportFormat.JSON, str(out))

    payload = json.loads(out.read_text())
    assert "mitigation_playbook" in payload
    playbook = payload["mitigation_playbook"]
    assert len(playbook) >= 1

    critical_entries = [e for e in playbook if e["severity"] == "critical"]
    assert critical_entries
    assert critical_entries[0]["remediation"]
    assert "keystore" in critical_entries[0]["remediation"].lower()


def test_risk_score_is_bounded(sample_project: Project, tmp_path: Path) -> None:
    gen = ReportGenerator(sample_project)
    data = gen._compile_report_data()
    assert 0.0 <= data.risk_score <= 100.0
