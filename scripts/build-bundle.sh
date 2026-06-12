#!/usr/bin/env bash
# MEDUSA NEXUS — desktop bundle builder.
#
# Freezes the mnexus Python core into a single-file sidecar, fetches the adb
# binary, builds the React frontend, and runs `tauri build` to produce the
# native installer (.dmg / .deb / .AppImage). macOS + Linux only — Windows is
# WSL2-per the requirements doc, so we don't emit a native .msi.
#
# Layout assumed (scaffold once with `pnpm create tauri-app` into desktop/):
#   desktop/                  Tauri app (React frontend)
#   desktop/src-tauri/        Rust shell
#   desktop/src-tauri/bin/    sidecars land here, target-triple-suffixed
#
# Usage:
#   scripts/build-bundle.sh            full build for the host platform
#   scripts/build-bundle.sh --sidecar  only (re)freeze the Python sidecar
#   scripts/build-bundle.sh --tools    only fetch adb
#
# Env:
#   FRIDA_VERSION   pin frida to match the device frida-server (default: from pyproject)

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly DESKTOP_DIR="$REPO_ROOT/desktop"
readonly BIN_DIR="$DESKTOP_DIR/src-tauri/bin"

# Rust's host triple is the suffix Tauri expects on externalBin (adb-<triple>).
TARGET_TRIPLE="$(rustc -Vv | sed -n 's/host: //p')"
readonly TARGET_TRIPLE

log() { printf '\033[36m[bundle]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[bundle] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 1. Freeze mnexus into a single-file host sidecar ───────────────────────
# This is the host-side core: device bridges, frida, tart, proxies, SQLite.
# It is NOT in Docker — it needs USB and the Keychain.
build_sidecar() {
  log "freezing mnexus → sidecar (target: $TARGET_TRIPLE)"
  command -v pyinstaller >/dev/null || pip install pyinstaller
  pip install -e "$REPO_ROOT" >/dev/null

  pyinstaller \
    --noconfirm --onefile --clean \
    --name "mnexus-server" \
    --collect-all mnexus \
    --collect-all frida \
    --hidden-import uvicorn.logging \
    --distpath "$BIN_DIR" \
    "$REPO_ROOT/scripts/_sidecar_entry.py"

  # Tauri requires the target-triple suffix on externalBin sidecars.
  mkdir -p "$BIN_DIR"
  mv "$BIN_DIR/mnexus-server" "$BIN_DIR/mnexus-server-$TARGET_TRIPLE"
  log "sidecar → $BIN_DIR/mnexus-server-$TARGET_TRIPLE"
}

# ── 2. Fetch adb (the one host binary we always bundle — tiny) ─────────────
fetch_adb() {
  log "fetching adb platform-tools for $TARGET_TRIPLE"
  local os zip
  case "$TARGET_TRIPLE" in
    *apple-darwin*)  os="darwin" ;;
    *linux*)         os="linux" ;;
    *)               die "unsupported target for adb: $TARGET_TRIPLE" ;;
  esac
  zip="$(mktemp -d)/pt.zip"
  curl -fsSL -o "$zip" "https://dl.google.com/android/repository/platform-tools-latest-${os}.zip"
  unzip -q -o "$zip" -d "$(dirname "$zip")"
  mkdir -p "$BIN_DIR"
  cp "$(dirname "$zip")/platform-tools/adb" "$BIN_DIR/adb-$TARGET_TRIPLE"
  chmod +x "$BIN_DIR/adb-$TARGET_TRIPLE"
  log "adb → $BIN_DIR/adb-$TARGET_TRIPLE"
}

# ── 3. Frontend + Tauri build ──────────────────────────────────────────────
build_app() {
  log "building frontend + native bundle"
  ( cd "$DESKTOP_DIR" && pnpm install --frozen-lockfile && pnpm tauri build )
  log "bundle(s) in $DESKTOP_DIR/src-tauri/target/release/bundle/"
}

main() {
  case "${1:-}" in
    --sidecar) build_sidecar ;;
    --tools)   fetch_adb ;;
    "")        build_sidecar; fetch_adb; build_app ;;
    *)         die "unknown flag: $1" ;;
  esac
  log "done."
}
main "$@"
