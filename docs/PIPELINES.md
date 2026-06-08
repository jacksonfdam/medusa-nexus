# Pipelines — YAML → real engine calls

The Pipeline Editor screen has displayed YAML since v0; what's new is
that hitting `[ RUN ]` now actually runs each stage against the
target project.

## Built-ins

Listed by `GET /v1/pipelines`:

| Name | What it does |
|---|---|
| `full_assessment` | intake → static fan-out (parallel jadx + mobsf + ghidra) → dynamic prep → dynamic analysis → report |
| `static_only` | apktool → jadx → mobsf → markdown report |

Each carries a `yaml` field with the full definition. Hit
`GET /v1/pipelines/<name>` for one.

## Running

### Named built-in

```http
POST /v1/pipelines/full_assessment/run
Content-Type: application/x-www-form-urlencoded

project_id=PRJ-355151DF
```

Returns the completed `PipelineRun` synchronously:

```json
{
  "run_id": "a4b2c8e0d1",
  "pipeline_name": "full_assessment",
  "project_id": "PRJ-355151DF",
  "started_at": 1747000000.123,
  "finished_at": 1747000045.678,
  "state": "ok",
  "stages": [
    {"name": "intake", "engine": "apktool", "action": "decode",
     "status": "ok", "duration_ms": 412,
     "output": {"decoded_components": 18, "deeplinks": 5, "permissions": 12}},
    {"name": "static_scan.0", "engine": "jadx", "action": "decompile",
     "status": "ok", "duration_ms": 8210, "output": {"findings": 18}},
    {"name": "static_scan.1", "engine": "mobsf", "action": "full_scan",
     "status": "skipped", "error": "no handler returned None — skipped",
     "duration_ms": 1},
    …
  ]
}
```

### Ad-hoc YAML

```http
POST /v1/pipelines/run-yaml
Content-Type: application/x-www-form-urlencoded

yaml_body=name%3A+probe%0Astages%3A%0A++-+name%3A+a%0A++++engine%3A+jadx%0A++++action%3A+decompile&project_id=PRJ-355151DF
```

Same response shape.

### Polling

`GET /v1/pipelines/runs/{run_id}` returns the stored run. Process-local
registry — runs don't survive uvicorn restarts. The artefacts each stage
produced (findings in `dynamic_events`, reports on disk) survive
because their respective engines persist them.

## Stage handlers

Table-driven dispatch in `mnexus.runtime.pipeline_executor._STAGE_HANDLERS`.
Adding a new (engine, action) pair is one entry.

| `engine` | `action` | Handler does |
|---|---|---|
| `apktool` | `decode` | Confirms the static decode already ran during ingest; surfaces component/deeplink/permission counts |
| `jadx` | `decompile` | `JADXEngine.execute(ctx)` |
| `mobsf` | `full_scan` | `MobSFEngine.execute(ctx)` |
| `ghidra` | `analyze_native_libs` | `GhidraEngine.execute(ctx)` |
| `playintel` | `scan` | Re-runs PlayIntel against the project's stored APK |
| `stheno` | `patch` | `APKPatcher.patch(...)`; `patches` from stage params |
| `reporter` | `generate` | `ReportGenerator.generate(...)`; `template` + `formats` from stage params |
| `frida` | `run_session` | Soft-skip — live attach is better launched from the Dynamic tab |

Unknown `(engine, action)` pairs land on `skipped` (not `failed`) so a
typo doesn't abort the run. A handler that raises lands the stage on
`failed` but the executor continues; the run state is `failed` overall
if any stage failed, `ok` otherwise.

## YAML schema

```yaml
name: my_pipeline               # display name
version: 1
stages:
  - name: intake                # any unique label
    engine: apktool
    action: decode

  - name: static_scan
    parallel: true              # run children via asyncio.gather
    steps:
      - { engine: jadx,   action: decompile }
      - { engine: mobsf,  action: full_scan }
      - { engine: ghidra, action: analyze_native_libs }

  - name: dynamic_prep
    engine: stheno
    action: patch
    patches: [user_ca_trust, debuggable]   # forwarded as stage params

  - name: report
    engine: reporter
    action: generate
    template: technical                    # executive | technical | owasp-matrix | diff
    formats: [pdf, html, markdown, json]
    mitigation_playbook: true              # enforced regardless of this flag
```

Parallel groups (`parallel: true` + `steps:`) flatten in the run log
with names like `static_scan.0`, `static_scan.1`. They still execute
concurrently inside `asyncio.gather`.

## REPL

```
mnexus> /pipeline list
  full_assessment       Full Security Assessment
  static_only           Static-only sweep

mnexus> /pipeline run static_only --project PRJ-355151DF
running pipeline static_only against PRJ-355151DF…
✓ run a4b2c8e0d1 · state ok · 4 stage(s)
  ok       intake                   apktool/decode                   412ms
  ok       static_scan.0            jadx/decompile                  8210ms
  ok       static_scan.1            mobsf/full_scan                   45ms  (skipped if MobSF unreachable)
  ok       report                   reporter/generate                 90ms
```
