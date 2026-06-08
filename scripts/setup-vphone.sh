#!/usr/bin/env bash
#
# scripts/setup-vphone.sh — install + verify wh1te4ever/super-tart-vphone for
# Medusa Nexus.
#
# What this script DOES (auto):
#   1. Verifies Apple Silicon, macOS Sequoia 15.7.4+ / Tahoe 26.3+, Xcode CLT.
#   2. Reports SIP, AMFI and `csrutil --research-guests` status (read-only).
#   3. Clones super-tart-vphone + super-tart-vphone-writeup into ~/.mnexus/tools/vphone/.
#   4. Builds the Swift package via `swift build -c release`.
#   5. Symlinks the built binary to ~/.mnexus/tools/vphone/bin/tart.
#   6. Persists MNEXUS_VPHONE_PATH + MNEXUS_TART_BIN into ~/.mnexus/env.sh.
#   7. Smoke-tests `tart --version` and prints next steps.
#
# What this script DOES NOT DO (because it shouldn't):
#   • Disable SIP / AMFI for you. Reboot to recoveryOS yourself.
#   • Download / patch / redistribute Apple firmware (cloudOS 26, iOS 26.1).
#     The first-boot path requires hand-tuned offsets per build — follow the
#     GUIDE.md in the cloned repo.
#   • Run `idevicerestore`, restore the patched IPSW, or inject Cryptexes.
#
# Flags:
#   --check       prereq + status only, don't clone / build
#   --rebuild     force `swift build -c release` even if binary exists
#   --uninstall   remove ~/.mnexus/tools/vphone/ and the env-file lines
#   --help        print this header
#
# Re-run safely. NO_COLOR=1 strips ANSI for CI logs.

set -euo pipefail

# ─── colors ─────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'; C_MAGENTA=$'\033[35m'
    C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
    C_CYAN=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_MAGENTA=""
    C_DIM=""; C_BOLD=""; C_RESET=""
fi

step() { printf "\n%s%s→ %s%s\n" "$C_BOLD" "$C_CYAN" "$*" "$C_RESET"; }
ok()   { printf "  %s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf "  %s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
fail() { printf "  %s✕%s %s\n" "$C_RED" "$C_RESET" "$*" >&2; }
note() { printf "  %s%s%s\n" "$C_DIM" "$*" "$C_RESET"; }
hl()   { printf "%s%s%s" "$C_BOLD" "$*" "$C_RESET"; }

abort() { fail "$1"; exit "${2:-1}"; }

# ─── argv ───────────────────────────────────────────────────────────────
MODE="install"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)     MODE="check";     shift ;;
        --rebuild)   MODE="rebuild";   shift ;;
        --uninstall) MODE="uninstall"; shift ;;
        --help|-h)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) fail "unknown flag: $1"; exit 2 ;;
    esac
done

# ─── paths ──────────────────────────────────────────────────────────────
NEXUS_HOME="${MNEXUS_HOME:-$HOME/.mnexus}"
TOOLS_DIR="$NEXUS_HOME/tools"
VPHONE_DIR="$TOOLS_DIR/vphone"
REPO_DIR="$VPHONE_DIR/super-tart-vphone"
WRITEUP_DIR="$VPHONE_DIR/super-tart-vphone-writeup"
BIN_DIR="$VPHONE_DIR/bin"
ENV_FILE="${MNEXUS_ENV_FILE:-$NEXUS_HOME/env.sh}"

# ─── 0. uninstall (early exit) ─────────────────────────────────────────
if [[ "$MODE" == "uninstall" ]]; then
    step "uninstall"
    if [[ -d "$VPHONE_DIR" ]]; then
        rm -rf "$VPHONE_DIR"
        ok "removed $VPHONE_DIR"
    else
        note "no install at $VPHONE_DIR"
    fi
    if [[ -f "$ENV_FILE" ]]; then
        # Strip our previous lines without nuking other entries.
        local_tmp=$(mktemp)
        grep -v -E '^(export )?MNEXUS_VPHONE_PATH=|^(export )?MNEXUS_TART_BIN=' "$ENV_FILE" > "$local_tmp" || true
        mv "$local_tmp" "$ENV_FILE"
        ok "cleaned $ENV_FILE"
    fi
    note "SIP/AMFI status untouched. Re-enable with: csrutil enable && nvram boot-args=\"\""
    exit 0
