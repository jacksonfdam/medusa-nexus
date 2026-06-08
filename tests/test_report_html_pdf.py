"""ReportGenerator HTML + PDF renderers.

Until now both render paths raised NotImplementedError. The new HTML
renderer goes through a single Jinja2 template; PDF tries WeasyPrint
when available and falls back to a printable HTML file with a comment
banner otherwise.

Coverage:
  * HTML renders end-to-end for each template (executive / technical /
    owasp-matrix / diff) and ships the Mitigation Playbook section.
  * Every CRITICAL/HIGH finding's remediation appears in the rendered HTML.
  * The OWASP matrix template renders the MASVS table.
  * Severity chips use the right CSS class.
  * Jinja autoescape protects against HTML injection in finding fields.
  * PDF without weasyprint falls back to .html with a comment marker.
  * PDF with weasyprint (monkeypatched) writes through to the .pdf path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from mnexus.models.attack_surface import AttackSurface
from mnexus.models.finding import Finding, FindingCategory, Severity
from mnexus.models.project import Project
from mnexus.reporting.generator import (
    ReportFormat,
    ReportGenerator,
    ReportTemplate,
    _build_masvs_matrix,
    _sev_chip_class,
    _template_label,
)


# ─── fixtures ─────────────────────────────────────────────────────────


def _finding(
    *,
    title="Static (zero) IV with AES",
    severity=Severity.CRITICAL,
    category=FindingCategory.CRYPTO,
    masvs="MSTG-CRYPTO-3",
    remediation="Use SecureRandom.getInstanceStrong() to seed the IV instead of zeros.",
    description="The Cipher init used a zero IV — every encryption is deterministic.",
    evidence='Cipher.init(Cipher.ENCRYPT_MODE, key, new IvParameterSpec(new byte[16]))',
) -> Finding:
    return Finding(
        title=title, description=description, severity=severity, category=category,
        source_engine="jadx", evidence=evidence, masvs=masvs, remediation=remediation,
        location="com.target.app/Cipher.java:42", cwe_id="CWE-329",
    )


@pytest.fixture
def project(tmp_path) -> Project:
    apk = tmp_path / "target.apk"
    apk.write_bytes(b"PK\x03\x04stub")
    surface = AttackSurface(
        findings=[
            _finding(),
            _finding(
                title="Cleartext HTTP to api.target.com",
                severity=Severity.HIGH,
                category=FindingCategory.NETWORK,
                masvs="MSTG-NETWORK-1",
                remediation="Move api.target.com to HTTPS and pin the certificate.",
            ),
            _finding(
                title="Insecure storage in shared prefs",
                severity=Severity.MEDIUM,
                category=FindingCategory.STORAGE,
                masvs="MSTG-STORAGE-1",
                remediation="Use EncryptedSharedPreferences (androidx.security).",
            ),
        ],
    )
    return Project(
        id="PRJ-RPT00001",
        name="Target",
        apk_path=apk,
        apk_sha256="ab" * 32,
        package_name="com.target.app",
        version_name="1.2.3",
        version_code=42,
        attack_surface=surface,
    )


# ─── helper unit tests ────────────────────────────────────────────────


def test_sev_chip_class_maps_known_severities() -> None:
    assert _sev_chip_class(Severity.CRITICAL) == "crit"
    assert _sev_chip_class(Severity.HIGH) == "high"
    assert _sev_chip_class(Severity.MEDIUM) == "med"
    assert _sev_chip_class(Severity.LOW) == "low"
    assert _sev_chip_class(Severity.INFO) == "info"
    # Accepts plain strings too (Jinja may pass either)
    assert _sev_chip_class("critical") == "crit"
    # Unknown falls back to info — the chip stays visible.
    assert _sev_chip_class("mystery") == "info"


def test_template_label_returns_human_titles() -> None:
    assert _template_label(ReportTemplate.EXECUTIVE) == "EXECUTIVE"
    assert _template_label(ReportTemplate.TECHNICAL) == "TECHNICAL"
    assert _template_label(ReportTemplate.OWASP_MATRIX) == "OWASP MASVS MATRIX"


def test_masvs_matrix_aggregates_by_tag_with_highest_severity() -> None:
    findings = [
        _finding(masvs="MSTG-CRYPTO-3", severity=Severity.CRITICAL),
        _finding(masvs="MSTG-CRYPTO-3", severity=Severity.LOW),
        _finding(masvs="MSTG-NETWORK-1", severity=Severity.HIGH),
        _finding(masvs=None, severity=Severity.MEDIUM),  # no MASVS → dropped
    ]
    rows = _build_masvs_matrix(findings)
    by_tag = {r["tag"]: r for r in rows}
    assert by_tag["MSTG-CRYPTO-3"]["count"] == 2
    # CRITICAL beats LOW → highest is critical.
    assert by_tag["MSTG-CRYPTO-3"]["highest"] == "critical"
    assert by_tag["MSTG-NETWORK-1"]["count"] == 1
    assert "MSTG-NONE" not in by_tag


# ─── HTML renderer ────────────────────────────────────────────────────


def test_html_render_creates_file_with_mitigation_playbook(project, tmp_path) -> None:
    out = tmp_path / "report.html"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.HTML, str(out),
    )
    assert Path(written).exists()
    body = Path(written).read_text(encoding="utf-8")
    assert "MEDUSA NEXUS" in body
    # Mitigation Playbook section is mandatory (spec invariant).
    assert "Mitigation Playbook" in body
    # Each finding's remediation must appear in the rendered HTML.
    for f in project.attack_surface.findings:
        assert f.remediation in body


def test_html_render_executive_template_omits_full_findings_dump(project, tmp_path) -> None:
    """Executive template renders the playbook but not the full findings
    dump — that section only fires for technical / diff. Pinning so a
    future template change doesn't silently bloat the executive report.
    """
    out = tmp_path / "exec.html"
    ReportGenerator(project).generate(ReportTemplate.EXECUTIVE, ReportFormat.HTML, str(out))
    body = out.read_text(encoding="utf-8")
    # Mitigation Playbook is present everywhere.
    assert "Mitigation Playbook" in body
    # The '// Findings' section header (rendered as h2 with that text)
    # only appears in technical/diff. Distinguish from the chip-row
    # 'Findings by severity' heading.
    assert "// Findings</h2>" not in body
    assert "// Findings by severity" in body


def test_html_render_owasp_matrix_includes_masvs_table(project, tmp_path) -> None:
    out = tmp_path / "owasp.html"
    ReportGenerator(project).generate(ReportTemplate.OWASP_MATRIX, ReportFormat.HTML, str(out))
    body = out.read_text(encoding="utf-8")
    assert "OWASP MASVS coverage" in body
    # Three findings, two distinct MASVS tags (CRYPTO + NETWORK + STORAGE).
    assert "MSTG-CRYPTO-3" in body
    assert "MSTG-NETWORK-1" in body
    assert "MSTG-STORAGE-1" in body
    # Table chip uses the right class — chip-crit for the critical CRYPTO
    # finding ('chip chip-crit' substring).
    assert "chip chip-crit" in body


def test_html_render_escapes_user_input_in_finding_fields(tmp_path) -> None:
    """Jinja autoescape must keep <script> in evidence/title from
    breaking out of the rendered page."""
    apk = tmp_path / "x.apk"
    apk.write_bytes(b"PK\x03\x04stub")
    surface = AttackSurface(findings=[
        _finding(
            title='<script>alert("xss")</script>',
            severity=Severity.HIGH,
            category=FindingCategory.NETWORK,
            evidence='<img src=x onerror=alert(1)>',
            remediation='<script>1</script>fix it',
        ),
    ])
    p = Project(
        id="PRJ-XSS00001", name="xss", apk_path=apk, apk_sha256="cd" * 32,
        package_name="x.y", version_name="1", attack_surface=surface,
    )
    out = tmp_path / "xss.html"
    ReportGenerator(p).generate(ReportTemplate.TECHNICAL, ReportFormat.HTML, str(out))
    body = out.read_text(encoding="utf-8")
    # The dangerous payloads must not appear verbatim — should be HTML-escaped.
    assert '<script>alert("xss")</script>' not in body
    assert '<img src=x onerror=alert(1)>' not in body
    # But the escaped versions must be present.
    assert "&lt;script&gt;alert" in body or "&lt;script&gt;" in body


def test_html_render_dispatches_via_generate_entry_point(project, tmp_path) -> None:
    """The public entry-point `generate(template, fmt, path)` must
    dispatch HTML correctly (was the NotImplementedError path)."""
    out = tmp_path / "via-entry.html"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.HTML, str(out),
    )
    assert written == str(out)
    assert "MEDUSA NEXUS" in Path(written).read_text(encoding="utf-8")


# ─── PDF renderer ─────────────────────────────────────────────────────


def test_pdf_renderer_falls_back_to_html_when_weasyprint_missing(
    project, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No WeasyPrint → write HTML with a comment marker instead of crashing."""
    import sys
    # Force WeasyPrint to look unavailable for this test even if the
    # dev machine has it installed.
    monkeypatch.setitem(sys.modules, "weasyprint", None)

    out = tmp_path / "report.pdf"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.PDF, str(out),
    )
    written_path = Path(written)
    # PDF target didn't materialise — HTML did.
    assert not out.exists() or written_path != out
    assert written_path.suffix == ".html"
    body = written_path.read_text(encoding="utf-8")
    assert "weasyprint not installed" in body
    assert "Mitigation Playbook" in body


