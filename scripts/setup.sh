#!/usr/bin/env bash
# MEDUSA NEXUS — installer.
#
# Opinionated. Idempotent. Runs on macOS and Debian/Ubuntu Linux.
# Installs: Python venv + package + all external tools + ch0pin frameworks
#           + (optional) Ghidra + MobSF docker + frida-server push.
#
# Usage:
#   scripts/setup.sh              full install
#   scripts/setup.sh --minimal    skip Ghidra, MobSF, frida-server
#   scripts/setup.sh --device     only push frida-server on the connected device
#   scripts/setup.sh --doctor     only run `mnexus doctor`
#   scripts/setup.sh --help
#
# Environment overrides:
#   MNEXUS_HOME        default $HOME/.mnexus
#   GHIDRA_VERSION     default 11.1.2 (see GHIDRA_RELEASES below)
#   FRIDA_VERSION      default latest release (queried from GitHub)
#   NO_COLOR=1         disable ANSI output

set -Eeuo pipefail

# ─── configuration ─────────────────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly MNEXUS_HOME="${MNEXUS_HOME:-$HOME/.mnexus}"
readonly MNEXUS_TOOLS="$MNEXUS_HOME/tools"
readonly MNEXUS_WORKSPACE="$MNEXUS_HOME/workspace"
readonly MNEXUS_ENV_FILE="$MNEXUS_HOME/env.sh"
readonly VENV_DIR="$REPO_ROOT/.venv"
readonly GHIDRA_VERSION="${GHIDRA_VERSION:-11.1.2}"

# ─── ANSI palette (cyberpunk terminal) ────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    readonly C_CYAN=$'\033[38;5;51m'
    readonly C_ACID=$'\033[38;5;120m'
    readonly C_MAGENTA=$'\033[38;5;213m'
    readonly C_RED=$'\033[38;5;203m'
    readonly C_MUTED=$'\033[38;5;244m'
    readonly C_BOLD=$'\033[1m'
    readonly C_RESET=$'\033[0m'
else
    readonly C_CYAN='' C_ACID='' C_MAGENTA='' C_RED='' C_MUTED='' C_BOLD='' C_RESET=''
fi

say()   { printf "${C_ACID}[NEXUS ]${C_RESET} %s\n" "$*"; }
warn()  { printf "${C_MAGENTA}[NEXUS !]${C_RESET} %s\n" "$*" >&2; }
fail()  { printf "${C_RED}[NEXUS X]${C_RESET} %s\n" "$*" >&2; exit 1; }
step()  { printf "\n${C_CYAN}${C_BOLD}» %s${C_RESET}\n" "$*"; }
hint()  { printf "  ${C_MUTED}%s${C_RESET}\n" "$*"; }
ok()    { printf "  ${C_ACID}✓${C_RESET} %s\n" "$*"; }

# ─── flags ────────────────────────────────────────────────────────────────
MODE="full"
for arg in "$@"; do
    case "$arg" in
        --minimal) MODE="minimal" ;;
        --device)  MODE="device" ;;
        --doctor)  MODE="doctor" ;;
        --help|-h)
            cat <<'HELP'
MEDUSA NEXUS — installer. Opinionated. Idempotent.

Usage:
  scripts/setup.sh              full install
  scripts/setup.sh --minimal    skip Ghidra, MobSF, frida-server
  scripts/setup.sh --device     only push frida-server on the connected device
  scripts/setup.sh --doctor     only run `mnexus doctor`
  scripts/setup.sh --help

Environment overrides:
  MNEXUS_HOME        default $HOME/.mnexus
  GHIDRA_VERSION     default 11.1.2
  FRIDA_VERSION      default = latest GitHub release
  NO_COLOR=1         disable ANSI output
HELP
            exit 0
            ;;
        *) fail "unknown flag: $arg (try --help)" ;;
    esac
done