fi

# ─── 1. host prereqs ───────────────────────────────────────────────────
step "host check"

if [[ "$(uname -s)" != "Darwin" ]]; then
    abort "macOS only — super-tart-vphone uses Apple's Virtualization.framework"
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    abort "Apple Silicon only — Intel Macs cannot run vphone600ap"
fi
ok "Apple Silicon ($(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'unknown'))"

PRODUCT_NAME=$(sw_vers -productName 2>/dev/null || echo "")
PRODUCT_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "")
BUILD=$(sw_vers -buildVersion 2>/dev/null || echo "")
ok "$PRODUCT_NAME $PRODUCT_VERSION ($BUILD)"

# Version check: super-tart-vphone needs Sequoia 15.7.4+ or Tahoe 26.3+.
# We compare lexicographically over zero-padded major.minor.patch.
version_ok() {
    local v="$1" want_a="$2" want_b="$3"
    awk -v v="$v" -v a="$want_a" -v b="$want_b" '
    function pad(s,    n,p,parts) {
        n = split(s, parts, ".")
        p = ""
        for (i = 1; i <= 3; i++) { p = p sprintf("%03d", parts[i]+0) }
        return p
    }
    BEGIN {
        pv = pad(v); pa = pad(a); pb = pad(b)
        if (pv >= pa || pv >= pb) exit 0; else exit 1
    }'
}
if version_ok "$PRODUCT_VERSION" "15.7.4" "26.3"; then
    ok "macOS version meets the vphone requirement (15.7.4+ Sequoia or 26.3+ Tahoe)"
else
    warn "macOS $PRODUCT_VERSION may be too old — README requires 15.7.4 / 26.3 or newer"
    warn "the build will likely succeed but VM boot may fail at runtime"
fi

if ! command -v swift >/dev/null; then
    abort "swift not on PATH — install Xcode or 'xcode-select --install'"
fi
ok "swift $(swift --version 2>/dev/null | head -n1 | tr -d '\n')"

if ! command -v xcodebuild >/dev/null; then
    warn "xcodebuild not found — full Xcode (not just CLT) is required by super-tart"
    warn "install Xcode from the Mac App Store, then 'sudo xcode-select -s /Applications/Xcode.app'"
fi

# ─── 2. host security mode (read-only) ────────────────────────────────
step "host security mode (read-only — we never change these)"

if command -v csrutil >/dev/null; then
    SIP_STATUS=$(csrutil status 2>/dev/null || echo "")
    if echo "$SIP_STATUS" | grep -qi "disabled"; then
        ok "SIP: disabled"
    else
        warn "SIP appears enabled — vphone needs it disabled"
        note "  reboot to recoveryOS, then: csrutil disable"
        note "  also: csrutil allow-research-guests enable"
    fi
    # research-guests is a separate flag we want surfaced.
    if csrutil --help 2>&1 | grep -q "allow-research-guests"; then
        # Older csrutil doesn't print research-guests in `status`; we just
        # surface the requirement.
        note "  required: csrutil allow-research-guests enable  (run from recoveryOS)"
    fi
else
    warn "csrutil not on PATH — can't read SIP status"
fi

AMFI_BOOTARG=$(nvram boot-args 2>/dev/null | grep -oE 'amfi[a-zA-Z0-9_]*=[^[:space:]]+' | head -n1 || true)
if [[ -n "$AMFI_BOOTARG" ]]; then
    ok "AMFI boot-arg present: $AMFI_BOOTARG"
else
    warn "AMFI boot-arg not detected — vphone needs AMFI disabled"
    note "  from recoveryOS: nvram boot-args=\"amfi=0xff amfi_get_out_of_my_way=0x1\""
fi

if [[ "$MODE" == "check" ]]; then
    note "(--check) skipping clone + build"
    exit 0
fi

# ─── 3. clone ─────────────────────────────────────────────────────────
step "clone"
mkdir -p "$VPHONE_DIR" "$BIN_DIR"

clone_or_pull() {
    local repo="$1" dest="$2" name
    name="$(basename "$dest")"
    if [[ -d "$dest/.git" ]]; then
        ok "$name already cloned — fetching latest"
        ( cd "$dest" && git fetch --quiet origin && git pull --ff-only --quiet ) || warn "git pull failed for $name"
    else
        ok "cloning $name"
        git clone --quiet "$repo" "$dest"
    fi
}

