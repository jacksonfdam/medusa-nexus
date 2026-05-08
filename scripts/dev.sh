#!/usr/bin/env bash
#
# scripts/dev.sh — one-command bootstrap + live-reload dev server.
#
# Run from the repo root. Idempotent: safe to re-run.
#
#   ./scripts/dev.sh                  # default 127.0.0.1:8765
#   ./scripts/dev.sh --port 9090
#   ./scripts/dev.sh --no-browser     # don't auto-open the browser
#   ./scripts/dev.sh --check          # bootstrap + verify only, don't serve
#
# What it does:
#   1. Verifies Python 3.11+ is on PATH.
#   2. Creates a `.venv/` if missing and installs the package in editable mode.
#   3. Sources `~/.mnexus/env.sh` if present (engine paths + service URLs).
#   4. Runs `mnexus doctor` so you see engine status before the server starts.
#   5. Launches uvicorn with --reload (auto-restart on .py changes).
#   6. Polls /v1/health in the background and prints ✓/✕ each restart.
#   7. Optionally opens http://127.0.0.1:8765/ in the default browser.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ─── colors ─────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'; C_MAGENTA=$'\033[35m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
    C_CYAN=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_MAGENTA=""; C_DIM=""; C_BOLD=""; C_RESET=""
fi

say()  { printf "%s🔱%s %s\n" "$C_CYAN" "$C_RESET" "$*"; }
ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
fail() { printf "  %s✕%s %s\n" "$C_RED" "$C_RESET" "$*" >&2; }
step() { printf "\n%s%s→ %s%s\n" "$C_BOLD" "$C_CYAN" "$*" "$C_RESET"; }

# ─── argv ───────────────────────────────────────────────────────────────
PORT=8765
HOST="127.0.0.1"
OPEN_BROWSER=1
CHECK_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)        PORT="$2"; shift 2 ;;
        --host)        HOST="$2"; shift 2 ;;
        --no-browser)  OPEN_BROWSER=0; shift ;;
        --check)       CHECK_ONLY=1; shift ;;
        --help|-h)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) fail "unknown arg: $1"; exit 2 ;;
    esac
done

# ─── 1. python ──────────────────────────────────────────────────────────
step "checking python"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null; then
    fail "python3 not on PATH"
    exit 1
fi
PY_VERSION=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    fail "python ${PY_VERSION} found — mnexus needs 3.11+"
    fail "macOS:  brew install python@3.13   ·   linux:  apt-get install python3.11"
    exit 1
fi
ok "python ${PY_VERSION}"

# ─── 2. venv ────────────────────────────────────────────────────────────
step "venv + deps"
if [[ ! -d .venv ]]; then
    "$PY" -m venv .venv
    ok "created .venv/"
fi
# shellcheck disable=SC1091
. .venv/bin/activate

# Install the package in editable mode + dev extras if not already importable.
if ! python -c 'import mnexus' >/dev/null 2>&1 || [[ "${1:-}" == "--reinstall" ]]; then
    pip install -q --upgrade pip
    pip install -q -e '.[dev]'
    pip install -q prompt_toolkit  # cushy CLI autocomplete
    ok "installed mnexus in editable mode"
else
    ok "mnexus already installed"
fi

# ─── 3. env file ────────────────────────────────────────────────────────
ENV_FILE="${MNEXUS_ENV_FILE:-$HOME/.mnexus/env.sh}"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    ok "loaded $ENV_FILE"
else
    warn "no $ENV_FILE — engine paths default to PATH lookup"
    warn "tip: run scripts/setup.sh to populate engine paths + service URLs"
fi

# ─── 4. doctor ──────────────────────────────────────────────────────────
step "engine doctor"
if mnexus doctor; then
    DOCTOR_OK=1
else
    DOCTOR_OK=0
    warn "some engines are missing — server still works, just with reduced detection"
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
    if [[ "$DOCTOR_OK" -eq 1 ]]; then
        ok "verify ok"
        exit 0
    fi
    exit 1
fi

# ─── 5. health-check watchdog (background) ─────────────────────────────
# Polls every 5s by default — the previous 1s loop flooded the uvicorn
# access log with /v1/health hits without giving meaningfully faster
# reload-detection (uvicorn restart takes ~200-500ms; users see the
# next ✓/✕ within 5s, which is plenty). Override via env.
HEALTH_URL="http://${HOST}:${PORT}/v1/health"
HEALTH_POLL_INTERVAL_S="${MNEXUS_HEALTH_POLL_INTERVAL_S:-5}"
(
    LAST_STATE=""
    sleep 2
    while true; do
        if curl -sf -o /dev/null --max-time 1 "$HEALTH_URL"; then
            STATE="up"
        else
            STATE="down"
        fi
        if [[ "$STATE" != "$LAST_STATE" ]]; then
            if [[ "$STATE" == "up" ]]; then
                printf "%s✓%s %s/v1/health[%s] OK\n" "$C_GREEN" "$C_RESET" "$C_DIM" "$C_RESET"
                if [[ "$OPEN_BROWSER" -eq 1 && "$LAST_STATE" == "" ]]; then
                    if command -v open >/dev/null; then open "http://${HOST}:${PORT}/" || true
                    elif command -v xdg-open >/dev/null; then xdg-open "http://${HOST}:${PORT}/" || true
                    fi
                fi
            else
                printf "%s✕%s server reloading or down…\n" "$C_YELLOW" "$C_RESET"
            fi
            LAST_STATE="$STATE"
        fi
        sleep "$HEALTH_POLL_INTERVAL_S"
    done
) &
WATCH_PID=$!
trap 'kill $WATCH_PID 2>/dev/null || true' EXIT

# ─── 6. uvicorn with reload ─────────────────────────────────────────────
step "starting server (auto-reload on .py changes)"
say "${C_BOLD}http://${HOST}:${PORT}/${C_RESET}      ${C_DIM}web ui${C_RESET}"
say "${C_BOLD}http://${HOST}:${PORT}/docs${C_RESET}  ${C_DIM}swagger${C_RESET}"
echo
exec python -m uvicorn mnexus.api.main:app \
    --host "$HOST" --port "$PORT" \
    --reload --reload-dir mnexus \
    --log-level info
