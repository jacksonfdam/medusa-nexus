# MEDUSA NEXUS — Design Index

Source of truth: [`medusanexus.pen`](medusanexus.pen) — open in Pencil to edit.

Every screen is also exported as a PNG under `screens/<group>/`. Hero screens are fully composed; screens tagged *stub* are intentionally wireframe-level — the spec is in [`../docs-site/content/design/spec.mdx`](../docs-site/content/design/spec.mdx) and they'll land at full fidelity in iteration 2.

All on-screen copy is English. Every finding card and every report template carries a **Mitigation Playbook** — non-negotiable.

---

## Group 0 — Boot

| # | Screen | Fidelity | File |
|---|---|---|---|
| 00 | Boot / Splash | hero | [00-boot.png](screens/group-0-boot/00-boot.png) |

## Group 1 — App Shell

| # | Screen | Fidelity | File |
|---|---|---|---|
| 01 | Dashboard / Home | hero | [01-dashboard.png](screens/group-1-shell/01-dashboard.png) |
| 02 | Projects List | stub | [02-projects-list.png](screens/group-1-shell/02-projects-list.png) |

## Group 2 — Intake

| # | Screen | Fidelity | File |
|---|---|---|---|
| 03 | APK Intake / Drag & Drop | hero | [03-apk-intake.png](screens/group-2-intake/03-apk-intake.png) |
| 05 | Pull from Device | hero | [05-pull-from-device.png](screens/group-2-intake/05-pull-from-device.png) |
| 06 | Device Bridge | stub | [06-device-bridge.png](screens/group-2-intake/06-device-bridge.png) |

*(04 merged into 06 — single device page covers list + bridge.)*

## Group 3 — Project Workspace

Tabs in the workspace: **Overview · Static · Dynamic · Network · Report**.

| # | Screen | Fidelity | File |
|---|---|---|---|
| 07 | Overview (risk gauge + timeline) | hero | [07-overview.png](screens/group-3-workspace/07-overview.png) |
| 08 | Static Analysis | hero | [08-static-analysis.png](screens/group-3-workspace/08-static-analysis.png) |
| 09 | Secrets & Crypto Audit | stub | [09-secrets-crypto.png](screens/group-3-workspace/09-secrets-crypto.png) |
| 10 | Components & Deep Links | stub | [10-components-deeplinks.png](screens/group-3-workspace/10-components-deeplinks.png) |
| 11 | Native Analysis (Ghidra) | stub | [11-native-ghidra.png](screens/group-3-workspace/11-native-ghidra.png) |
| 12 | Dynamic Analysis (Frida console) | hero | [12-dynamic-analysis.png](screens/group-3-workspace/12-dynamic-analysis.png) |
| 13 | Live Method Tracer | stub | [13-live-tracer.png](screens/group-3-workspace/13-live-tracer.png) |
| 14 | Network Analysis | hero | [14-network-analysis.png](screens/group-3-workspace/14-network-analysis.png) |
| 15 | API Endpoint Map | stub | [15-api-map.png](screens/group-3-workspace/15-api-map.png) |
| 16 | SSL Pinning Map | stub | [16-ssl-pinning-map.png](screens/group-3-workspace/16-ssl-pinning-map.png) |

## Group 4 — Visualizers

| # | Screen | Fidelity | File |
|---|---|---|---|
| 17 | Attack Surface Graph | stub | [17-attack-surface-graph.png](screens/group-4-visualizers/17-attack-surface-graph.png) |
| 18 | Data Flow Diagram | stub | [18-data-flow-diagram.png](screens/group-4-visualizers/18-data-flow-diagram.png) |
| 19 | Attack Tree | stub | [19-attack-tree.png](screens/group-4-visualizers/19-attack-tree.png) |
| 20 | OWASP MASVS Matrix | hero | [20-owasp-masvs-matrix.png](screens/group-4-visualizers/20-owasp-masvs-matrix.png) |

## Group 5 — Finding & Report

| # | Screen | Fidelity | File |
|---|---|---|---|
| 21 | Finding Detail drawer | hero | [21-finding-detail.png](screens/group-5-finding-report/21-finding-detail.png) |
| 22 | Report Generator | hero | [22-report-generator.png](screens/group-5-finding-report/22-report-generator.png) |
| 23 | Diff Report | stub | [23-diff-report.png](screens/group-5-finding-report/23-diff-report.png) |

The Finding Detail drawer and the Report Generator both render a **Mitigation** block as a first-class section. No finding ships without remediation guidance.

## Group 6 — Automation & Config

| # | Screen | Fidelity | File |
|---|---|---|---|
| 24 | Pipeline Editor | stub | [24-pipeline-editor.png](screens/group-6-automation/24-pipeline-editor.png) |
| 25 | Recipes Library | hero | [25-recipes-library.png](screens/group-6-automation/25-recipes-library.png) |
| 26 | Tools / Doctor | hero | [26-tools-doctor.png](screens/group-6-automation/26-tools-doctor.png) |
| 27 | Settings | stub | [27-settings.png](screens/group-6-automation/27-settings.png) |
| 28 | Terminal / CLI Console | stub | [28-terminal-console.png](screens/group-6-automation/28-terminal-console.png) |

## Group 7 — Auxiliary States

| # | Screen | Fidelity | File |
|---|---|---|---|
| 29 | Empty / Error states | stub | [29-empty-error-states.png](screens/group-7-states/29-empty-error-states.png) |
| 30 | Toast Stack | stub | [30-toast-stack.png](screens/group-7-states/30-toast-stack.png) |
| 31 | About / Credits | hero | [31-about-credits.png](screens/group-7-states/31-about-credits.png) |

---

## Design System

Tokens and reusable components live in the same `.pen` file at `x<0` (off-canvas, to the left of the screen grid).

**Color tokens** — `bg/base`, `bg/panel`, `bg/accent-panel`, `primary/cyan`, `accent/acid`, `secondary/magenta`, `border/default|hover|accent`, `muted/cyan`, `severity/critical|high|medium|low|info`, `scanline`.

**Typography** — Courier Prime primary, Rye for rare display. Scale: 57/40/32/24/20/16/14/13/11, ASCII letter 72 with `letter-spacing: -4`.

**Reusable components**:

- `cmp/Panel`
- `cmp/Button/{Primary, Secondary, Destructive}`
- `cmp/Status/{Online, Offline, Scanning}`
- `cmp/Chip/{CRIT, HIGH, MED, LOW, INFO}`
- `cmp/DataRow`
- `cmp/Input`
- `cmp/Tab/{Active, Idle}`
- `cmp/HexDivider`
- `cmp/FindingCard` — header + Evidence + **Mitigation** (accent-bordered, always visible)
- `cmp/SidebarItem` / `cmp/SidebarItemActive`
- `cmp/AsciiHeader` — large single letter + gradient underline
- `cmp/RiskGauge` — circular 0–100 arc

Effects specified in [`../docs-site/content/design/design-language.mdx`](../docs-site/content/design/design-language.mdx) — glitch, scanlines, CRT flicker, neon glow, chaos text, pulse opacity.

---

## Fidelity legend

- **hero** — composed with production-ready content, components, copy, and severity chips. Ready to translate to code.
- **stub** — labeled wireframe with header + title + feature description. Defines the intent; full layout lands in the next iteration.

The spec driving every screen is in [`../docs-site/content/design/spec.mdx`](../docs-site/content/design/spec.mdx). Author credits: [`../CREDITS.md`](../CREDITS.md).
