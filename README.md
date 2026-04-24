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

**Pre-alpha.** The repo contains:

- Full product spec ([`docs/SPEC.md`](docs/SPEC.md)) and visual design language ([`docs/DESIGN_LANGUAGE.md`](docs/DESIGN_LANGUAGE.md)).
- 31-screen Pencil UI deck with 14 screens at hero fidelity ([`design/INDEX.md`](design/INDEX.md)).
- Python package scaffold: `Finding` / `AttackSurface` / `Project` models, `BaseEngine` ABC with 7 engine stubs, orchestrator, SQLite artifact store, intelligence layer (correlator + auto-hook generator), reporting with a mandatory Mitigation Playbook, Click CLI, FastAPI skeleton.
- 7 passing tests enforcing the "no finding without mitigation" invariant.

Most engine `execute()` methods still return `[]`. React frontend is 0% written. Detection rules are not yet shipped. See the honest gap list in the repo issues / the assistant's notes.

## Requirements

- **Python** 3.11+ (3.12 recommended).
- **Git**, **curl**, **unzip** on PATH.
- **macOS**: [Homebrew](https://brew.sh).
- **Debian / Ubuntu**: `apt-get` available (the script uses `sudo apt-get` for `adb` / `apktool`).
- **Docker** (optional, for MobSF).
- **Burp Suite** Professional (optional; closed-source, install manually).
- An **Android device or emulator** with USB debugging, plus `frida-server` or a Stheno-patched APK (the script can push `frida-server` for you).

## Quick start

```bash
git clone https://github.com/jacksonmafra-umain/medusa-nexus.git
cd medusa-nexus

./scripts/setup.sh           # full install — brews / apts, venv, ch0pin, Ghidra, MobSF docker
# or
./scripts/setup.sh --minimal # skip Ghidra (~400 MB), MobSF docker, frida-server push
```

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
| `--doctor` | only run `mnexus doctor` |
| `--help` | print usage |

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

### CLI commands

```bash
# Static scan an APK — runs every static engine in parallel,
# builds the attack surface, stores the project in SQLite.
mnexus scan ./target.apk --package com.target.app --version 4.12.0

# Dynamic session (stubbed in this revision; will run Frida + Medusa recipes).
mnexus dynamic --package com.target.app --modules ssl_bypass,root_bypass,crypto_log

# Generate a report — every template ships a Mitigation Playbook.
mnexus report --project PRJ-ABCD1234 \
              --template technical --format markdown \
              --output ./report.md

# Start the FastAPI backend + (eventually) serve the React UI at 127.0.0.1:8765.
mnexus serve --port 8765
```

### Web UI

`mnexus serve` exposes:

- `GET /v1/health` — liveness probe.
- `GET /v1/doctor` — same data as `mnexus doctor`, as JSON.
- `GET /v1/projects` — list stored projects.
- `GET /v1/projects/{id}` — full project JSON.

The React frontend lives under `mnexus/web/` (not shipped in this revision). Once implemented, `mnexus serve` will mount it at `/`. See [`design/INDEX.md`](design/INDEX.md) for the screen deck driving the UI.

### Device setup after first run

```bash
# Once a device is plugged in and USB debugging is authorized:
./scripts/setup.sh --device      # pushes frida-server to /data/local/tmp

# On a rooted device:
adb shell su -c '/data/local/tmp/frida-server &'

# On a non-rooted device, patch the APK instead of running frida-server:
# (handled by the Stheno engine; see docs/SPEC.md § 3.3)
```

## Development

```bash
source .venv/bin/activate

# run the test suite (7 tests, covers the mitigation invariants)
pytest

# lint + type-check (dev extras install these)
ruff check .
mypy mnexus

# launch the CLI in editable mode without reinstalling
python -m mnexus.cli doctor
```

## Structure

| Path | What lives here |
|---|---|
| `mnexus/` | Python package — models, engines, orchestrator, intelligence, reporting, CLI, API. |
| `tests/` | Pytest suite — mitigation invariant + report generator coverage. |
| `scripts/setup.sh` | One-shot installer (macOS + Linux). |
| `docs/SPEC.md` | Full product specification. |
| `docs/DESIGN_LANGUAGE.md` | Visual tokens, typography, motion effects. |
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
