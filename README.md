# 🔱 MEDUSA NEXUS

*Unified Mobile Threat Analysis Platform.*
*Every head sees a different angle.*

`mnexus` is the orchestrator your APK never asked for. It doesn't reinvent JADX, Ghidra, MobSF, Frida, Medusa, Stheno, Burp or APKTool — it makes them stop pretending they don't know each other, sits them down at one SQLite-backed table, and watches them correlate findings like adults.

## What it does

1. **You drop an APK** (or pull one off a device with one click).
2. **Static engines run in parallel** — JADX decompiles, MobSF lectures, Ghidra dissects the `.so` files, a secrets scanner finds the API key that's been hardcoded since 2019.
3. **The attack surface gets built** — exported components, deep links, crypto primitives, pinning libs, root-detection libs, the works.
4. **Frida hooks get auto-generated** based on what static analysis actually found. No more copy-pasting `universal-ssl-pinning-bypass.js` from Stack Overflow.
5. **You run the dynamic session**. Traffic routes through Burp, Medusa recipes load, Stheno patches the APK if needed, every crypto call and intent gets logged.
6. **Correlation layer confirms findings** — static suspicion + dynamic evidence = a finding with a confidence level your client will take seriously.
7. **Reports ship with mitigation.** Not "improve security posture". Actual before/after code.

## Status

**Alpha — full end-to-end Android pipeline + iOS toolkit + live dynamic loop.**

## Docs

