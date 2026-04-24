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
# Empty = auto-detect latest from GitHub. Override with GHIDRA_VERSION=X.Y.Z
readonly GHIDRA_VERSION="${GHIDRA_VERSION:-}"

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
        --mobsf)   MODE="mobsf" ;;
        --help|-h)
            cat <<'HELP'
MEDUSA NEXUS — installer. Opinionated. Idempotent.

Usage:
  scripts/setup.sh              full install
  scripts/setup.sh --minimal    skip Ghidra, MobSF, frida-server
  scripts/setup.sh --device     only push frida-server on the connected device
  scripts/setup.sh --mobsf      start MobSF in Docker with a pinned API key and write it to env
  scripts/setup.sh --doctor     only run `mnexus doctor`
  scripts/setup.sh --help

Environment overrides:
  MNEXUS_HOME        default $HOME/.mnexus
  GHIDRA_VERSION     default = latest GitHub release
  FRIDA_VERSION      default = latest GitHub release
  MOBSF_API_KEY      optional pinned key; auto-generated UUID if unset
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
    local target="$MNEXUS_TOOLS/ghidra"

    if [[ -x "$target/support/analyzeHeadless" ]]; then
        step "Ghidra already installed"
        ok "$target"
        return 0
    fi

    if [[ -n "$GHIDRA_VERSION" ]]; then
        step "installing Ghidra v$GHIDRA_VERSION"
    else
        step "installing Ghidra (latest release)"
    fi

    mkdir -p "$MNEXUS_TOOLS"

    local url
    # Try latest release first when no version pinned.
    if [[ -z "$GHIDRA_VERSION" ]]; then
        url=$(curl -fsSL "https://api.github.com/repos/NationalSecurityAgency/ghidra/releases/latest" \
            | grep -Eo '"browser_download_url":[^"]*"[^"]*ghidra_[^"]+_PUBLIC[^"]*\.zip"' \
            | head -1 | cut -d'"' -f4 || true)
    else
        url=$(curl -fsSL "https://api.github.com/repos/NationalSecurityAgency/ghidra/releases" \
            | grep -Eo "\"browser_download_url\":[^\"]*\"[^\"]*ghidra_${GHIDRA_VERSION}_PUBLIC[^\"]*\\.zip\"" \
            | head -1 | cut -d'"' -f4 || true)
    fi

    if [[ -z "${url:-}" ]]; then
        warn "could not resolve a Ghidra release zip from GitHub — skipping"
        hint "browse https://github.com/NationalSecurityAgency/ghidra/releases and set GHIDRA_VERSION=X.Y.Z"
        return 0
    fi

    say "downloading: $url"
    local tmp; tmp=$(mktemp -d)
    if ! curl -fL --progress-bar -o "$tmp/ghidra.zip" "$url"; then
        warn "download failed — skipping Ghidra"
        rm -rf "$tmp"
        return 0
    fi

    say "unpacking (~400 MB — kettle-on time)"
    unzip -q "$tmp/ghidra.zip" -d "$tmp/unpack" || { warn "unzip failed — skipping"; rm -rf "$tmp"; return 0; }
    local extracted
    extracted=$(find "$tmp/unpack" -maxdepth 1 -type d -name "ghidra_*" | head -1)
    if [[ -z "$extracted" ]]; then
        warn "unexpected Ghidra zip layout — skipping"
        rm -rf "$tmp"
        return 0
    fi
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
        warn "no device connected (adb devices shows nothing)."
        hint "plug a device in, authorize USB debugging, then: scripts/setup.sh --device"
        return 0
    fi
    if ! command -v xz >/dev/null 2>&1; then
        warn "xz not installed — skipping. On macOS: 'brew install xz'. On Linux: 'apt install xz-utils'."
        return 0
    fi

    local dev_abi frida_arch
    dev_abi=$(adb shell getprop ro.product.cpu.abi | tr -d '\r')
    case "$dev_abi" in
        arm64-v8a)   frida_arch="arm64"  ;;
        armeabi-v7a) frida_arch="arm"    ;;
        x86_64)      frida_arch="x86_64" ;;
        x86)         frida_arch="x86"    ;;
        *) warn "unknown device ABI: '$dev_abi' — skipping"; return 0 ;;
    esac
    ok "device ABI: $dev_abi → frida-server arch: $frida_arch"

    local frida_ver="${FRIDA_VERSION:-}"
    if [[ -z "$frida_ver" ]]; then
        frida_ver=$(curl -fsSL https://api.github.com/repos/frida/frida/releases/latest \
            | grep -m1 '"tag_name"' | cut -d'"' -f4 || true)
    fi
    if [[ -z "${frida_ver:-}" ]]; then
        warn "could not resolve frida release version (GitHub rate-limited?) — skipping"
        return 0
    fi
    ok "frida release: $frida_ver"

    local url="https://github.com/frida/frida/releases/download/${frida_ver}/frida-server-${frida_ver}-android-${frida_arch}.xz"
    hint "$url"

    # HEAD check first so we don't download a 404 page.
    if ! curl -fsSLI -o /dev/null "$url"; then
        warn "binary not found at the URL above — skipping."
        hint "asset naming may have changed. Browse https://github.com/frida/frida/releases"
        return 0
    fi

    local tmp; tmp=$(mktemp -d)
    say "downloading…"
    if ! curl -fL --progress-bar -o "$tmp/frida-server.xz" "$url"; then
        warn "download failed — skipping. Try again with better wifi."
        rm -rf "$tmp"
        return 0
    fi
    if ! xz -d "$tmp/frida-server.xz"; then
        warn "xz decompress failed — skipping."
        rm -rf "$tmp"
        return 0
    fi

    say "pushing to /data/local/tmp/frida-server"
    adb push "$tmp/frida-server" /data/local/tmp/frida-server >/dev/null || {
        warn "adb push failed — skipping"; rm -rf "$tmp"; return 0;
    }
    adb shell "chmod 755 /data/local/tmp/frida-server" || true
    rm -rf "$tmp"

    ok "frida-server staged on device."
    hint "on a rooted device: adb shell 'su -c \"/data/local/tmp/frida-server &\"'"
    hint "on a non-rooted device, use Stheno to inject frida-gadget into the APK."
}