clone_or_pull https://github.com/wh1te4ever/super-tart-vphone "$REPO_DIR"
clone_or_pull https://github.com/wh1te4ever/super-tart-vphone-writeup "$WRITEUP_DIR"

# ─── 4. build ─────────────────────────────────────────────────────────
step "build (swift build -c release)"

BUILT_BIN="$REPO_DIR/.build/release/tart"
SYMLINK="$BIN_DIR/tart"

needs_build=0
if [[ "$MODE" == "rebuild" ]]; then
    needs_build=1
elif [[ ! -x "$BUILT_BIN" ]]; then
    needs_build=1
fi

if [[ $needs_build -eq 1 ]]; then
    note "this can take several minutes on first run"
    pushd "$REPO_DIR" >/dev/null
    if ! swift build -c release 2>&1 | tee "$VPHONE_DIR/last-build.log" | tail -n 4; then
        popd >/dev/null
        abort "swift build failed — see $VPHONE_DIR/last-build.log"
    fi
    popd >/dev/null
    ok "built $BUILT_BIN"
else
    ok "binary already built ($BUILT_BIN) — pass --rebuild to force"
fi

# Symlink for stable path discovery.
ln -sf "$BUILT_BIN" "$SYMLINK"
ok "symlink $SYMLINK → $BUILT_BIN"

# ─── 5. env file ──────────────────────────────────────────────────────
step "env file ($ENV_FILE)"
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"

# Drop any previous lines for these vars, then re-append. Simple + idempotent.
tmp=$(mktemp)
grep -v -E '^(export )?MNEXUS_VPHONE_PATH=|^(export )?MNEXUS_TART_BIN=' "$ENV_FILE" > "$tmp" || true
{
    cat "$tmp"
    echo "# super-tart-vphone — wired by scripts/setup-vphone.sh"
    echo "export MNEXUS_VPHONE_PATH=\"$REPO_DIR\""
    echo "export MNEXUS_TART_BIN=\"$SYMLINK\""
} > "$ENV_FILE"
rm -f "$tmp"
ok "wrote MNEXUS_VPHONE_PATH + MNEXUS_TART_BIN"

# ─── 6. smoke test ────────────────────────────────────────────────────
step "smoke test"

if VERSION_OUT=$( "$SYMLINK" --version 2>&1 ); then
    ok "tart --version: $VERSION_OUT"
else
    warn "tart --version returned non-zero — but the binary built. Inspect with:"
    note "  $SYMLINK --help"
fi

# Detect if any VMs already exist.
VM_LIST=$( "$SYMLINK" list 2>/dev/null || true )
if echo "$VM_LIST" | grep -q '[a-z0-9]'; then
    ok "existing VMs:"
    echo "$VM_LIST" | sed 's/^/    /'
else
    note "no VMs yet — that's expected on a fresh install"
fi

# ─── 7. next steps ────────────────────────────────────────────────────
step "next steps"
cat <<EOF
  $(hl 'Source the env file in your shell:')
    source $ENV_FILE

  $(hl 'Then verify Medusa Nexus picked it up:')
    mnexus doctor                        # should list vphone alongside adb/jadx/...

  $(hl 'First-boot path (manual — by design):')
    Follow $REPO_DIR/GUIDE.md to:
      1. Extract cloudOS 26.x firmware (you must own / pull this yourself).
      2. Patch AVPBooter / iBSS / iBEC / LLB / TXM / kernelcache.
      3. Boot a VM in DFU + restore the patched IPSW via idevicerestore.
      4. Inject Cryptexes via SSH ramdisk.
      5. Run a normal-boot VM — SSH lands on root@127.0.0.1:2222 (alpine).

  $(hl 'Once a VM boots, you can wire frida-server into it with:')
    mnexus vphone bootstrap <vm-name>    # (Wave 2 — pending)

  ${C_DIM}docs:    docs-site/content/integrations/vphone.mdx
  guide:   $REPO_DIR/GUIDE.md
  writeup: $WRITEUP_DIR/${C_RESET}
EOF
echo
ok "done"
