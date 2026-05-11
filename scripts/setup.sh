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
#   scripts/setup.sh --moxy       start Moxy in Docker + extract & push the mitmproxy CA
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
        --burp)    MODE="burp" ;;
        --burp-rest-api) MODE="burp-rest-api" ;;
        --moxy)    MODE="moxy" ;;
        --help|-h)
            cat <<'HELP'
MEDUSA NEXUS — installer. Opinionated. Idempotent.

Usage:
  scripts/setup.sh              full install
  scripts/setup.sh --minimal    skip Ghidra, MobSF, frida-server
  scripts/setup.sh --device     only push frida-server on the connected device
  scripts/setup.sh --mobsf      start MobSF in Docker with a pinned API key and write it to env
  scripts/setup.sh --burp       verify Burp Pro REST API + write MNEXUS_BURP_URL / _API_KEY to env
  scripts/setup.sh --burp-rest-api   install vmware-archive/burp-rest-api (jar + run.sh wrapper)
  scripts/setup.sh --moxy       start Moxy in Docker, extract the mitmproxy CA, push to attached device
  scripts/setup.sh --doctor     only run `mnexus doctor`
  scripts/setup.sh --help

Environment overrides:
  MNEXUS_HOME        default $HOME/.mnexus
  GHIDRA_VERSION     default = latest GitHub release
  FRIDA_VERSION      default = latest GitHub release
  MOBSF_API_KEY      optional pinned key; auto-generated UUID if unset
  BURP_URL           default http://127.0.0.1:1337 (where Burp Pro's REST API listens)
  BURP_API_KEY       required for --burp mode (copy from Burp → Settings → Suite → API)
  BURP_SUITE_JAR     absolute path to burpsuite_pro.jar / burpsuite_community.jar
                     (for --burp-rest-api, auto-detected if installed via brew cask)
  MOXY_UI_PORT       default 5000 (host port mapped to Moxy's web UI)
  MOXY_PROXY_PORT    default 8081 (host port mapped to Moxy's MITM proxy)
  MOXY_PUSH_TO_DEVICE  default 1 — push the CA to /sdcard/Download via adb if a device is attached
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

# ─── Moxy (matank001/Moxy) — MITMproxy front-end for mobile traffic ──────

# Best-effort LAN IP detection so the device knows where to point its proxy.
# Loopback is useless: the phone has to reach the Mac on Wi-Fi/Ethernet.
_detect_lan_ip() {
    local ip=""
    if [[ "$PLATFORM" == "darwin" ]]; then
        for iface in en0 en1 en2 en3 en4 en5; do
            ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
            [[ -n "$ip" ]] && { echo "$ip"; return 0; }
        done
    else
        # Linux: prefer the interface that owns the default route.
        ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
        if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
            ip=$(hostname -I 2>/dev/null | awk '{print $1}')
        fi
        [[ -n "$ip" ]] && { echo "$ip"; return 0; }
    fi
    return 1
}

# Poll Moxy's UI port until it answers or we give up.
wait_for_moxy() {
    local port="$1" max_seconds="${2:-60}" elapsed=0
    while (( elapsed < max_seconds )); do
        if curl -fsSL -o /dev/null --max-time 2 "http://localhost:${port}/" 2>/dev/null; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        printf "  ${C_MUTED}…waiting on Moxy (%ds)${C_RESET}\r" "$elapsed"
    done
    echo ""
    return 1
}

# Pull the mitmproxy CA out of the running container. mitmproxy writes it on
# first start; the path has historically lived at ~/.mitmproxy inside the
# container. We try the common locations and fall back to a filesystem scan.
_extract_moxy_ca() {
    local dest="$1"
    local candidates=(
        "/root/.mitmproxy/mitmproxy-ca-cert.cer"
        "/root/.mitmproxy/mitmproxy-ca-cert.pem"
        "/home/moxy/.mitmproxy/mitmproxy-ca-cert.cer"
        "/app/.mitmproxy/mitmproxy-ca-cert.cer"
        "/app/projects_data/mitmproxy/mitmproxy-ca-cert.cer"
    )
    local found=""
    for path in "${candidates[@]}"; do
        if docker exec moxy test -f "$path" >/dev/null 2>&1; then
            found="$path"
            break
        fi
    done
    if [[ -z "$found" ]]; then
        # Brute-force: scan the container for any mitmproxy-ca-cert.* file.
        found=$(docker exec moxy sh -c 'find / -name "mitmproxy-ca-cert.*" -type f 2>/dev/null | head -1' || true)
    fi
    if [[ -z "$found" ]]; then
        return 1
    fi
    docker cp "moxy:$found" "$dest" >/dev/null 2>&1 || return 1
    return 0
}

start_moxy() {
    step "starting Moxy container (MITM proxy + web UI)"
    if ! command -v docker >/dev/null 2>&1; then
        fail "docker not installed. Install Docker Desktop / engine and re-run."
    fi
    if ! docker info >/dev/null 2>&1; then
        fail "docker daemon not running. Start Docker and re-run."
    fi

    # Make sure the base MNEXUS_* vars are present before layering Moxy on top.
    write_env_file_base

    local ui_port="${MOXY_UI_PORT:-5000}"
    local proxy_port="${MOXY_PROXY_PORT:-8081}"
    local data_dir="$MNEXUS_HOME/tools/moxy/projects_data"
    local ca_dir="$MNEXUS_HOME/tools/moxy"
    local ca_path="$ca_dir/moxy-ca.cer"
    mkdir -p "$data_dir" "$ca_dir"

    if docker ps -a --format '{{.Names}}' | grep -qx 'moxy'; then
        warn "existing 'moxy' container found — removing"
        docker rm -f moxy >/dev/null 2>&1 || true
    fi

    say "docker run -d --name moxy -p ${ui_port}:5000 -p ${proxy_port}:8081 ghcr.io/matank001/moxy:latest"
    docker run -d \
        --name moxy \
        -p "${ui_port}:5000" \
        -p "${proxy_port}:8081" \
        -v "$data_dir:/app/projects_data" \
        ghcr.io/matank001/moxy:latest >/dev/null

    say "waiting for Moxy UI to boot on port ${ui_port}"
    if ! wait_for_moxy "$ui_port" 60; then
        warn "Moxy didn't answer on http://localhost:${ui_port} within 60s. Check: docker logs moxy"
        return 0
    fi
    ok "Moxy UI is up at http://localhost:${ui_port}"

    # Give mitmproxy a beat to materialise its CA on first run.
    sleep 2

    step "extracting mitmproxy CA from the container"
    if _extract_moxy_ca "$ca_path"; then
        ok "CA written to $ca_path"
    else
        warn "couldn't find the mitmproxy CA inside the container."
        hint "run any request through the proxy first, then re-run scripts/setup.sh --moxy"
        ca_path=""
    fi

    # LAN IP — what the device should actually point at.
    local lan_ip
    lan_ip=$(_detect_lan_ip || true)
    if [[ -n "$lan_ip" ]]; then
        ok "LAN IP detected: $lan_ip"
    else
        warn "couldn't detect a LAN IP. Pick the right interface manually:"
        hint "macOS:  ipconfig getifaddr en0"
        hint "Linux:  ip route get 1.1.1.1"
        lan_ip="localhost"
    fi

    # Optional: push the CA to a connected Android device.
    local push="${MOXY_PUSH_TO_DEVICE:-1}"
    if [[ -n "$ca_path" && "$push" == "1" ]] && command -v adb >/dev/null 2>&1; then
        local n_devices
        n_devices=$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device"{n++} END {print n+0}')
        if (( n_devices >= 1 )); then
            step "pushing CA to /sdcard/Download on the connected device"
            if adb push "$ca_path" /sdcard/Download/moxy-ca.cer >/dev/null 2>&1; then
                ok "pushed: install via Settings → Security → Encryption & credentials → Install a certificate → CA certificate"
            else
                warn "adb push failed. Move the file by hand: $ca_path"
            fi
        else
            hint "no adb device detected — skipping push. Plug the phone in + authorise USB debugging, then re-run."
        fi
    fi

    # Persist what we know.
    upsert_env_var "MNEXUS_MOXY_URL"        "http://localhost:${ui_port}"
    upsert_env_var "MNEXUS_MOXY_PROXY_HOST" "$lan_ip"
    upsert_env_var "MNEXUS_MOXY_PROXY_PORT" "$proxy_port"
    [[ -n "$ca_path" ]] && upsert_env_var "MNEXUS_MOXY_CA_PATH" "$ca_path"

    ok "wrote MNEXUS_MOXY_URL / _PROXY_HOST / _PROXY_PORT to $MNEXUS_ENV_FILE"

    cat <<EOF

  ${C_CYAN}${C_BOLD}» device-side setup${C_RESET}
    1. Wi-Fi → long-press the SSID → Modify network → Advanced
       proxy: ${C_ACID}Manual${C_RESET}
       host:  ${C_ACID}${lan_ip}${C_RESET}
       port:  ${C_ACID}${proxy_port}${C_RESET}
    2. Settings → Security → Encryption & credentials → Install a certificate
       → CA certificate → pick ${C_ACID}moxy-ca.cer${C_RESET} from Downloads
    3. open ${C_CYAN}http://localhost:${ui_port}${C_RESET} on this Mac to watch traffic

  ${C_MUTED}TLS-pinned apps will still fail — patch with Stheno or hook with Frida (Recipes panel: SSL / RESILIENCE).${C_RESET}
EOF
}

# ─── burp-rest-api (vmware-archive) — Burp + Spring Boot wrapper ─────────
# Downloads the release jar, best-effort locates burpsuite_community.jar or
# burpsuite_pro.jar (optionally installing Burp via brew cask on macOS),
# writes a `run.sh` wrapper that searches for the jar at LAUNCH TIME, and
# points MNEXUS_BURP_URL at the local REST server.

# Print the list of candidate paths we search. Kept here (outside the
# function) so we can reuse the same list inside the generated run.sh.
_burp_suite_jar_candidates() {
    cat <<'EOF'
/Applications/Burp Suite Professional.app/Contents/Resources/app/burpsuite_pro.jar
/Applications/Burp Suite Community Edition.app/Contents/Resources/app/burpsuite_community.jar
/Applications/Burp Suite Professional.app/Contents/app/burpsuite_pro.jar
/Applications/Burp Suite Community Edition.app/Contents/app/burpsuite_community.jar
/Applications/Burp Suite Professional.app/Contents/java/app/burpsuite_pro.jar
/Applications/Burp Suite Community Edition.app/Contents/java/app/burpsuite_community.jar
/Applications/BurpSuitePro/burpsuite_pro.jar
/Applications/BurpSuiteCommunity/burpsuite_community.jar
$HOME/Applications/Burp Suite Professional.app/Contents/Resources/app/burpsuite_pro.jar
$HOME/Applications/Burp Suite Community Edition.app/Contents/Resources/app/burpsuite_community.jar
$HOME/BurpSuitePro/burpsuite_pro.jar
$HOME/BurpSuiteCommunity/burpsuite_community.jar
/opt/BurpSuitePro/burpsuite_pro.jar
/opt/BurpSuiteCommunity/burpsuite_community.jar
EOF
}

_find_burp_suite_jar() {
    # Try $BURP_SUITE_JAR first, then the candidate list, then a broad glob
    # of /Applications (in case Burp's bundle layout moved again).
    if [[ -n "${BURP_SUITE_JAR:-}" && -f "$BURP_SUITE_JAR" ]]; then
        echo "$BURP_SUITE_JAR"
        return 0
    fi
    local line
    while IFS= read -r line; do
        # Expand $HOME inside the list.
        line="${line//\$HOME/$HOME}"
        if [[ -f "$line" ]]; then
            echo "$line"
            return 0
        fi
    done < <(_burp_suite_jar_candidates)
    # Last-ditch glob (bounded to /Applications so we don't wander the disk).
    local found
    found=$(find /Applications -maxdepth 6 -type f \( -name 'burpsuite_pro.jar' -o -name 'burpsuite_community.jar' \) 2>/dev/null | head -1 || true)
    [[ -n "$found" ]] && echo "$found"
}

install_burp_rest_api() {
    step "installing burp-rest-api (vmware-archive)"

    if ! command -v java >/dev/null 2>&1; then
        warn "java not found. burp-rest-api needs a JRE (Java 11+; 21 for the latest)."
        hint "macOS:  brew install --cask temurin"
        hint "Linux:  sudo apt-get install -y default-jre-headless"
        return 0
    fi
    ok "java: $(java -version 2>&1 | head -1)"

    mkdir -p "$MNEXUS_TOOLS"
    local install_dir="$MNEXUS_TOOLS/burp-rest-api"
    mkdir -p "$install_dir"

    # 1. Resolve latest release jar URL
    local jar_url
    jar_url=$(curl -fsSL "https://api.github.com/repos/vmware-archive/burp-rest-api/releases/latest" \
        | grep -Eo '"browser_download_url":[^"]*"[^"]*burp-rest-api-[^"]+\.jar"' \
        | head -1 | cut -d'"' -f4 || true)

    if [[ -z "$jar_url" ]]; then
        warn "could not resolve burp-rest-api release — skipping."
        hint "check https://github.com/vmware-archive/burp-rest-api/releases manually."
        return 0
    fi

    local jar_name jar_path
    jar_name=$(basename "$jar_url")
    jar_path="$install_dir/$jar_name"

    if [[ -f "$jar_path" ]]; then
        ok "already at $jar_path"
    else
        say "downloading: $jar_url"
        if ! curl -fL --progress-bar -o "$jar_path" "$jar_url"; then
            warn "download failed — skipping."
            rm -f "$jar_path"
            return 0
        fi
        ok "downloaded $jar_name"
    fi

    # 2. Try to locate burpsuite jar.
    local burp_jar
    burp_jar=$(_find_burp_suite_jar || true)

    # 2a. On macOS, if we didn't find it and we have brew, offer to install
    #     Burp Community. Non-interactive runs skip the prompt.
    if [[ -z "$burp_jar" && "$PLATFORM" == "darwin" ]] && command -v brew >/dev/null 2>&1; then
        if [[ -t 0 ]]; then
            printf "  ${C_MAGENTA}no Burp Suite found. Install Community via brew cask? [Y/n] ${C_RESET}"
            local reply
            read -r reply
            reply="${reply:-y}"
            if [[ "$reply" =~ ^[Yy] ]]; then
                say "brew install --cask burp-suite"
                brew install --cask burp-suite || warn "brew cask install failed. Install Burp manually then re-run."
                burp_jar=$(_find_burp_suite_jar || true)
            fi
        else
            hint "non-interactive: install Burp with  ${C_CYAN}brew install --cask burp-suite${C_RESET}"
        fi
    fi

    if [[ -n "$burp_jar" ]]; then
        ok "detected Burp jar: $burp_jar"
    else
        warn "no Burp Suite jar found."
        hint "install Burp, then run:  $install_dir/run.sh"
        hint "  macOS: brew install --cask burp-suite"
        hint "  Linux: download from https://portswigger.net/burp/communitydownload"
        hint "  the wrapper will search again at launch time — no re-setup needed."
    fi

    # 3. Emit a wrapper that re-detects the Burp jar at LAUNCH TIME.
    local run_sh="$install_dir/run.sh"
    {
        cat <<'LAUNCHER_HEAD'
#!/usr/bin/env bash
# Auto-generated by mnexus setup. Launches burp-rest-api in headless mode.
# Re-detects the Burp Suite jar every time, so you can run setup once and
# install Burp afterwards without re-running anything.
#
# Env overrides: PORT, BURP_SUITE_JAR, REST_API_JAR, HEADLESS, JAVA_OPTS.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8090}"
HEADLESS="${HEADLESS:-true}"
JAVA_OPTS="${JAVA_OPTS:--Xmx2g -Djava.awt.headless=${HEADLESS}}"

REST_API_JAR="${REST_API_JAR:-$(ls "$HERE"/burp-rest-api-*.jar 2>/dev/null | head -1 || true)}"
if [[ -z "$REST_API_JAR" || ! -f "$REST_API_JAR" ]]; then
    echo "burp-rest-api jar not found in $HERE — re-run scripts/setup.sh --burp-rest-api" >&2
    exit 2
fi

# Candidate list (kept in sync with the installer).
BURP_CANDIDATES=(
LAUNCHER_HEAD
        # Embed each candidate as a quoted array element.
        while IFS= read -r line; do
            printf '    "%s"\n' "${line//\$HOME/\$HOME}"
        done < <(_burp_suite_jar_candidates)
        cat <<'LAUNCHER_TAIL'
)

find_burp_jar() {
    if [[ -n "${BURP_SUITE_JAR:-}" && -f "$BURP_SUITE_JAR" ]]; then
        echo "$BURP_SUITE_JAR"; return 0
    fi
    local c
    for c in "${BURP_CANDIDATES[@]}"; do
        if [[ -f "$c" ]]; then
            echo "$c"; return 0
        fi
    done
    # Fallback: shallow glob under /Applications.
    local found
    found=$(find /Applications -maxdepth 6 -type f \
        \( -name 'burpsuite_pro.jar' -o -name 'burpsuite_community.jar' \) \
        2>/dev/null | head -1 || true)
    [[ -n "$found" ]] && echo "$found"
}

BURP_SUITE_JAR="$(find_burp_jar || true)"
if [[ -z "$BURP_SUITE_JAR" ]]; then
    echo "burpsuite_*.jar not found on this system." >&2
    echo "Install Burp Suite:" >&2
    echo "  macOS: brew install --cask burp-suite" >&2
    echo "  Linux: https://portswigger.net/burp/communitydownload" >&2
    echo "Or set BURP_SUITE_JAR=/abs/path/to/burpsuite.jar and re-run." >&2
    exit 3
fi

echo "[burp-rest-api] burp jar      = $BURP_SUITE_JAR"
echo "[burp-rest-api] rest-api jar  = $REST_API_JAR"
echo "[burp-rest-api] listening on  = http://localhost:$PORT"

exec java $JAVA_OPTS \
    -cp "$BURP_SUITE_JAR:$REST_API_JAR" \
    -Dorg.springframework.boot.logging.LoggingSystem=none \
    org.springframework.boot.loader.launch.JarLauncher \
    --server.port="$PORT" \
    --headless.mode="$HEADLESS"
LAUNCHER_TAIL
    } > "$run_sh"
    chmod +x "$run_sh"
    ok "launcher: $run_sh"

    # 4. Write env vars. burp-rest-api uses no API key by default; MNEXUS_BURP_API_KEY=none
    #    tells the engine to probe the burp-rest-api shape.
    write_env_file_base
    upsert_env_var "MNEXUS_BURP_URL"     "http://localhost:8090"
    upsert_env_var "MNEXUS_BURP_API_KEY" "none"
    ok "set MNEXUS_BURP_URL=http://localhost:8090  MNEXUS_BURP_API_KEY=none"

    # 5. How to run
    echo
    say "to launch burp-rest-api:"
    printf "    ${C_ACID}%s${C_RESET}\n" "$run_sh"
    hint "then:   source $MNEXUS_ENV_FILE && mnexus doctor"

    # 6. Compatibility caveat.
    warn "heads up: vmware-archive/burp-rest-api is unmaintained and tied to specific Burp versions."
    hint "works best with Burp 2020.x–2023.x. Newer Burp builds may break internal APIs."
}

# ─── Burp Suite Pro REST API (no daemon to launch — just verify + env) ───
configure_burp() {
    step "configuring Burp Suite Pro REST API"

    printf "  ${C_MUTED}Burp Pro exposes a REST API at ${C_RESET}http://<host>:<port>/<api_key>/v0.1/\n"
    printf "  ${C_MUTED}Enable it in: ${C_CYAN}Burp → Settings → Suite → API${C_RESET}\n"
    printf "  ${C_MUTED}Then copy the generated ${C_CYAN}API key${C_MUTED} and the ${C_CYAN}Service URL${C_MUTED}.${C_RESET}\n"
    echo

    local url="${BURP_URL:-http://127.0.0.1:1337}"
    local key="${BURP_API_KEY:-}"

    # If the user didn't pass env vars, ask interactively (only when stdin is a tty).
    if [[ -z "$key" && -t 0 ]]; then
        read -r -p "  Burp REST URL [$url]: " input_url
        [[ -n "$input_url" ]] && url="$input_url"
        read -r -p "  Burp API key: " key
    fi

    if [[ -z "$key" ]]; then
        warn "no BURP_API_KEY supplied — skipping."
        hint "re-run:  BURP_API_KEY=<key> [BURP_URL=<url>] scripts/setup.sh --burp"
        return 0
    fi

    # Make sure base vars exist before we layer Burp entries on top.
    write_env_file_base

    # Verify the key against Burp. Expect 200 on the v0.1 root path.
    local probe="$url/$key/v0.1/"
    say "probing $probe"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$probe" 2>/dev/null || echo "000")

    case "$code" in
        200)
            ok "Burp REST API reachable and authenticated"
            ;;
        000)
            warn "no response — is Burp Suite Pro running with the REST API enabled?"
            hint "writing the values to env anyway so mnexus doctor can point at them."
            ;;
        401|403)
            warn "Burp rejected the key ($code). Generate a new one in the Suite API panel and re-run."
            ;;
        404)
            warn "Burp answered 404 at /$key/v0.1/ — the key path is wrong. Check the API panel."
            ;;
        *)
            warn "Burp answered $code. Saving values anyway — investigate with 'mnexus doctor'."
            ;;
    esac

    upsert_env_var "MNEXUS_BURP_URL"     "$url"
    upsert_env_var "MNEXUS_BURP_API_KEY" "$key"
    ok "wrote MNEXUS_BURP_URL + MNEXUS_BURP_API_KEY to $MNEXUS_ENV_FILE"
    hint "re-source:  source $MNEXUS_ENV_FILE"
    hint "then:       mnexus doctor"
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
    grep -qE '^export +MNEXUS_MOXY_URL=' "$MNEXUS_ENV_FILE" \
        || upsert_env_var "MNEXUS_MOXY_URL" "http://localhost:5000"
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
        burp)
            configure_burp
            exit 0
            ;;
        burp-rest-api)
            install_burp_rest_api
            exit 0
            ;;
        moxy)
            start_moxy
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