# ─── MobSF container (pinned API key + env injection) ────────────────────
generate_api_key() {
    if command -v uuidgen >/dev/null 2>&1; then
        uuidgen | tr 'A-Z' 'a-z'
    else
        # Fallback: 32 hex chars from /dev/urandom.
        LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 32
        echo
    fi
}

# Upsert KEY=VALUE into the env file. Idempotent.
# $1 = var name (e.g. MNEXUS_MOBSF_API_KEY), $2 = value.
upsert_env_var() {
    local var="$1" val="$2"
    mkdir -p "$MNEXUS_HOME"
    touch "$MNEXUS_ENV_FILE"
    local line="export $var=\"$val\""
    # Strip any existing active or commented entries for this var.
    if grep -qE "^(# *)?export +$var=" "$MNEXUS_ENV_FILE"; then
        # sed -i portability: macOS BSD sed needs a backup suffix.
        sed -i.bak -E "/^(# *)?export +$var=/d" "$MNEXUS_ENV_FILE" && rm -f "$MNEXUS_ENV_FILE.bak"
    fi
    echo "$line" >> "$MNEXUS_ENV_FILE"
}

# Poll MobSF's home page until it answers or we give up.
wait_for_mobsf() {
    local max_seconds="${1:-45}" elapsed=0
    while (( elapsed < max_seconds )); do
        if curl -fsSL -o /dev/null --max-time 2 "http://localhost:8000/" 2>/dev/null; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        printf "  ${C_MUTED}…waiting on MobSF (%ds)${C_RESET}\r" "$elapsed"
    done
    echo ""
    return 1
}

# Verify an API key against MobSF. Returns 0 if the key works.
verify_mobsf_key() {
    local key="$1"
    local code
    # POST /api/v1/scans is the auth-wrapped endpoint. Without a body we expect
    # 400 (bad request) if the key passes, 401 if it doesn't.
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
        -X POST \
        -H "Authorization: $key" \
        -H "X-Mobsf-Api-Key: $key" \
        "http://localhost:8000/api/v1/scans" 2>/dev/null || echo "000")
    [[ "$code" != "401" && "$code" != "403" && "$code" != "000" ]]
}

# Parse the API key MobSF printed into its stdout logs. Covers several formats.
parse_mobsf_key_from_logs() {
    docker logs mobsf 2>&1 \
        | grep -iE 'api[[:space:]]*key' \
        | grep -oE '[a-f0-9]{32,64}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' \
        | tail -1
}

