"""Deeplink + exported-activity probe — generates a runnable bash script.

Given a `Project`, produce a `bash` file that walks every recovered deep
link and every exported activity and fires `adb shell am start` against
the connected device. Useful for:

  * confirming the manifest declarations actually resolve to a handler;
  * spotting deep links that crash the app (intent fuzzing 101);
  * mass-screenshotting first-render output for triage.

The script is self-contained — it doesn't depend on Nexus running, just
needs `adb` on PATH and a device authorised. Each invocation is wrapped
in a small banner so the operator can scroll the terminal output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from mnexus.models.project import Project


def to_deeplink_script(project: Project, *, screenshot: bool = True, delay_s: float = 1.5) -> str:
    surface = project.attack_surface
    deeplinks = list(dict.fromkeys((surface.deeplinks if surface else []) or []))

    activities = []
    if surface:
        for comp in surface.exported_components:
            if comp.component_type == "activity":
                activities.append(comp.name)

    pkg = project.package_name
    when = datetime.now(UTC).isoformat()

    lines: list[str] = [
        "#!/usr/bin/env bash",
        "#",
        f"# MEDUSA NEXUS · deeplink + exported-activity probe",
        f"# project : {project.id}",
        f"# package : {pkg}",
        f"# version : {project.version_name}",
        f"# platform: {project.platform}",
        f"# generated: {when}",
        "#",
        "# Requires: adb on PATH, a device with USB debugging authorised, the",
        "# app installed (mnexus serve --install or `adb install …`).",
        "#",
        "# Usage:  bash deeplink-probe.sh           # run all probes",
        "#         DRY_RUN=1 bash deeplink-probe.sh # print commands without firing them",
        "#         FILTER='auth' bash deeplink-probe.sh   # only probes whose URI contains 'auth'",
        "",
        "set -uo pipefail",
        "",
        f'PKG="{pkg}"',
        f'DELAY={delay_s}',
        f'SCREENSHOT={"1" if screenshot else "0"}',
        f'OUT_DIR="{project.id}-deeplink-probe-$(date +%Y%m%d-%H%M%S)"',
        'DRY_RUN="${DRY_RUN:-0}"',
        'FILTER="${FILTER:-}"',
        "",
        '[[ "$DRY_RUN" == "1" ]] || mkdir -p "$OUT_DIR"',
        "",
        "_banner() {",
        '  printf "\\n\\033[1;36m🔱 %s\\033[0m\\n" "$1"',
        "}",
        "",
        "_probe() {",
        '  local kind="$1"; local target="$2"; local idx="$3"',
        '  if [[ -n "$FILTER" && "$target" != *"$FILTER"* ]]; then return 0; fi',
        '  _banner "[$idx] $kind :: $target"',
        '  local cmd',
        '  if [[ "$kind" == "deeplink" ]]; then',
        '    cmd="adb shell am start -W -a android.intent.action.VIEW -d \\"$target\\" \\"$PKG\\""',
        '  else',
        '    cmd="adb shell am start -W -n \\"$PKG/$target\\""',
        '  fi',
        '  printf "  $ %s\\n" "$cmd"',
        '  if [[ "$DRY_RUN" == "1" ]]; then return 0; fi',
        '  eval "$cmd" || printf "    \\033[31m✕ start failed\\033[0m\\n"',
        '  sleep "$DELAY"',
        '  if [[ "$SCREENSHOT" == "1" ]]; then',
        '    local safe',
        '    safe=$(printf "%s" "$target" | tr "/:?&=" "_____" | cut -c -80)',
        '    adb exec-out screencap -p > "$OUT_DIR/${idx}-${kind}-${safe}.png" 2>/dev/null || true',
        '  fi',
        "}",
        "",
        "# ─── deeplinks ──────────────────────────────────────────────────────",
    ]

    if deeplinks:
        for i, link in enumerate(deeplinks, start=1):
            # Bash needs single quotes that escape internal single-quotes;
            # we sidestep with double-quotes since URIs don't normally contain them.
            safe = link.replace('"', '\\"')
            lines.append(f'_probe deeplink "{safe}" {i:03d}')
    else:
        lines.append("# (no deeplinks recovered)")

    lines.append("")
    lines.append("# ─── exported activities ───────────────────────────────────────────")
    if activities:
        for i, act in enumerate(activities, start=1):
            lines.append(f'_probe activity "{act}" A{i:03d}')
    else:
        lines.append("# (no exported activities recovered)")

    lines.append("")
    lines.append("_banner \"done · $OUT_DIR\"")
    lines.append("")
    return "\n".join(lines)