📚 **Full documentation lives at [mnexus.vercel.app](https://mnexus.vercel.app)**.

| Read | When |
| ---- | ---- |
| [Getting started](docs-site/content/getting-started/index.mdx) — install, requirements, env vars, first scan, 60-second tour | First-day setup. |
| [Workflows](docs-site/content/workflows/index.mdx) — Android static, iOS, dynamic Frida, Memory Inspector, PlayIntel, diff, **chain detection**, pipelines, **CI/CD**, reporting | "I want to do X" — analyst stories. |
| [Integrations](docs-site/content/integrations/index.mdx) — Burp, Caido, Moxy, super-tart-vphone, MCP | Per-tool wiring + auth + pitfalls. |
| [Reference](docs-site/content/reference/index.mdx) — architecture, env vars, CLI, REPL, HTTP API (136+ endpoints) | The matrix when you need a flag or a route. |

All markdown lives in [`docs-site/content/`](docs-site/content/) so an AI assistant reading the repo sees byte-identical content as this site.
The CLI / REPL / API reference pages are *generated from the Python source at build time* — they cannot drift.

### CI/CD in one block

`mnexus scan` ships CI-shaped flags — `--json` for machine output and `--fail-on critical|high|medium|low|info` for the severity gate. Pair `--against PRJ-PREV` to count only *new* findings vs a baseline (PR-style check):

```bash
mnexus scan ./app-release.apk --json --fail-on high --against $BASELINE_PID > scan.json
# Exit 0 → safe to merge.  Exit 1 → a new HIGH+ finding landed; review the PR.
```

Full walkthrough — GitHub Actions YAML, exit-code matrix, what NOT to put in CI — in [`docs-site/content/workflows/ci-cd.mdx`](docs-site/content/workflows/ci-cd.mdx).

### Chain detection in one block

Most mobile bugs are MEDIUM in isolation, CRITICAL in combination. The chain correlator promotes a set of independently-MEDIUM findings into one CRITICAL chain finding with a per-link mitigation playbook. Catalogued today: the **1-click account takeover via deeplink → WebView → intent-redirect chain** — four contributing detectors (`deeplink_audit` × `webview_audit`) feed `chain_correlator` automatically on every static scan.

```bash
mnexus scan ./target.apk --json | jq '.findings_by_severity'
# If "critical" >= 1 and the chain matched, drill into it:
PID=$(mnexus projects --json | jq -r '.[0].id')
mnexus findings --project $PID --severity critical --json \
  | jq '.[] | select(.source_engine == "chain_correlator")'
```

Walkthrough — every link, every detector, how to add a new chain shape — in [`docs-site/content/workflows/chain-detection.mdx`](docs-site/content/workflows/chain-detection.mdx).

### MCP — drive a full inspection from your AI assistant

`mnexus mcp-serve` now ships **read + write** tools. The write set (`scan_apk`, `run_pipeline`, `analyze_native_lib`) lets Claude Desktop / Cursor / Zed run a full APK ingest → pipeline → finding walkthrough from a single prompt. Wire-up + tool reference + agentic loop example in [`docs-site/content/integrations/mcp.mdx`](docs-site/content/integrations/mcp.mdx).

## Requirements

- **Python** 3.11+ (3.12 recommended).
- **Git**, **curl**, **unzip** on PATH.
- **macOS**: [Homebrew](https://brew.sh).
- **Debian / Ubuntu**: `apt-get` available (the script uses `sudo apt-get` for `adb` / `apktool`).
- **Docker** (optional, for MobSF).
- **Burp Suite** Professional (optional; closed-source, install manually).
- An **Android device or emulator** with USB debugging, plus `frida-server` or a Stheno-patched APK (the script can push `frida-server` for you).

## Quick start

The shortest path:

```bash
git clone https://github.com/jacksonfdam/medusa-nexus.git
cd medusa-nexus
./scripts/dev.sh             # bootstrap → doctor → server (auto-reload + browser open)
```

`dev.sh` ensures the venv exists, installs the package in editable mode, runs `mnexus doctor`, starts uvicorn with `--reload`, and watches `/v1/health` so every reload prints a `✓` or `✕`. If you'd rather see the full installer with
brews / apts / Ghidra / MobSF docker / Stheno / frida-server staging:

```bash
./scripts/setup.sh           # full install
./scripts/setup.sh --minimal # skip Ghidra (~400 MB), MobSF docker, frida-server push
```

For the 60-second tour with screenshots and slash-command reference, see
[`docs-site/content/getting-started/quickstart.mdx`](docs-site/content/getting-started/quickstart.mdx).

What the script does:

1. Detects platform (macOS / Linux, arm64 / x86_64).
2. Creates `.venv/` and installs `mnexus` in editable mode with dev extras.
3. Installs `adb`, `jadx`, `apktool` via `brew` (macOS) or `apt-get` + GitHub releases (Linux).
4. Clones `ch0pin/medusa` and `ch0pin/Stheno` into `~/.mnexus/tools/`.
5. *(full mode)* Downloads Ghidra (v11.1.2 by default, override with `GHIDRA_VERSION=`).
6. *(full mode)* Pulls the MobSF docker image.
7. *(full mode)* Stages `frida-server` for the connected device's ABI at `/data/local/tmp/frida-server`.
8. Writes `~/.mnexus/env.sh` with every `MNEXUS_*` path + URL the Python package expects.

Idempotent — safe to re-run. `NO_COLOR=1 ./scripts/setup.sh` kills ANSI output for CI logs.

### Setup flags

| Flag | Effect |
|---|---|
| *(none)* | full install |
| `--minimal` | skip Ghidra, MobSF docker, frida-server push |
| `--device` | only push frida-server to the currently connected device |
| `--mobsf` | start MobSF in Docker with a pinned API key + write it to `~/.mnexus/env.sh` |
| `--burp` | verify Burp Pro REST API + write `MNEXUS_BURP_URL` / `_API_KEY` to env |
| `--burp-rest-api` | install `vmware-archive/burp-rest-api` (jar + `run.sh` wrapper) |
| `--moxy` | start [Moxy](https://github.com/matank001/Moxy) in Docker, extract the mitmproxy CA, push it to the connected device via `adb`, write `MNEXUS_MOXY_*` to env. Details in [`docs-site/content/integrations/moxy.mdx`](docs-site/content/integrations/moxy.mdx). |
| `--ios-tools` | install **bagbak + ldid + frida-ios-dump + libimobiledevice + pymobiledevice3** in one shot (the last two power the read-only iOS screen mirror). Idempotent; reports per-tool success at the end. Details in [`docs-site/content/workflows/ios.mdx`](docs-site/content/workflows/ios.mdx). |
| `--doctor` | only run `mnexus doctor` |
| `--help` | print usage |

### iOS lab via super-tart-vphone (research-only, opt-in)

The `vphone` engine wraps [`wh1te4ever/super-tart-vphone`](https://github.com/wh1te4ever/super-tart-vphone) — a fork of Tart that boots **real iOS** in a VM on Apple Silicon. With it, every iOS Frida recipe in the library runs against a local VM (`frida -H 127.0.0.1:27042`) instead of needing a physical jailbroken iPhone.

**Research-only.** Requires Apple Silicon, macOS Sequoia 15.7.4+ / Tahoe 26.3+, and SIP + AMFI disabled (`csrutil disable && csrutil allow-research-guests enable`). The full integration plan, the four-wave breakdown, and the explicit yes/no automation matrix live in [`docs-site/content/integrations/vphone.mdx`](docs-site/content/integrations/vphone.mdx).

```bash
./scripts/setup-vphone.sh           # checks prereqs + clones + builds + writes MNEXUS_TART_BIN
./scripts/setup-vphone.sh --check   # status report only — never modifies the host

source ~/.mnexus/env.sh
mnexus doctor                        # vphone row appears with `research mode · N VMs`
mnexus vphone list                   # short status table
mnexus vphone start ios-test         # tart run in the background
mnexus vphone ssh ios-test -- uname -a
mnexus vphone install ios-test ~/Downloads/target.ipa
```

The first-boot path (firmware extraction, bootrom + iBSS + iBEC + LLB + TXM + kernelcache patching, `idevicerestore`, Cryptex injection over SSH ramdisk) is **manual** — the upstream [`GUIDE.md`](https://github.com/wh1te4ever/super-tart-vphone/blob/main/GUIDE.md) walks you through it. We don't automate that path because it depends on hand-tuned offsets per cloudOS build and we never redistribute Apple firmware.

### Starting MobSF (and getting past the `MISSING` doctor row)

```bash
# spin up the container with a deterministic API key,
# and have the script write MNEXUS_MOBSF_API_KEY into the env file for you.
./scripts/setup.sh --mobsf

# re-source the env in the current shell, then verify
source ~/.mnexus/env.sh
mnexus doctor
```

You can pin your own key via `MOBSF_API_KEY=<your-key> ./scripts/setup.sh --mobsf` — useful for CI and team setups.

### Wiring up Burp Suite Pro (for the `burp` engine)

Burp Suite is closed-source and runs as a JAR — the installer can't autostart it. But it can validate the REST API and drop the right env vars into `~/.mnexus/env.sh`:

1. Open **Burp Suite Professional** → **Settings** → **Suite** → **API**.
2. Toggle **Enable API**. Note the **Service URL** (defaults to `http://127.0.0.1:1337/`) and the **API key** Burp shows.
3. Run one of:

   ```bash
   # interactive (script will prompt for URL + key)
   ./scripts/setup.sh --burp

   # non-interactive (CI-friendly)
   BURP_URL=http://127.0.0.1:1337 BURP_API_KEY=<paste-key> ./scripts/setup.sh --burp
   ```

   The script probes `GET <url>/<key>/v0.1/` and reports 200 / 401 / 404 / connection errors with a specific message before writing `MNEXUS_BURP_URL` + `MNEXUS_BURP_API_KEY` to the env file.

4. `source ~/.mnexus/env.sh && mnexus doctor` — the `burp` row should flip to `OK`.

**Note on Burp Community edition:** it does *not* ship the REST API. Use the legacy `burp-rest-api` extension below instead — the installer supports it.

### Alternative: install `vmware-archive/burp-rest-api` (for Community edition)

Adds a REST surface (`/burp/versions`, `/burp/proxy/history`, `/burp/scanner/…`) on top of any Burp Suite jar — Community or Pro.

```bash
# Make sure Burp Suite is installed first (any edition).
# macOS: brew install --cask burp-suite

./scripts/setup.sh --burp-rest-api
```

What the script does:

1. Checks for a JRE (11+ / 21 for the latest release).
2. Downloads the latest `burp-rest-api-*.jar` from GitHub releases into `~/.mnexus/tools/burp-rest-api/`.
3. Tries to locate `burpsuite_community.jar` / `burpsuite_pro.jar` via a candidate list (also accepts `BURP_SUITE_JAR=<abs path>`). On macOS, if no Burp is found and the run is interactive, offers to `brew install --cask burp-suite` inline.
4. Writes a wrapper `run.sh` that **re-runs the detection at launch time**, so you can set up now and install Burp later without re-running the script. Launches everything headless on port **8090**, no auth.
5. Sets `MNEXUS_BURP_URL=http://localhost:8090` and `MNEXUS_BURP_API_KEY=none` in `~/.mnexus/env.sh` — the Python `BurpEngine` recognizes the `none` sentinel and probes `/burp/versions` instead of the Pro API's `/<key>/v0.1/` path.

Launching:

```bash
# Auto-detected burp jar:
~/.mnexus/tools/burp-rest-api/run.sh

# Or override:
BURP_SUITE_JAR=/path/to/burpsuite.jar PORT=8090 ~/.mnexus/tools/burp-rest-api/run.sh

# Verify:
source ~/.mnexus/env.sh && mnexus doctor
```

**Caveats**

- `vmware-archive/burp-rest-api` is unmaintained (archived). It tracks Burp Suite internal APIs that drift between releases; real-world sweet spot is Burp **2020.x – 2023.x**. Newer builds may break.
- Runs without authentication by default. Don't expose port 8090 beyond `localhost`.
- Uses ~2 GB of heap. The wrapper sets `-Xmx2g`; override with `JAVA_OPTS`.

### Capturing mobile traffic with Moxy (no Burp / Caido license needed)

[Moxy](https://github.com/matank001/Moxy) is an open-source MITM proxy + web UI built on mitmproxy. Same role as Burp for HTTP/HTTPS interception, but free, scriptable from a browser, and docker-friendly. The installer wires it
up end-to-end:

```bash
./scripts/setup.sh --moxy
```

What that does:

1. Pulls + runs `ghcr.io/matank001/moxy:latest` with `projects_data` mounted
   under `~/.mnexus/tools/moxy/` so state lives outside the repo.
2. Polls the UI on `http://localhost:5000` until it answers.
3. `docker cp`s the mitmproxy CA out of the container into
   `~/.mnexus/tools/moxy/moxy-ca.cer`.
4. Detects the host's LAN IP — that's the address the device has to point
   at, not `localhost`.
5. If a single `adb` device is attached, copies the CA to
   `/sdcard/Download/moxy-ca.cer` so you can install it from
   **Settings → Security → Install a certificate** in three taps.
6. Writes `MNEXUS_MOXY_URL` / `_PROXY_HOST` / `_PROXY_PORT` / `_CA_PATH` to
   `~/.mnexus/env.sh`.
7. Prints device-side instructions with the resolved IP/port substituted.

Custom ports (5000/8081 are commonly occupied — AirPlay Receiver squats on
5000 under macOS Sonoma+):

```bash
MOXY_UI_PORT=5001 MOXY_PROXY_PORT=8082 ./scripts/setup.sh --moxy
```

After:

```bash
source ~/.mnexus/env.sh
mnexus doctor                    # moxy row should flip to OK
```

Device-side setup, common pitfalls (Network Security Config, certificate pinning, the intercept-mode "No response available" trap), and the diagnosis
tree are all in [`docs-site/content/integrations/moxy.mdx`](docs-site/content/integrations/moxy.mdx).

### iOS workflow (decrypt → patch → memory-swap)

If you're testing an iOS app off the App Store you need a different toolchain than Android. MedusaNexus wraps the established ecosystem:

```bash
# One flag, idempotent:
./scripts/setup.sh --ios-tools
# Installs:
#   bagbak              — npm install -g (preferred IPA decryptor)
#   ldid                — brew on macOS / apt on Linux (preferred signer)
#   frida-ios-dump      — git clone under ~/.mnexus/tools/ + pip install requirements
#   libimobiledevice    — idevicescreenshot fallback + device info
#   pymobiledevice3     — pip into venv (read-only screen mirror, iOS 17+ friendly)

# Manual install if you'd rather skip the script:
npm install -g bagbak
brew install ldid libimobiledevice
pip install pymobiledevice3
git clone https://github.com/AloneMonkey/frida-ios-dump ~/.mnexus/tools/frida-ios-dump
(cd ~/.mnexus/tools/frida-ios-dump && pip install -r requirements.txt)
```

You can also just **watch the screen** without any of that: plug in the
iPhone, open `/#/devices`, click it, and the panel renders a read-only
mirror (screenshot poll over lockdownd — no jailbreak, no decryption).
Live control stays Android-only. On iOS 17+ the developer tunnel the
mirror needs is started for you on server launch; if sudo creds aren't
cached, run `mnexus ios-tunnel` once. Opt out with `MNEXUS_IOS_TUNNEL=0`.

Then drive the full workflow from the REPL:

```
mnexus> /decrypt-ios com.target.bank.test
mnexus> /patch ipa return_zero_at_offset:0x100123456
mnexus> /dynamic start --recipes ios_ssl_kill_switch
mnexus> /memory scan "65 79 4a 68" --module Bank      # find JWT in memory
mnexus> /memory write 0x10f234000 "..."               # token swap
```

Endpoints, failure modes, and the full talk-style walkthrough live
in [`docs-site/content/workflows/ios.mdx`](docs-site/content/workflows/ios.mdx).

### Live dynamic loop + Memory Inspector

The Dynamic tab attaches a real Frida session to the project's
package, stacks N hooks + Medusa recipes in one session (each
IIFE-isolated), streams `send({...})` events back via SSE, and
exposes process memory through four endpoints
(`/v1/dynamic/sessions/{sid}/memory/{scan,read,write,modules}`).
Workflow walkthrough — including the **token-swap recipe** — in
[`docs-site/content/workflows/dynamic.mdx`](docs-site/content/workflows/dynamic.mdx).

## Running

```bash
# 1. activate the venv
source .venv/bin/activate

# 2. load tool paths + URLs
source ~/.mnexus/env.sh

# 3. verify every engine
mnexus doctor
```

`mnexus doctor` prints a table of engines with `OK` / `MISSING` + version + path. Any `MISSING` row is actionable — the `note` column tells you what to do.

### Interactive REPL

Run `mnexus` with no arguments and you get a Claude/Gemini-style terminal app:
banner, slash commands, autocomplete, history, project context shown in the
prompt.

```bash
$ mnexus
🔱 nexus ❯ /scan ~/Downloads/target.apk
🔱 nexus PRJ-A1B2C3D4 ❯ /findings critical
🔱 nexus PRJ-A1B2C3D4 ❯ /report markdown
🔱 nexus PRJ-A1B2C3D4 ❯ /serve
🔱 nexus PRJ-A1B2C3D4 ❯ /open
```

Slash commands (prefix-matched, so `/doc` resolves to `/doctor`):

| command            | description                                                           |
|--------------------|-----------------------------------------------------------------------|
| `/help`            | Show every command in a table.                                        |
| `/doctor`          | Run engine health checks with a live spinner.                         |
| `/scan <apk>`      | Static scan — auto-detects package + version.                         |
| `/projects`        | List stored projects with risk scores.                                |
| `/use <id>`        | Set the active project for subsequent commands.                       |
| `/findings [sev]`  | List findings, optionally filtered by severity.                       |
| `/rescan`          | Re-run the static fan-out on the active project.                      |
| `/report [fmt]`    | Generate a report (`markdown`/`json`/`html`/`pdf`).                   |
| `/serve [port]`    | Start the FastAPI server in the background.                           |
| `/stop` `/open` `/url` | Background server control.                                        |
| `/devices`, `/adb` | Quick `adb devices -l` + one-shot `adb` commands.                    |
| `/dynamic <verb>`  | Frida session control: `start` · `stop` · `status` · `stream`.        |
| `/memory <verb>`   | Live memory ops on the active session: `modules` · `scan` · `read` · `write`. |
| `/patch apk\|ipa`  | Byte-patch the project's APK or IPA + re-sign (apktool / ldid / codesign). |
| `/decrypt-ios <id>`| Decrypt App Store IPA via bagbak / frida-ios-dump + auto-ingest.      |
| `/diff manifest\|findings` | Diff the active project against the latest prior scan.        |
| `/pipeline list\|run` | List built-in pipelines or execute one.                            |
| `/recipes [filter]`| Browse `/v1/recipes` (built-ins + Medusa modules).                    |
| `/export <fmt>`    | Write Postman / Caido / Burp / Moxy / deeplinks export to disk.       |
| `/play-scan <pkg>` | Stream + scan an APK from Google Play (PlayIntel).                    |
| `/play-account <verb>` | Manage stored Play identities.                                    |
| `/vphone <verb>`   | super-tart-vphone iOS lab control.                                    |
| `/clear`, `/exit`  | UI plumbing.                                                          |

### One-shot CLI (for scripts and CI)

Every slash command has a flat equivalent:

```bash
# Engine health check — exits non-zero if anything's missing
mnexus doctor

# Static scan an APK — auto-detects package + version
mnexus scan ./target.apk
mnexus scan ./target.apk --package com.target.app --version 4.12.0

# Generate a report — every template ships a Mitigation Playbook
mnexus report --project PRJ-ABCD1234 \
              --template technical --format markdown \
              --output ./report.md

# Production-style serve (no reload)
mnexus serve --host 127.0.0.1 --port 8765

# Dev-style serve — boots faster than dev.sh; for an already-set-up venv
mnexus dev --port 8765
```

### Web UI

`mnexus serve` (or `./scripts/dev.sh`) mounts a single-page app at `/` plus
a JSON API that the SPA + external tooling can both consume. Highlights:

- **Dashboard / Projects / Scan** — drag-and-drop APK upload, recent imports,
  live engine status, project cards with risk scores.
- **Per-project tabs** — OVERVIEW / STATIC / DYNAMIC / NETWORK / REPORT, each
  populated from real APK data after a scan. `⟳ RESCAN` and `↻ REFRESH`
  buttons in the tab bar trigger pipeline re-runs and view re-fetches.
- **Visualizers** — attack-surface graph, data-flow swimlanes, attack tree,
  OWASP MASVS matrix, SSL pinning map, API endpoint tree.
- **ADB Control Panel** at `#/adb` — ADBugger-style command surface with a
  device dropdown, project package binding, and a sticky right-pane
  "Command Log" that records every adb call with its full command and output.
- **Device tools** at `#/device/{bridge,shell,files,screen,logcat,pull}` —
  device info, interactive shell, file manager (push/pull/delete), screencap,
  logcat tail with filter.
- **Recipes / Tools / Settings / Terminal** — the Pencil deck's full 31-screen
  surface, all wired.
- **Collapsible sidebar** — `[☰]` toggle in the topbar (or `⌘B` / `Ctrl-B`),
  state persists across reloads. Phones get a slide-in drawer with backdrop.

Key API endpoints (full list at `/docs`):

| endpoint                                          | purpose                                      |
|---------------------------------------------------|----------------------------------------------|
| `GET  /v1/health`                                 | Liveness probe.                              |
| `GET  /v1/doctor`                                 | Engine health (same as `mnexus doctor`).     |
| `GET  /v1/projects`                               | List stored projects.                        |
| `GET  /v1/projects/{id}`                          | Full project JSON.                           |
| `POST /v1/projects/{id}/rescan`                   | Re-run the static fan-out in place.          |
| `GET  /v1/projects/{id}/{secrets,components,native,api-map,ssl-map,owasp,attack-tree,dataflow,surface}` | Per-screen views over the attack surface. |
| `GET  /v1/projects/{id}/hooks`                    | Auto-generated Frida hooks.                  |
| `POST /v1/apks/upload`                            | Upload an APK and ingest it.                 |
| `POST /v1/projects/{id}/report`                   | Generate a report (PDF/HTML/MD/JSON).        |
| `GET  /v1/devices`                                | `adb devices -l` parsed.                     |
| `POST /v1/devices/{serial}/{shell,install,uninstall,clear,start,stop,monkey,reboot,...}` | Per-device commands. |
| `GET  /v1/adb/log`                                | Audit trail of every adb call.               |

### Device setup after first run

```bash
# Once a device is plugged in and USB debugging is authorized:
./scripts/setup.sh --device      # pushes frida-server to /data/local/tmp

# On a rooted device:
adb shell su -c '/data/local/tmp/frida-server &'

# On a non-rooted device, patch the APK instead of running frida-server:
# (handled by the Stheno engine; see workflows/dynamic for the wiring)
```

## Development

The fastest loop:

```bash
./scripts/dev.sh                         # one-shot bootstrap + reload server
./scripts/dev.sh --check                 # bootstrap + doctor only (no server)
./scripts/dev.sh --port 9090 --no-browser
```

`dev.sh` is idempotent — re-running it just re-verifies + restarts. The
inner uvicorn watches `mnexus/`, so editing any `.py` triggers a sub-second
reload. A background watchdog polls `/v1/health` and prints `✓` / `✕` on
each state change.

Manual flow if you'd rather not use the script:

```bash
source .venv/bin/activate

# run the full test suite (35+ tests across API, models, engines, reporting)
pytest

# lint + type-check (dev extras install these)
ruff check .
mypy mnexus

# launch the CLI in editable mode without reinstalling
python -m mnexus.cli                # interactive REPL
python -m mnexus.cli doctor          # one-shot
python -m mnexus.cli dev             # serve with reload
```

## Structure

| Path | What lives here |
|---|---|
| `mnexus/` | Python package — models, engines, orchestrator, intelligence, reporting, CLI, API. |
| `tests/` | Pytest suite — mitigation invariant + report generator coverage. |
| `scripts/setup.sh` | One-shot installer (macOS + Linux). |
| `docs-site/` | Vercel-deployed documentation site (Nextra 4 + MDX). |
| `design/medusanexus.pen` | Pencil source file (31 screens + design system). |
| `design/screens/` | Per-screen PNG exports, grouped. |
| `design/INDEX.md` | Screen catalog with fidelity levels. |
| `CREDITS.md` | Author + upstream tool acknowledgements. |

## Author

**Jackson Mafra** — Mobile Threat Engineer @ Umain.
[@jacksonmafra-umain](https://github.com/jacksonmafra-umain) · [@jacksonfdam](https://github.com/jacksonfdam)

See [CREDITS.md](CREDITS.md) for upstream acknowledgements (ch0pin, JADX, Ghidra, MobSF, Frida, Burp, APKTool).

## License

TBD — everything here is currently private and opinionated.
