#!/usr/bin/env bash
#
# scripts/micro-commits.sh — split the current uncommitted backlog into
# focused, thematic commits. Run once from the repo root.
#
# The sandbox couldn't reliably acquire .git/index.lock through the FUSE
# mount, so this script lives in-tree and runs natively from your shell.
# Each commit is reviewable on its own; stop at any point with Ctrl-C and
# the rest of the changes stay in your working tree.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

green() { printf "\033[32m%s\033[0m\n" "$*"; }
say() { printf "\n\033[1;36m🔱 %s\033[0m\n" "$*"; }

# Bail out early if the working tree is clean.
if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    green "  nothing to commit — working tree is clean"
    exit 0
fi

commit() {
    local msg="$1"; shift
    git add "$@"
    if git diff --cached --quiet; then
        printf "  · skipped (no staged changes for: %s)\n" "$msg"
        return
    fi
    git commit -m "$msg" >/dev/null
    printf "  ✓ %s\n" "$msg"
}

# ─── Wave 1 — iOS support ────────────────────────────────────────────────

say "iOS Wave 1"

commit "feat(models): iOS-aware data model — Project.platform, AttackSurface entitlements/url_schemes/ATS/provisioning, Finding.platform_hint" \
    mnexus/models/project.py \
    mnexus/models/attack_surface.py \
    mnexus/models/finding.py

commit "feat(core): SQLite migration — add 'platform' column to projects, default 'android'" \
    mnexus/core/artifact_store.py

commit "feat(engines): IPAToolEngine — built-in IPA + AXML/plist/provisioning parser, no external apktool/plistutil" \
    mnexus/engines/ipatool_engine.py \
    mnexus/engines/__init__.py

commit "feat(engines): GhidraEngine — autodetect ELF/Mach-O, scan iOS-flavoured patterns (CommonCrypto, kSec*, NSLog secrets, PT_DENY_ATTACH, jb paths)" \
    mnexus/engines/ghidra_engine.py

commit "feat(intelligence): platform-aware HookGenerator — iOS templates (jb bypass, SSL kill switch, keychain dump, CommonCrypto logger)" \
    mnexus/intelligence/hook_generator.py

commit "feat(core): orchestrator ingest() dispatcher + _ingest_ipa pipeline (ipatool + mobsf + ghidra)" \
    mnexus/core/orchestrator.py

commit "feat(recipes): built-in Frida recipes — ios_ssl_kill_switch, ios_jailbreak_bypass, ios_keychain_dump, cipher_key_leak" \
    mnexus/recipes/__init__.py \
    mnexus/recipes/builtin.py

# ─── Theme switcher (split from the rest of api/static + main.py) ───────

say "Theme switcher (Nexus / Dracula)"

# main.py + app.js + app.css + index.html each have BOTH iOS-related and
# theme-related changes; we commit them together as "feat(ui): iOS upload
# + theme switcher" because git add -p is too brittle for hunks this big.

commit "feat(api): /v1/ipas/upload + auto-detect platform + recipes platform filter + hooks/rescan platform-aware + asset version + no-cache static middleware" \
    mnexus/api/main.py

commit "feat(ui): iOS frontend (.ipa upload, platform glyph, iOS labels, recipes platform filter) + theme switcher (Nexus + Dracula, Settings UI, pre-paint apply)" \
    mnexus/api/static/app.js \
    mnexus/api/static/app.css \
    mnexus/api/templates/index.html

commit "test(ios): e2e — synthetic IPA → upload → assert findings + attack surface + every subview + rescan + iOS-flavoured hooks" \
    tests/test_ipa_ingest_e2e.py

# ─── VPhone (super-tart-vphone) — Wave 1 + Wave 2 ────────────────────────

say "VPhone integration (super-tart-vphone)"

commit "docs(vphone): integration plan — 4 waves, what we automate vs what we don't, security/legal posture" \
    docs/VPHONE_PLAN.md

commit "feat(scripts): setup-vphone.sh — Apple-Silicon prereq check, SIP/AMFI status report, clone+build super-tart, env-file wire (idempotent, --check, --rebuild, --uninstall)" \
    scripts/setup-vphone.sh

commit "feat(config): NexusConfig — vphone_path + tart_bin (read from MNEXUS_* env)" \
    mnexus/config.py

commit "feat(engines): VPhoneEngine — full lifecycle wrapper around super-tart (list/start/stop/ssh/scp/install_ipa/screenshot) with optional audit-log recorder hook" \
    mnexus/engines/vphone_engine.py \
    mnexus/engines/__init__.py \
    mnexus/core/orchestrator.py

commit "feat(api): /v1/vphones/* REST surface + transport-aware audit log (adb/vphone rows in the same /v1/adb/log buffer)" \
    mnexus/api/main.py

commit "test(vphone): unit tests for VPhoneEngine helpers — table parser, normalize, _resolve_tart_bin, doctor with shell-stub binary" \
    tests/test_vphone_engine.py

commit "test(vphone): /v1/vphones/* API contracts — graceful 200/503/422/501 paths + audit-log row carries transport='vphone'" \
    tests/test_vphone_api.py

commit "feat(cli): /vphone slash command + flat \`mnexus vphone\` subcommand — list/info/start/stop/ssh/install/status, same shape in REPL and one-shot" \
    mnexus/cli.py

commit "docs(readme): VPhone lab — research-only opt-in section under Setup flags, links VPHONE_PLAN + upstream GUIDE.md" \
    README.md

# ─── Done ────────────────────────────────────────────────────────────────

green "
all done. recent commits:"
git log --oneline -16