# ─── platform detection ───────────────────────────────────────────────────
detect_platform() {
    step "detecting platform"
    local uname_s uname_m
    uname_s=$(uname -s)
    uname_m=$(uname -m)

    case "$uname_s" in
        Darwin) PLATFORM="darwin" ;;
        Linux)  PLATFORM="linux" ;;
        *) fail "unsupported OS: $uname_s. Try a real unix." ;;
    esac

    case "$uname_m" in
        arm64|aarch64) ARCH="arm64" ;;
        x86_64|amd64)  ARCH="x86_64" ;;
        *) fail "unsupported arch: $uname_m" ;;
    esac

    ok "$PLATFORM/$ARCH"
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "missing command: $1 — install it and come back."
}

# ─── python venv + package ────────────────────────────────────────────────
find_python() {
    for candidate in python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    fail "no Python >= 3.11 found. Install python@3.12 (brew/apt) and try again."
}

setup_python() {
    step "setting up Python venv ($VENV_DIR)"
    local py
    py=$(find_python)
    ok "interpreter: $py ($($py --version))"

    if [[ ! -d "$VENV_DIR" ]]; then
        "$py" -m venv "$VENV_DIR"
        ok "venv created"
    else
        hint "venv already exists — reusing"
    fi

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    step "installing Python dependencies (editable + dev extras)"
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
    "$VENV_DIR/bin/python" -m pip install --quiet -e "$REPO_ROOT[dev]"
    ok "mnexus installed in editable mode"
}

# ─── system tools (adb, jadx, apktool) ────────────────────────────────────
install_system_tools() {
    step "installing external tools (adb / jadx / apktool)"

    if [[ "$PLATFORM" == "darwin" ]]; then
        if ! command -v brew >/dev/null 2>&1; then
            fail "Homebrew not found. Install from https://brew.sh and re-run."
        fi
        for pkg in android-platform-tools jadx apktool; do
            if brew list --formula "$pkg" >/dev/null 2>&1; then
                hint "$pkg already installed"
            else
                say "brew install $pkg"
                brew install "$pkg"
            fi
        done
        ok "darwin tools ready"

    elif [[ "$PLATFORM" == "linux" ]]; then
        if command -v apt-get >/dev/null 2>&1; then
            say "sudo apt-get install adb apktool unzip curl (may prompt for password)"
            sudo apt-get update -qq
            sudo apt-get install -y --no-install-recommends adb apktool unzip curl default-jre-headless
            if ! command -v jadx >/dev/null 2>&1; then
                install_jadx_from_release
            fi
            ok "linux/apt tools ready"
        else
            fail "only apt-get is supported on Linux right now. PRs welcome."
        fi
    fi
}

install_jadx_from_release() {
    step "downloading jadx from GitHub releases"
    local tmp
    tmp=$(mktemp -d)
    local url
    url=$(curl -fsSL https://api.github.com/repos/skylot/jadx/releases/latest \
        | grep -E '"browser_download_url".*jadx-[0-9.]+\.zip' \
        | head -1 | cut -d'"' -f4)
    [[ -n "$url" ]] || fail "could not resolve jadx release url"
    curl -fsSL -o "$tmp/jadx.zip" "$url"
    mkdir -p "$MNEXUS_TOOLS/jadx"
    unzip -q -o "$tmp/jadx.zip" -d "$MNEXUS_TOOLS/jadx"
    rm -rf "$tmp"
    ok "jadx installed at $MNEXUS_TOOLS/jadx (bin/jadx)"
}

# ─── Ghidra (optional: --minimal skips) ───────────────────────────────────
install_ghidra() {
    step "installing Ghidra v$GHIDRA_VERSION"
    local target="$MNEXUS_TOOLS/ghidra"

    if [[ -x "$target/support/analyzeHeadless" ]]; then
        ok "Ghidra already at $target"
        return 0
    fi

    mkdir -p "$MNEXUS_TOOLS"
    local api="https://api.github.com/repos/NationalSecurityAgency/ghidra/releases"
    local url
    url=$(curl -fsSL "$api" \
        | grep -E "\"browser_download_url\".*ghidra_${GHIDRA_VERSION}_PUBLIC.*\\.zip\"" \
        | head -1 | cut -d'"' -f4)

    if [[ -z "$url" ]]; then
        warn "Ghidra v$GHIDRA_VERSION release not found on GitHub. Try another GHIDRA_VERSION="
        return 0
    fi

    say "downloading: $url"
    local tmp; tmp=$(mktemp -d)
    curl -fL --progress-bar -o "$tmp/ghidra.zip" "$url"
    say "unpacking (~400 MB; kettle-on time)"
    unzip -q "$tmp/ghidra.zip" -d "$tmp/unpack"
    local extracted
    extracted=$(find "$tmp/unpack" -maxdepth 1 -type d -name "ghidra_*" | head -1)
    [[ -n "$extracted" ]] || fail "extracted Ghidra layout unexpected"
    rm -rf "$target"
    mv "$extracted" "$target"
    rm -rf "$tmp"
    ok "Ghidra at $target"
}

