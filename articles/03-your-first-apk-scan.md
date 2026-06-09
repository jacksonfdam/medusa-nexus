---
title: "Your first APK scan, end to end — in 10 minutes"
description: "A hands-on walkthrough of installing MedusaNexus, scanning an APK, reading the findings panel, exploring the web UI, and generating a report."
published: 2026-06-23
author: Jackson Mafra
tags: ["mobile-security", "android", "hands-on", "developers", "medusanexus"]
canonical: https://mnexus.vercel.app/articles/03-your-first-apk-scan
codex_refs:
  - "AVD Deep Dive — https://medium.com/@jacksonfdam/"
  - "Cuttlefish — https://medium.com/@jacksonfdam/"
medusa_refs:
  - https://github.com/jacksonfdam/medusa-nexus
tldr: |
  Install MedusaNexus, scan your first APK, and walk through the result — the findings
  panel, the attack surface, the web UI's project tabs, and a generated report — in
  about ten minutes of wall-clock time. Zero theory; pure muscle memory. Everything in
  this article is paste-and-run.
---

The previous two articles built the conceptual foundation: who looks at your mobile app, and what every term in a mobile threat report actually means. This one is the opposite — pure hands-on. By the end you will have installed MedusaNexus on your laptop, scanned an APK, walked through a project's findings, opened the web UI, and generated a report. Ten minutes of wall-clock time, mostly waiting for `pip install`.

You'll need one input: an Android APK file. If you don't have one handy, pick any app from your device and pull it:

```bash
adb shell pm list packages | grep com.example   # find the package
adb shell pm path com.example.app               # locate the installed APK
adb pull /data/app/.../base.apk ~/Downloads/target.apk
```

Any APK works. The walkthrough below uses `~/Downloads/target.apk` as the file path; substitute your own.

## Installation

MedusaNexus runs on macOS and Linux. The installer is a single shell script with several flags; the `--minimal` flag skips Ghidra (the heaviest dependency) and gets you scanning fastest.

```bash
git clone https://github.com/jacksonfdam/medusa-nexus.git
cd medusa-nexus
./scripts/setup.sh --minimal
source ~/.mnexus/env.sh
```

What this does, in order: creates a Python virtualenv under `.venv/`, installs the `mnexus` package in editable mode with dev extras, downloads `adb` / `jadx` / `apktool` (via Homebrew on macOS, apt-get on Linux), clones `ch0pin/medusa` and `ch0pin/Stheno` into `~/.mnexus/tools/`, and writes `~/.mnexus/env.sh` with every `MNEXUS_*` environment variable the package expects.

Verify with the doctor:

```bash
mnexus doctor
```

The output lists every registered engine and whether it's reachable. With `--minimal`, you should see `adb`, `jadx`, `apktool`, `frida`, `playintel` all marked `OK` — and `ghidra`, `mobsf`, `burp`, `vphone` marked `MISS`. The `MISS` rows aren't failures; the pipeline routes around missing engines.

If anything is unexpectedly `MISS`, run `mnexus doctor --env` to see which `MNEXUS_*` variables the running process actually picked up. The most common cause of an unexplained miss is that you sourced `env.sh` in a different shell than the one running `mnexus`.

## The first scan

With the toolchain ready, drop an APK on disk and run:

```bash
mnexus scan ~/Downloads/target.apk
```

The CLI does five things, in order:

