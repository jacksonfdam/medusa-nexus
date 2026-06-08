# Reporting — Markdown / JSON / HTML / PDF with Mitigation Playbook

Four formats, four templates, one invariant: **every report ships a
Mitigation Playbook section**. The model layer enforces it — a
CRITICAL or HIGH finding without `remediation` raises at construction
time, before the report can render.

## Formats

| Format | Renderer | Dependency | Notes |
|---|---|---|---|
| `markdown` | inline writer | none | plain text, headers + bullet lists. Default for CI consumers. |
| `json` | inline writer | none | machine-readable payload — every finding's full body. |
| `html` | Jinja2 template | `jinja2>=3.1` (always installed) | single file, inline CSS, cyberpunk palette + `@media print` fallback for browser print-to-PDF. |
| `pdf` | WeasyPrint over HTML | `pip install weasyprint` (heavy native deps) | when WeasyPrint is missing, falls back to HTML with a banner comment so the analyst can browser-print themselves. |
| `png` | Chromium screenshot of HTML | `google-chrome` / `chromium` on PATH (or `MNEXUS_CHROME_BIN=…`) | runs `chrome --headless --screenshot=<out>` over a `file://` URL of the rendered HTML. Falls back to HTML on missing browser, sandbox failures, or empty output. Useful for executive decks — single image instead of a multi-page PDF. |

## Templates

`mnexus.reporting.generator.ReportTemplate`:

| Value | What renders |
|---|---|
| `executive` | Risk score · severity counts · **Mitigation Playbook only**. No full findings dump. For non-technical readers. |
| `technical` | Everything: severity counts · Mitigation Playbook · per-finding evidence + remediation. Default. |
| `owasp-matrix` | Adds an **OWASP MASVS coverage** table aggregating findings by `masvs` tag with the highest severity per tag. |
| `diff` | Same content shape as `technical` for now; tracked for a future iteration to overlay manifest-diff + findings-diff data. |

## Generating

### From the CLI / REPL

```
mnexus> /use PRJ-355151DF
mnexus> /report technical pdf
✓ wrote /Users/.../reports/PRJ-355151DF-technical.pdf
```

```
mnexus report --project PRJ-355151DF \
              --template technical --format pdf \
              --output ./report.pdf
```

### From the API

```http
GET /v1/projects/{id}/report?template=technical&format=html
```

…or via the pipeline executor (`engine: reporter, action: generate` —
see [`PIPELINES.md`](PIPELINES.md)).

### Directly

```python
from mnexus.reporting.generator import ReportGenerator, ReportFormat, ReportTemplate

generator = ReportGenerator(project)
generator.generate(ReportTemplate.TECHNICAL, ReportFormat.PDF, "./report.pdf")
```

## Mitigation Playbook contract

`mnexus/models/finding.py` enforces it via a Pydantic model validator:

```python
@model_validator(mode="after")
def _mitigation_required_for_blockers(self) -> Finding:
    if self.severity in (Severity.CRITICAL, Severity.HIGH) and not (self.remediation and self.remediation.strip()):
        raise ValueError(
            f"severity={self.severity.value} findings require a `remediation` — "
            "this is the whole point of the platform."
        )
    return self
```

The Playbook section sorts findings by severity (critical → info)
and emits one entry per finding with its remediation text. Informational
findings without remediation get a placeholder line so the section
stays visually consistent.

## XSS hardening

The HTML template uses Jinja2's autoescape — finding fields with
`<script>alert(1)</script>` get escaped to `&lt;script&gt;…` rather
than rendered. Pinning test in `tests/test_report_html_pdf.py`.

## Template source

Single file: `mnexus/reporting/templates/report.html.j2`. Self-contained
(inline CSS, no external assets) so the HTML download works as a
standalone file. `@media print` flips to a white background for
browser-print sessions that don't burn ink.