# ─── ch0pin frameworks (Medusa + Stheno) ──────────────────────────────────
clone_ch0pin_frameworks() {
    step "cloning ch0pin frameworks"
    mkdir -p "$MNEXUS_TOOLS"

    clone_or_update() {
        local url="$1" dir="$2"
        if [[ -d "$dir/.git" ]]; then
            hint "updating $(basename "$dir")"
            git -C "$dir" pull --ff-only --quiet || warn "pull failed for $dir — keeping local state"
        else
            say "git clone $url"
            git clone --quiet "$url" "$dir"
        fi
    }
    clone_or_update "https://github.com/Ch0pin/medusa.git" "$MNEXUS_TOOLS/medusa"
    clone_or_update "https://github.com/Ch0pin/Stheno.git" "$MNEXUS_TOOLS/stheno"
    ok "Medusa + Stheno at $MNEXUS_TOOLS"
}

# ─── MobSF (Docker) ───────────────────────────────────────────────────────
pull_mobsf_docker() {
    step "pulling MobSF docker image"
    if ! command -v docker >/dev/null 2>&1; then
        warn "docker not installed — skipping MobSF. Install Docker Desktop / engine to enable."
        return 0
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "docker daemon not running — skipping MobSF. Start Docker and re-run later."
        return 0
    fi
    docker pull opensecurity/mobile-security-framework-mobsf:latest
    ok "image pulled. Start it with:"
    hint "docker run --rm -d -p 8000:8000 --name mobsf opensecurity/mobile-security-framework-mobsf:latest"
    hint "then set MNEXUS_MOBSF_API_KEY=<key from MobSF's /api_docs page>"
}

# ─── frida-server on connected device ─────────────────────────────────────
push_frida_server() {
    step "pushing frida-server to connected device"
    if ! command -v adb >/dev/null 2>&1; then
        warn "adb not on PATH — skipping frida-server push."
        return 0
    fi
    if ! adb devices | awk 'NR>1 && $2=="device"{found=1} END{exit !found}'; then
        warn "no device connected (adb devices shows nothing). Run: scripts/setup.sh --device"
        return 0
    fi

    local dev_abi
    dev_abi=$(adb shell getprop ro.product.cpu.abi | tr -d '\r')
    local frida_arch
    case "$dev_abi" in
        arm64-v8a) frida_arch="arm64" ;;
        armeabi-v7a) frida_arch="arm" ;;
        x86_64) frida_arch="x86_64" ;;
        x86) frida_arch="x86" ;;
        *) warn "unknown device ABI: $dev_abi — skipping"; return 0 ;;
    esac

    local frida_ver="${FRIDA_VERSION:-}"
    if [[ -z "$frida_ver" ]]; then
        frida_ver=$(curl -fsSL https://api.github.com/repos/frida/frida/releases/latest \
            | grep -m1 '"tag_name"' | cut -d'"' -f4)
    fi
    [[ -n "$frida_ver" ]] || fail "could not resolve frida release version"

    local url="https://github.com/frida/frida/releases/download/${frida_ver}/frida-server-${frida_ver}-android-${frida_arch}.xz"
    local tmp; tmp=$(mktemp -d)
    say "fetching $url"
    curl -fL --progress-bar -o "$tmp/frida-server.xz" "$url"
    xz -d "$tmp/frida-server.xz"

    say "pushing to /data/local/tmp/frida-server on device"
    adb push "$tmp/frida-server" /data/local/tmp/frida-server >/dev/null
    adb shell "chmod 755 /data/local/tmp/frida-server"
    rm -rf "$tmp"

    ok "frida-server staged. On a rooted device: adb shell su -c '/data/local/tmp/frida-server &'"
    hint "on non-rooted devices use Stheno to inject frida-gadget into the APK instead."
}