1. **Manifest extraction.** `apktool` reads `AndroidManifest.xml` — the package name, version code, version name, all `<uses-permission>` entries, every `<intent-filter>`. Even if you didn't pass `--package` or `--version`, the scan auto-detects them here.
2. **Static fan-out.** Every static engine that's registered and healthy runs in parallel against the APK. `jadx` decompiles the DEX into Java source. The secrets scanner walks resource strings and decompiled output for hard-coded credentials. The deeplink extractor enumerates every URI that shows up in the code. The permissions analyser cross-references declared permissions against what the code actually invokes.
3. **Attack surface build.** The intelligence layer aggregates the engine outputs into a single `AttackSurface` model: exported components, deeplinks, native libraries, API endpoints, crypto operations, pinning libraries, root-detection libraries, jailbreak-detection libraries (for cross-platform projects).
4. **Correlation.** The correlator pairs findings that overlap — when two engines report the same hard-coded key, they get deduplicated. The chain correlator pattern-matches against known attack chains; when the pieces of a 1-click ATO chain (article 5) are individually present, a single `CRITICAL` chain finding is emitted referencing every link.
5. **Hook generation.** The auto-hook generator emits Frida scripts for the findings that would benefit from dynamic confirmation. They land under `~/.mnexus/workspace/<project_id>/hooks/`, ready to load.

The output is a Rich-formatted panel:

```
🔱 ✓ ingest complete
PRJ-355151DF  ·  com.target.app

risk      67.5/100
findings  42  (3c 12h 18m 9l)
surface   24 components · 8 deeplinks · 3 native libs
hooks     7 auto-generated

Active project set. Try /findings or /report.
```

That's a project. `PRJ-355151DF` is a content-addressable id derived from the SHA-256 of the APK bytes — the same APK always gets the same id, which is useful for diffing later. Every scan creates one project.

## Reading the findings panel

The fastest way to walk the findings is the REPL. Type:

```bash
mnexus
```

The REPL is an interactive shell — Click-based CLI flow, Rich-rendered tables, prompt_toolkit autocomplete, history persisted to `~/.mnexus/history`. The project you just scanned is already active.

The first command to run is `/findings`. Without arguments, it lists every finding the scan produced, sorted by severity:

```
🔱 nexus PRJ-355151DF ❯ /findings
┌──────────────┬──────────┬────────┬──────────────────────────────────────────┬────────────────┐
│ id           │ sev      │ engine │ title                                     │ location       │
├──────────────┼──────────┼────────┼──────────────────────────────────────────┼────────────────┤
│ FND-7B22A91C │ CRITICAL │ jadx   │ Static (zero) IV with AES                │ classes.dex    │
│ FND-A8E1F02C │ HIGH     │ jadx   │ Permissive deeplink router (40 hosts)    │ MainActivity   │
│ FND-3C9D4B11 │ HIGH     │ scanner│ Hard-coded AWS access key                │ res/raw/cfg    │
│ FND-D17E0066 │ MEDIUM   │ jadx   │ Cleartext HTTP in BuildConfig           │ BuildConfig    │
│ …            │ …        │ …      │ …                                        │ …              │
└──────────────┴──────────┴────────┴──────────────────────────────────────────┴────────────────┘
```

Filter by severity:

```
🔱 nexus PRJ-355151DF ❯ /findings critical
```

Each finding has a deterministic id (`FND-…`) and a backing engine. The CLI shows a compact summary; the full finding — description, evidence, remediation, CWE reference, MASVS control — lives behind the API.

The REPL's `/help` lists every command. The ones you'll use most in this article:

- `/findings [sev]` — list findings, optionally filtered by severity.
- `/projects` — list every project in the database.
- `/use <id>` — switch the active project.
- `/rescan` — re-run the pipeline on the active project in place.
- `/report [format]` — generate a report (`md`/`json`/`html`/`pdf`/`png`).
- `/serve` — start the FastAPI backend in the background.
- `/open` — open the web UI in the browser.

The slash-command catalogue is generated from the source at build time and lives in [`docs-site/content/reference/repl.mdx`](../docs-site/content/reference/repl.mdx) of the docs site; the version printed by `/help` is always current.

## The web UI tour

For exploring findings interactively, the web UI is the better surface. Start it:

```
🔱 nexus PRJ-355151DF ❯ /serve
✓ server ready
web ui   http://127.0.0.1:8765/
swagger  http://127.0.0.1:8765/docs

🔱 nexus PRJ-355151DF ❯ /open
→ opening http://127.0.0.1:8765/
```

