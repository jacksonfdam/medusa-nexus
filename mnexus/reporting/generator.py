"""ReportGenerator — turns a Project into PDF/HTML/Markdown/JSON.

Every template renders a **Mitigation Playbook** section. The invariant is
enforced in `_compile_report_data`: a report that reaches `render` without
per-finding remediation populated will raise. Silence is not a finding;
silence is not a report either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from mnexus.models.finding import Finding, FindingCategory, Severity
from mnexus.models.project import Project


class ReportTemplate(str, Enum):
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    OWASP_MATRIX = "owasp-matrix"
    DIFF = "diff"


class ReportFormat(str, Enum):
    PDF = "pdf"
    HTML = "html"
    MARKDOWN = "markdown"
    JSON = "json"


@dataclass(slots=True)
class MitigationEntry:
    """One line of the Mitigation Playbook. Tied to a finding."""

    finding_id: str
    severity: Severity
    category: FindingCategory
    title: str
    remediation: str  # never empty — invariant enforced below


@dataclass(slots=True)
class ReportData:
    """Fully resolved report payload. Handed to the template renderer."""

    project: Project
    executive_summary: str
    risk_score: float
    findings_by_severity: dict[str, int]
    findings_by_category: dict[str, int]
    mitigation_playbook: list[MitigationEntry]
    all_findings: list[Finding]
    stats: dict[str, int] = field(default_factory=dict)


class ReportGenerator:
    """Builds a ReportData from a Project and dispatches to a format renderer."""

    def __init__(self, project: Project) -> None:
        self.project = project

    # ─── public ───

    def generate(self, template: ReportTemplate, fmt: ReportFormat, output_path: str) -> str:
        """Render the report to disk and return the absolute output path."""
        data = self._compile_report_data()
        renderers = {
            ReportFormat.MARKDOWN: self._render_markdown,
            ReportFormat.JSON: self._render_json,
            ReportFormat.HTML: self._render_html,
            ReportFormat.PDF: self._render_pdf,
        }
        return renderers[fmt](data, template, output_path)

    # ─── data pipeline ───

    def _compile_report_data(self) -> ReportData:
        findings = self._collect_findings()
        mitigation_playbook = self._build_mitigation_playbook(findings)
        return ReportData(
            project=self.project,
            executive_summary=self._executive_summary(findings),
            risk_score=self._calculate_risk_score(findings),
            findings_by_severity=self._count_by(findings, lambda f: f.severity.value),
            findings_by_category=self._count_by(findings, lambda f: f.category.value),
            mitigation_playbook=mitigation_playbook,
            all_findings=findings,
            stats={"total": len(findings)},
        )

    def _collect_findings(self) -> list[Finding]:
        if self.project.attack_surface:
            return [*self.project.attack_surface.findings, *self.project.dynamic_results]
        return list(self.project.dynamic_results)

    def _build_mitigation_playbook(self, findings: list[Finding]) -> list[MitigationEntry]:
        """Emit one entry per finding. Raise if a blocker is missing remediation.

        CRITICAL/HIGH findings are already forced to have remediation at
        construction time — this is belt-and-suspenders in case a bad loader
        slipped one in via legacy JSON.
        """
        order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
        sorted_findings = sorted(findings, key=lambda f: order.index(f.severity))
        playbook: list[MitigationEntry] = []
        for f in sorted_findings:
            remediation = f.remediation or ""
            if f.severity in (Severity.CRITICAL, Severity.HIGH) and not remediation.strip():
                raise ValueError(
                    f"finding {f.id} is {f.severity.value} but has no remediation — "
                    f"report generation refuses to produce silent blockers"
                )
            if not remediation.strip():
                remediation = "— no explicit remediation; informational finding."
            playbook.append(
                MitigationEntry(
                    finding_id=f.id,
                    severity=f.severity,
                    category=f.category,
                    title=f.title,
                    remediation=remediation,
                )
            )
        return playbook

    def _executive_summary(self, findings: list[Finding]) -> str:
        crits = sum(1 for f in findings if f.severity is Severity.CRITICAL)
        highs = sum(1 for f in findings if f.severity is Severity.HIGH)
        if crits == 0 and highs == 0:
            return "No critical or high-severity issues identified. Sleep is permissible."
        return (
            f"{crits} critical and {highs} high-severity findings block release. "
            "Full list, evidence, and mitigation steps below."
        )

    def _calculate_risk_score(self, findings: list[Finding]) -> float:
        if not findings:
            return 0.0
        total = sum(f.severity_weight for f in findings)
        return round((total / (len(findings) * 10.0)) * 100.0, 1)

    def _count_by(self, findings: list[Finding], key) -> dict[str, int]:  # type: ignore[no-untyped-def]
        out: dict[str, int] = {}
        for f in findings:
            k = key(f)
            out[k] = out.get(k, 0) + 1
        return out

    # ─── renderers ───

    def _render_markdown(self, data: ReportData, template: ReportTemplate, output_path: str) -> str:
        lines: list[str] = []
        lines.append(f"# MEDUSA NEXUS // {template.value.upper()} — {data.project.name}")
        lines.append("")
        lines.append(f"- package: `{data.project.package_name}`")
        lines.append(f"- version: `{data.project.version_name}`")
        lines.append(f"- sha-256: `{data.project.apk_sha256}`")
        lines.append(f"- risk score: **{data.risk_score}/100**")
        lines.append("")
        lines.append("## Executive summary")
        lines.append("")
        lines.append(data.executive_summary)
        lines.append("")
        lines.append("## Findings by severity")
        lines.append("")
        for sev, n in data.findings_by_severity.items():
            lines.append(f"- `{sev.upper()}` — {n}")
        lines.append("")
        lines.append("## Mitigation Playbook")
        lines.append("")
        lines.append("Every finding ships with remediation. If a block below is empty, the build is broken.")
        lines.append("")
        for entry in data.mitigation_playbook:
            lines.append(f"### {entry.finding_id} · {entry.severity.value.upper()} · {entry.title}")
            lines.append("")
            lines.append(entry.remediation)
            lines.append("")
        rendered = "\n".join(lines)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        return output_path

    def _render_json(self, data: ReportData, template: ReportTemplate, output_path: str) -> str:
        import json

        payload = {
            "template": template.value,
            "project": data.project.model_dump(mode="json"),
            "risk_score": data.risk_score,
            "executive_summary": data.executive_summary,
            "findings_by_severity": data.findings_by_severity,
            "findings_by_category": data.findings_by_category,
            "mitigation_playbook": [
                {
                    "finding_id": e.finding_id,
                    "severity": e.severity.value,
                    "category": e.category.value,
                    "title": e.title,
                    "remediation": e.remediation,
                }
                for e in data.mitigation_playbook
            ],
            "findings": [f.model_dump(mode="json") for f in data.all_findings],
        }
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        return output_path

    def _render_html(self, data: ReportData, template: ReportTemplate, output_path: str) -> str:  # pragma: no cover - stub
        """HTML rendering lives in Jinja templates. Stubbed until templates land."""
        _ = data, template
        raise NotImplementedError("html renderer pending — see mnexus/reporting/templates/")

    def _render_pdf(self, data: ReportData, template: ReportTemplate, output_path: str) -> str:  # pragma: no cover - stub
        """PDF = HTML → headless Chromium. Stubbed until the HTML path exists."""
        _ = data, template
        raise NotImplementedError("pdf renderer pending — built on top of html renderer")
