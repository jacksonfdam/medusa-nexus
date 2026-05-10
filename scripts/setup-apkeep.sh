#!/usr/bin/env bash
# scripts/setup-apkeep.sh — install EFForg/apkeep so the ApkeepEngine can
# fetch APKs from Google Play / Aurora / F-Droid / APKPure / Huawei.

set -euo pipefail

bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
note()  { printf "\033[2m  %s\033[0m\n" "$*"; }

bold "🔱 MEDUSA NEXUS · setting up apkeep"
echo

if command -v apkeep >/dev/null 2>&1; then
    green "  ✓ apkeep already installed: $(apkeep --version 2>&1 | tail -1)"
    note  "    re-run with --force to upgrade"
    [[ "${1:-}" == "--force" ]] || exit 0
fi

OS="$(uname -s)"
case "$OS" in
    Darwin)
        if command -v brew >/dev/null 2>&1; then
            bold "  installing via Homebrew"
            brew install apkeep && exit 0 || red "  brew install failed, falling back to cargo"
        fi
        ;;
    Linux)
        # Some distros package apkeep; otherwise cargo handles it.
        if command -v apt-get >/dev/null 2>&1; then
            note "  apt doesn't ship apkeep — we'll use cargo. (Skipping apt path.)"
        fi
        ;;
esac

if ! command -v cargo >/dev/null 2>&1; then
    red "✕ cargo not found. Install rustup from https://rustup.rs and re-run."
    exit 1
fi

bold "  installing via cargo (~3 min on a warm cache)"
cargo install apkeep

# Sanity check: where did it land?
if ! command -v apkeep >/dev/null 2>&1; then
    red "✕ apkeep binary not on PATH after install."
    note "  Make sure \$HOME/.cargo/bin is in your PATH and re-run /doctor."
    exit 1
fi

green "  ✓ apkeep $(apkeep --version 2>&1 | tail -1)"
echo
bold "  next:"
note "    1. seed credentials at ~/.config/apkeep/apkeep.ini (email + aas_token)"
note "       — see https://github.com/EFForg/apkeep#google-play"
note "    2. /apk-fetch <package> [--source aurora|google-play|f-droid|apkpure|huawei-appgallery]"
note "    3. confirm health: mnexus doctor"