`/serve` boots a FastAPI server on port 8765 in the background; `/open` launches your default browser at the dashboard. The SPA is single-page, vanilla JavaScript (no framework dependency), and serves the same data the REPL serves — every endpoint is reachable directly via `curl` if you prefer the terminal.

The project view has sixteen tabs, each backed by one endpoint. The ones to walk on a first scan:

* **Findings.** The same table the REPL showed, with severity filters and full descriptions inline.
* **Secrets.** Confirmed vs suspected credentials, grouped by detector. Distinct from generic findings because the false-positive rate is high enough to warrant manual triage.
* **Components.** Every exported `Activity` / `Service` / `Receiver` / `Provider`, with the intent-filters they declare. Click an activity to see what its declared intent-filter actually allows.
* **Native.** Per-`.so` file: architecture (`armeabi-v7a` / `arm64-v8a` / `x86` / `x86_64`), JNI exports, hard-coded URLs detected in the strings table, crypto routines identified by signature.
* **API map.** Every hostname and path the static surface extracted from the code. When a traffic-capture proxy (Burp / Caido / Moxy) is attached, each row gains a live `hits` counter for the last N seconds.
* **OWASP.** A populated MASVS matrix — every finding mapped to its MASVS control, every control with at least one violation highlighted.
* **Attack tree.** A graph view of attacker entry points to assets. The static surface is the input; the layout is the chain correlator's output. Where article 5's chain shows up visually.
* **Hooks.** The auto-generated Frida scripts, one per finding that would benefit from dynamic confirmation. Each one is loadable into a Frida session with a single click.
* **Surface.** A raw dump of the `AttackSurface` model. Useful when you want to script against the data directly.

The HTTP API behind each tab is documented at `http://127.0.0.1:8765/docs` (Swagger UI). For automation, the same data is at `GET /v1/projects/{id}/findings`, `GET /v1/projects/{id}/components`, etc.

## Generating a report

Reports are the artefact you hand to someone else — a PR reviewer, a client, an auditor, your future self. MedusaNexus ships five formats:

```
🔱 nexus PRJ-355151DF ❯ /report markdown
✓ report: ~/.mnexus/workspace/reports/PRJ-355151DF.md
```

* `markdown` — pastes into a PR description, Notion, Jira, Linear.
* `json` — feeds into your own pipeline.
* `html` — self-contained HTML you can email, host, or attach.
* `pdf` — client deliverable (requires WeasyPrint).
* `png` — one-image executive summary (requires Chromium).

Every report carries a **Mitigation Playbook** section at the end — every finding's `remediation` field, grouped by category (Cryptography, Network, Auth, IPC, WebView, …) and sorted by severity. The Playbook is the difference between *"this app has problems"* and *"here is the PR that fixes them."*

There are four templates, switchable via the HTTP layer:

```bash
curl -X POST "http://127.0.0.1:8765/v1/projects/PRJ-355151DF/report" \
  -d "template=executive&fmt=html" -o report.html
```

`executive` is a one-page summary for non-technical readers. `technical` is the detailed engineering report. `owasp-matrix` is the MASVS coverage view. `diff` is the delta against a prior scan — useful after the first remediation pass.

## Re-scanning and diffing

When you change a finding's status — for instance, by editing a rule or applying a fix to the source — re-run the scan in place:

```
🔱 nexus PRJ-355151DF ❯ /rescan
```

`rescan` re-runs the pipeline against the same APK, replacing the project's findings with the fresh output. The project id and SQLite row stay the same. Use this when:

* You edited a rule under `rules/` and want to confirm the change.
* You upgraded an engine and want to validate.
* You want to drop a finding that was a false positive after manual review.

To compare two builds of the same app — say, before and after a developer's fix PR — re-scan the new APK as a new project and ask for the diff:

```
🔱 nexus ❯ /scan ~/Downloads/target-1.1.apk
🔱 nexus PRJ-A88B12C4 ❯ /diff findings
```

The diff auto-picks the most recent prior scan of the same package as the baseline. The output is structured: which findings are *new*, which are *resolved* (present in the baseline, gone in head), and which *regressed* (severity climbed). The same logic backs the `diff` report template, and — when combined with the `--fail-on` flag on `mnexus scan` (article 6) — becomes the foundation of CI/CD integration.