# ─── PNG renderer ─────────────────────────────────────────────────────


def test_png_renderer_writes_html_when_chrome_missing(
    project, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Chromium on PATH → fall back to HTML with a banner comment."""
    monkeypatch.setattr("mnexus.reporting.generator._find_chromium", lambda: None)
    out = tmp_path / "report.png"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.PNG, str(out),
    )
    written_path = Path(written)
    assert written_path.suffix == ".html"
    body = written_path.read_text(encoding="utf-8")
    assert "chromium" in body.lower() or "google-chrome" in body.lower()
    assert "Mitigation Playbook" in body


def test_png_renderer_drives_chromium_with_screenshot_flag(
    project, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _find_chromium returns a binary, the renderer subprocess-
    runs it with --screenshot=<out> and writes a stub PNG."""
    import subprocess

    captured: list[list[str]] = []

    def fake_chromium() -> str:
        return "/fake/chromium"

    def fake_run(cmd, check=False, capture_output=False, timeout=None):  # noqa: ARG001, ANN001
        captured.append(list(cmd))
        # Find --screenshot=<path> and write stub PNG bytes there.
        for arg in cmd:
            if arg.startswith("--screenshot="):
                out_path = arg.split("=", 1)[1]
                Path(out_path).write_bytes(b"\x89PNG\r\n\x1a\n stub png")
                break

        class _Done:
            returncode = 0
            stdout = b""
            stderr = b""

        return _Done()

    monkeypatch.setattr("mnexus.reporting.generator._find_chromium", fake_chromium)
    monkeypatch.setattr("subprocess.run", fake_run)

    out = tmp_path / "report.png"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.PNG, str(out),
    )
    assert written == str(out)
    assert Path(written).exists()
    assert Path(written).read_bytes().startswith(b"\x89PNG")
    # Chrome was invoked with the right flags.
    assert captured, "subprocess.run was not called"
    cmd = captured[0]
    assert cmd[0] == "/fake/chromium"
    assert "--headless" in cmd
    assert any(a == f"--screenshot={out}" for a in cmd)
    assert any(a.startswith("file://") for a in cmd)