# ─── env file ─────────────────────────────────────────────────────────────
write_env_file() {
    step "writing env file: $MNEXUS_ENV_FILE"
    mkdir -p "$MNEXUS_HOME"

    local adb_path jadx_path apktool_path
    adb_path=$(command -v adb || echo adb)
    jadx_path=$(command -v jadx || echo "$MNEXUS_TOOLS/jadx/bin/jadx")
    apktool_path=$(command -v apktool || echo apktool)

    cat > "$MNEXUS_ENV_FILE" <<EOF
# Generated by scripts/setup.sh — $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Source me to hydrate NexusConfig:  source $MNEXUS_ENV_FILE

export MNEXUS_ADB_PATH="$adb_path"
export MNEXUS_JADX_PATH="$jadx_path"
export MNEXUS_APKTOOL_PATH="$apktool_path"
export MNEXUS_GHIDRA_PATH="$MNEXUS_TOOLS/ghidra"
export MNEXUS_MEDUSA_PATH="$MNEXUS_TOOLS/medusa"
export MNEXUS_STHENO_PATH="$MNEXUS_TOOLS/stheno"

export MNEXUS_WORKSPACE="$MNEXUS_WORKSPACE"
export MNEXUS_DB_PATH="$MNEXUS_HOME/nexus.sqlite3"

export MNEXUS_MOBSF_URL="http://localhost:8000"
# export MNEXUS_MOBSF_API_KEY="<paste from MobSF /api_docs once container is running>"
export MNEXUS_BURP_URL="http://localhost:1337"
# export MNEXUS_BURP_API_KEY="<paste from Burp Pro → Settings → API>"
EOF
    ok "env written. Source it in your shell: source $MNEXUS_ENV_FILE"
}

# ─── summary ──────────────────────────────────────────────────────────────
print_summary() {
    printf "\n${C_CYAN}${C_BOLD}╔══ MEDUSA NEXUS — setup complete ══╗${C_RESET}\n\n"
    printf "  next steps:\n"
    printf "    ${C_ACID}1.${C_RESET} activate the venv    ${C_MUTED}source .venv/bin/activate${C_RESET}\n"
    printf "    ${C_ACID}2.${C_RESET} load env vars        ${C_MUTED}source $MNEXUS_ENV_FILE${C_RESET}\n"
    printf "    ${C_ACID}3.${C_RESET} verify               ${C_MUTED}mnexus doctor${C_RESET}\n"
    printf "    ${C_ACID}4.${C_RESET} run web UI           ${C_MUTED}mnexus serve --port 8765${C_RESET}\n"
    printf "    ${C_ACID}5.${C_RESET} or scan an APK       ${C_MUTED}mnexus scan ./target.apk --package com.target.app${C_RESET}\n\n"
    printf "  docs: ${C_CYAN}docs/SPEC.md${C_RESET} · ${C_CYAN}design/INDEX.md${C_RESET} · ${C_CYAN}CREDITS.md${C_RESET}\n\n"
}

# ─── main ─────────────────────────────────────────────────────────────────
main() {
    printf "${C_CYAN}${C_BOLD}\n🔱  MEDUSA NEXUS // setup  ·  mode=%s${C_RESET}\n" "$MODE"

    detect_platform
    require_cmd git
    require_cmd curl

    case "$MODE" in
        device)
            push_frida_server
            exit 0
            ;;
        doctor)
            # shellcheck disable=SC1091
            [[ -f "$VENV_DIR/bin/activate" ]] && source "$VENV_DIR/bin/activate"
            [[ -f "$MNEXUS_ENV_FILE" ]] && source "$MNEXUS_ENV_FILE"
            mnexus doctor
            exit $?
            ;;
    esac

    setup_python
    install_system_tools
    clone_ch0pin_frameworks

    if [[ "$MODE" == "full" ]]; then
        install_ghidra
        pull_mobsf_docker
        push_frida_server
    else
        hint "--minimal: skipping Ghidra / MobSF / frida-server"
    fi

    write_env_file
    print_summary
}

main "$@"