## What just happened

The scan you ran touched every layer of the platform:

* The **engine layer** (`mnexus/engines/`) provided the adapters to `jadx`, `apktool`, the secrets detector, the deeplink extractor, and so on.
* The **orchestrator** (`mnexus/core/orchestrator.py`) ran them in parallel and aggregated their findings.
* The **intelligence layer** (`mnexus/intelligence/`) built the attack surface from the raw findings and ran the correlator on top.
* The **model layer** (`mnexus/models/`) enforced the invariants — every finding has evidence, every `CRITICAL` or `HIGH` finding has a remediation.
* The **artifact store** (`mnexus/core/artifact_store.py`) persisted the project, the surface, the findings, and the generated hooks to one SQLite file.
* The **API layer** (`mnexus/api/`) exposed the result via 136+ endpoints, drove by both the REPL and the web UI you just walked.

Every piece of that is open source; the entire pipeline runs locally. No network traffic is required for static analysis; no cloud service is involved. Your APK never leaves your laptop.

## Common first-scan pitfalls

A few things that trip first-time users and what they mean:

* **`apktool` errors with *"Could not decode arsc file"*.** Modern AAPT2-compacted resources occasionally trip apktool's parser. The orchestrator falls back to filename heuristics — the scan proceeds with reduced resource visibility but still produces findings. Upgrade `apktool` if it persists.
* **`jadx` runs forever.** Heavy ProGuard'd or R8'd APKs can take minutes. The other engines fan-out alongside; you'll see partial findings as they complete. If it stays stuck >5 minutes, kill the scan and re-run with the [`--no-jadx`](https://github.com/jacksonfdam/medusa-nexus) flag (planned for a future release).
* **Zero secrets found.** The secrets detector defaults to conservative patterns to keep the false-positive rate down. Custom token formats (organisation-specific bearer prefixes, internal API key shapes) need tuning. The patterns live in `mnexus/playintel/secret_detector.py`.
* **Native tab empty.** No `lib/*/` directory in the APK, or the `.so` files are packed by a runtime protector. Ghidra (if installed) still tries; check the engine log in the workspace.
* **Risk score feels wrong.** The score is a deterministic weighted sum of finding severities. The weights live at `mnexus/intelligence/risk_score.py` and are intentionally tuneable. If your team has a different risk model, fork and adjust.

## TL;DR

Install with `./scripts/setup.sh --minimal`, source `env.sh`, run `mnexus doctor` to verify, run `mnexus scan ./your.apk` to ingest, drop into the REPL with `mnexus`, walk the findings with `/findings`, open the web UI with `/serve` + `/open`, generate a deliverable with `/report html`. Every step is paste-and-run. Total wall-clock time on a typical APK: under ten minutes.

Once the scan is sitting in front of you, the rest of this series will make more sense. Article 4 explains *why* the orchestrator combines five different tools instead of relying on any one. Article 5 walks through a specific attack chain the scanner finds. Article 6 wires the same scan into a CI/CD pipeline so it runs on every commit. Article 7 hands the analysis off to an AI assistant via MCP.

> The first scan is the cheapest experiment in mobile security you'll ever run. It costs nothing, leaks nothing, and surfaces more about your app's risk posture in ten minutes than most code reviews catch in a week. The harder question is what to do with the result — which is what the rest of the series is about.

---

**Next in the series →** *Five tools, one truth — how MedusaNexus orchestrates static analysis.* What `jadx`, `apktool`, `Ghidra`, `MobSF`, and `PlayIntel` each do, why every one is individually incomplete, and how the orchestrator produces findings none of them could alone.

---

*The series continues weekly on [Medium](https://medium.com/@jacksonfdam/). For deep dives on Android emulator-based labs — `AVD Deep Dive`, `Cuttlefish` — see the Codex at [Umain Fortress](https://umain-fortress.vercel.app/).*