def test_png_renderer_falls_back_to_html_when_chrome_produces_nothing(
    project, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chrome ran but wrote no bytes (sandbox quirks on CI) → HTML fallback."""
    def fake_chromium() -> str:
        return "/fake/chromium"

    def fake_run(cmd, check=False, capture_output=False, timeout=None):  # noqa: ARG001, ANN001
        class _Done:
            returncode = 0
            stdout = b""
            stderr = b""
        return _Done()  # ← no file written

    monkeypatch.setattr("mnexus.reporting.generator._find_chromium", fake_chromium)
    monkeypatch.setattr("subprocess.run", fake_run)

    out = tmp_path / "report.png"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.PNG, str(out),
    )
    written_path = Path(written)
    assert written_path.suffix == ".html"
    body = written_path.read_text(encoding="utf-8")
    assert "wrote no bytes" in body
    assert "Mitigation Playbook" in body


def test_find_chromium_prefers_env_var(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MNEXUS_CHROME_BIN beats shutil.which."""
    from mnexus.reporting.generator import _find_chromium

    fake = tmp_path / "fake-chrome"
    fake.write_text("#!/bin/bash")
    monkeypatch.setenv("MNEXUS_CHROME_BIN", str(fake))
    monkeypatch.setattr("shutil.which", lambda name: "/should/be/ignored")
    picked = _find_chromium()
    assert picked == str(fake)


def test_pdf_renderer_writes_pdf_when_weasyprint_available(
    project, tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkeypatch a fake weasyprint module so the test runs even when
    WeasyPrint isn't installed (it pulls heavy native deps)."""
    import sys
    import types

    written_calls = []

    class _FakeHTML:
        def __init__(self, *, string):  # noqa: ARG002 — we want the kwarg
            self.string = string

        def write_pdf(self, output_path):
            written_calls.append(output_path)
            # Write something so the test can assert the file exists.
            Path(output_path).write_bytes(b"%PDF-1.4 stub\n")

    fake_module = types.ModuleType("weasyprint")
    fake_module.HTML = _FakeHTML
    monkeypatch.setitem(sys.modules, "weasyprint", fake_module)

    out = tmp_path / "report.pdf"
    written = ReportGenerator(project).generate(
        ReportTemplate.TECHNICAL, ReportFormat.PDF, str(out),
    )
    assert written == str(out)
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF-")
    assert written_calls == [str(out)]