start_mobsf() {
    step "starting MobSF container with a pinned API key"
    if ! command -v docker >/dev/null 2>&1; then
        fail "docker not installed. Install Docker Desktop / engine and re-run."
    fi
    if ! docker info >/dev/null 2>&1; then
        fail "docker daemon not running. Start Docker and re-run."
    fi

    # Make sure the base MNEXUS_* vars are in the env file before we start
    # layering MobSF keys on top. Otherwise `--mobsf` alone produces a
    # half-populated file.
    write_env_file_base

    local key="${MOBSF_API_KEY:-$(generate_api_key)}"

    if docker ps -a --format '{{.Names}}' | grep -qx 'mobsf'; then
        warn "existing 'mobsf' container found — removing"
        docker rm -f mobsf >/dev/null 2>&1 || true
    fi

    say "docker run -d --name mobsf -p 8000:8000 -e MOBSF_API_KEY=<pinned>"
    docker run -d \
        --name mobsf \
        -p 8000:8000 \
        -e MOBSF_API_KEY="$key" \
        opensecurity/mobile-security-framework-mobsf:latest >/dev/null

    say "waiting for MobSF to boot (first start can take ~30s)"
    if ! wait_for_mobsf 60; then
        warn "MobSF didn't answer / within 60s. Check: docker logs mobsf"
        return 0
    fi
    ok "MobSF is up at http://localhost:8000"

    # Give MobSF a moment to finish its Django init before probing auth.
    sleep 3

    local effective_key="$key"
    if verify_mobsf_key "$key"; then
        ok "pinned API key authenticated"
    else
        warn "pinned key rejected (MobSF ignored the MOBSF_API_KEY env var on this image)."
        say "scraping the real key from container logs…"
        local logged_key
        logged_key=$(parse_mobsf_key_from_logs || true)
        if [[ -n "$logged_key" ]] && verify_mobsf_key "$logged_key"; then
            effective_key="$logged_key"
            ok "using key from container logs"
        else
            warn "could not auto-detect the working key."
            hint "open http://localhost:8000/api_docs in a browser and copy 'Your API Key'."
            hint "then: ./scripts/setup.sh --mobsf is idempotent — re-run after setting MOBSF_API_KEY=…"
        fi
    fi

    say "API key in effect: $effective_key"
    upsert_env_var "MNEXUS_MOBSF_API_KEY" "$effective_key"
    upsert_env_var "MNEXUS_MOBSF_URL" "http://localhost:8000"
    ok "wrote MNEXUS_MOBSF_API_KEY + MNEXUS_MOBSF_URL to $MNEXUS_ENV_FILE"
    hint "re-source your env file in this shell:  source $MNEXUS_ENV_FILE"
    hint "then verify with:                         mnexus doctor"
}

# ─── env file ─────────────────────────────────────────────────────────────
# Write every base MNEXUS_* var idempotently. Does NOT touch API keys the user
# (or start_mobsf) has already set.
write_env_file_base() {
    mkdir -p "$MNEXUS_HOME"

    local adb_path jadx_path apktool_path
    adb_path=$(command -v adb || echo adb)
    jadx_path=$(command -v jadx || echo "$MNEXUS_TOOLS/jadx/bin/jadx")
    apktool_path=$(command -v apktool || echo apktool)

    # Put a header line at the top once, if the file is empty.
    if [[ ! -s "$MNEXUS_ENV_FILE" ]]; then
        cat > "$MNEXUS_ENV_FILE" <<EOF
# Managed by scripts/setup.sh — re-running the installer is safe and idempotent.
# Source me in your shell:  source $MNEXUS_ENV_FILE
EOF
    fi

    upsert_env_var "MNEXUS_ADB_PATH"     "$adb_path"
    upsert_env_var "MNEXUS_JADX_PATH"    "$jadx_path"
    upsert_env_var "MNEXUS_APKTOOL_PATH" "$apktool_path"
    upsert_env_var "MNEXUS_GHIDRA_PATH"  "$MNEXUS_TOOLS/ghidra"
    upsert_env_var "MNEXUS_MEDUSA_PATH"  "$MNEXUS_TOOLS/medusa"
    upsert_env_var "MNEXUS_STHENO_PATH"  "$MNEXUS_TOOLS/stheno"
    upsert_env_var "MNEXUS_WORKSPACE"    "$MNEXUS_WORKSPACE"
    upsert_env_var "MNEXUS_DB_PATH"      "$MNEXUS_HOME/nexus.sqlite3"

    # Default service URLs — don't clobber if already set.
    grep -qE '^export +MNEXUS_MOBSF_URL=' "$MNEXUS_ENV_FILE" \
        || upsert_env_var "MNEXUS_MOBSF_URL" "http://localhost:8000"
    grep -qE '^export +MNEXUS_BURP_URL=' "$MNEXUS_ENV_FILE" \
        || upsert_env_var "MNEXUS_BURP_URL" "http://localhost:1337"
}

write_env_file() {
    step "writing env file: $MNEXUS_ENV_FILE"
    write_env_file_base
    ok "env written. Source it: source $MNEXUS_ENV_FILE"
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
        mobsf)
            start_mobsf
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
