---
title: "Let your AI assistant run the security review — MCP for mobile audits"
description: "Wire MedusaNexus into Claude Desktop, Cursor, or Zed via the Model Context Protocol and let an AI assistant drive the analysis end to end — scan, enumerate, correlate, recommend."
published: 2026-07-21
author: Jackson Mafra
tags: ["mobile-security", "ai", "mcp", "claude", "developers"]
canonical: https://mnexus.vercel.app/articles/07-ai-assistant-mobile-security-review
codex_refs:
  - "Trust No One — https://medium.com/@jacksonfdam/"
  - "Hackers Need Hobbies — https://medium.com/@jacksonfdam/"
medusa_refs:
  - https://github.com/jacksonfdam/medusa-nexus
tldr: |
  Model Context Protocol is the cable between AI assistants and the tools they can drive.
  MedusaNexus ships an MCP server that exposes ten tools — read-only by default — letting
  Claude Desktop, Cursor, or Zed enumerate findings, fetch evidence, run the chain
  correlator, and propose remediations in natural language. Three write tools (scan_apk,
  run_pipeline, analyze_native_lib) extend the loop end to end. The line between
  inspection and mutation stays explicit on purpose.
---

The previous six articles assumed the human is the one driving the analysis — running the CLI, reading the findings panel, walking the web UI, writing the report. This one inverts that. The Model Context Protocol — MCP — is the standard that lets an AI assistant drive tools the same way a human would, calling discrete operations, reading the results, and synthesizing the next step. For mobile security work, that turns out to be a particularly good fit. The audit workflow is mostly *read findings, fetch evidence, propose remediation*, and that's the loop MCP excels at.

This article walks through what MCP is, why it matters for security work specifically, how to wire MedusaNexus into the three major AI clients (Claude Desktop, Cursor, Zed), and what's possible — and deliberately impossible — through the AI loop today.

## What MCP is, in one paragraph

MCP is an open protocol — published by Anthropic in late 2024, since adopted by every major AI client — that defines how AI assistants discover and invoke external tools. The protocol is JSON-RPC 2.0 over stdio (or HTTP, depending on transport), with a defined handshake (`initialize`, `tools/list`, `tools/call`, `notifications/initialized`), defined error codes, and defined message shapes. A server implementing MCP advertises a list of tools, each with a name, description, and JSON Schema for inputs. The AI assistant reads the catalogue, decides which tool to call based on the user's request, supplies the arguments, and reads the result.

The architectural shift MCP enables is that AI assistants are no longer limited to text generation — they can drive *real systems*, with concrete side effects, mediated by tools that expose only the operations the tool's author chose to expose. The AI doesn't ssh into your machine; it calls `list_findings(project_id="PRJ-…")` and reads what the tool returns.

For security work, that bounded vocabulary is the whole point. You don't want the assistant running arbitrary commands on your laptop. You want it calling specific, audited operations with structured outputs.

## Why MCP fits mobile security audits

A mobile security audit is mostly a question-and-answer loop. *What activities are exported? What deeplinks do they handle? Which findings are CRITICAL? What's the evidence for finding FND-7B22A91C? What's the remediation? Are any of these findings new vs the last release?* Every one of those questions has a precise answer that the audit tool already knows.

In a manual audit, the human runs the queries and synthesizes the narrative. The synthesis is where most of the time goes — not because the queries are hard, but because there are dozens of them per audit and the analyst is the bottleneck.

The MCP loop changes that. The analyst describes the audit *intent* — "summarize the CRITICAL findings on this project and propose a remediation order" — and the assistant runs the queries, fetches the evidence, cross-references the findings, and produces the synthesis. The audit doesn't get less rigorous; the rigor shifts from the data-fetching phase (which an LLM does well) to the synthesis and judgement phases (which a human still does better, but starting from much richer context).

For a developer who isn't a full-time security analyst, the loop is even more valuable. The vocabulary from article 2 is built in to the assistant's prompt: it knows what *intent-filter*, *deeplink*, *MASVS*, *remediation* mean. The assistant translates between security-speak and developer-speak in both directions.

## The tools MedusaNexus exposes

The MCP server in MedusaNexus (`mnexus/mcp_server.py`) advertises ten tools today. Seven are read-only; three are read-write. The split is intentional.

### Read-only tools (always available)

| Tool | What it does |
| ---- | ------------ |
| `list_projects` | Every Project in the workspace with risk scores and finding counts. |
| `get_project` | One project's full overview: risk score, severity counts, attack surface summary. |
| `list_findings` | Findings for a project, filtered by severity / category. |
| `get_finding` | Fetch one finding by id including evidence and remediation. |
| `list_recipes` | Browse the built-in + Medusa recipe catalogue. |
| `decode_android_flag` | Decode an Android Intent / Receiver flag integer into symbolic names. |
| `manifest_diff` | Diff a project's static surface against a prior scan. |
| `findings_diff` | Diff a project's findings against a prior scan. |
| `firebase_probe` | Run RTDB / Firestore / Storage probes against a Firebase config (standalone, no project). |
| `doctor` | Engine health check — which engines are installed and reachable. |

These cover the entire read path of the audit. With just these, an assistant can describe the surface, walk the findings, correlate evidence, diff against prior scans, and propose remediations. It cannot trigger a new scan, cannot patch the APK, cannot start a Frida session.

### Write tools (opt-in, recently added)

| Tool | What it does |
| ---- | ------------ |
| `scan_apk` | Upload an APK and run the full static pipeline. Returns the new project_id. Blocking call (~30-60s). |
| `run_pipeline` | Execute a named pipeline against an existing project. |
| `analyze_native_lib` | Run Ghidra headless against a specific `.so` in a project. |

These three close the loop end to end. With them, the assistant can take an APK path from the user, scan it, run the full chain correlator, fetch the resulting findings, and produce the audit. The blast radius is bounded — none of these mutate the device, re-sign binaries, or fire active network probes without explicit confirmation.

### Tools deliberately not exposed (today)

* `start_dynamic_session` — boots a Frida session against a connected device. Mutates device state.
* `patch_apk` / `patch_ipa` — re-signs the binary. Mutates artefact.
* `decrypt_ios` — drives `bagbak` / `frida-ios-dump` against a jailbroken iPhone. Mutates device state.
* `execute_burp_probe_plan` — fires HTTP traffic against the target's backend. Touches third-party infrastructure.

These could be exposed. The decision not to today is conservative: every one of them has side effects an audit-style AI loop shouldn't trigger without an explicit human in the loop. The line moves over time; the design pattern is that *each new write tool requires an explicit opt-in step in the audit flow*.

## Wiring MCP into Claude Desktop

The canonical mobile MCP client is Claude Desktop. Configuration lives at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%/Claude/claude_desktop_config.json` on Windows, `~/.config/Claude/claude_desktop_config.json` on Linux. Add an entry under `mcpServers`:

```json
{
  "mcpServers": {
    "medusa-nexus": {
      "command": "mnexus",
      "args": ["mcp-serve"],
      "env": {
        "MNEXUS_API_BASE": "http://127.0.0.1:8765"
      }
    }
  }
}
```

Restart Claude Desktop. The hammer icon next to the prompt input should now list ten `medusa-nexus` tools (or thirteen if the write tools are enabled in your build). The `MNEXUS_API_BASE` environment variable points the MCP driver at the local FastAPI server; if you run MedusaNexus on a remote host, change the URL to match.

The MCP server itself runs as `mnexus mcp-serve` — a stdio-based server that speaks JSON-RPC. Behind the scenes it makes HTTP calls to the local Nexus FastAPI server, which means *the Nexus server must be running* (`mnexus serve` in a terminal) before the assistant can call anything.

## The first MCP-driven audit

With the wiring in place, an audit looks like a conversation:

> **You:** Scan `~/Downloads/competitor-app.apk`, then summarize the CRITICAL findings and propose a remediation order.

The assistant's loop, in slow motion:

1. Calls `scan_apk(apk_path="~/Downloads/competitor-app.apk")`. Receives back `{"project_id": "PRJ-A5B7C291", "status": "complete"}` after ~30 seconds of static analysis.
2. Calls `get_project(project_id="PRJ-A5B7C291")`. Receives the surface summary — risk score, severity counts, component counts.
3. Calls `list_findings(project_id="PRJ-A5B7C291", severity="critical")`. Receives an array of finding objects, each with id, title, severity, category, source_engine.
4. Calls `get_finding(finding_id="FND-CHAIN001")` for each CRITICAL finding. Receives the full body: description, evidence, remediation, MASVS control, contributing findings (for chain findings).
5. Synthesises: "I found 3 CRITICAL findings on PRJ-A5B7C291 (risk score 78). The most impactful is FND-CHAIN001, a 1-click ATO chain composed of 5 contributing findings: ..."

That five-step loop, end to end, takes about 90 seconds. The assistant's narrative output is the audit summary. The intermediate tool calls and responses are inspectable in Claude Desktop's tool-use panel if you want to verify the assistant didn't hallucinate.

The same workflow with Cursor or Zed is structurally identical — the configuration files are different (`~/.cursor/mcp.json`, `~/.config/zed/mcp.json`), the UI is different, but the tool catalogue and the loop are the same.

## Prompts that work

A few patterns that produce useful audit output:

**Survey mode.** *"List every project in the workspace. Sort by risk score descending. For the top three, tell me the package name, version, total finding count, and CRITICAL finding count."*

The assistant calls `list_projects`, sorts the response client-side, then for each of the top three calls `get_project` and `list_findings(severity="critical")`. Output is a tight comparison table.

**Diff mode.** *"PRJ-A5B7C291 is the new build, PRJ-OLD12345 is the previous release. What got worse?"*

The assistant calls `findings_diff(project_id="PRJ-A5B7C291", against="PRJ-OLD12345")`, gets back `{added, removed, changed}`. Reports the deltas in natural language, including which CRITICAL findings are new.

**Walk-the-chain mode.** *"Tell me everything about FND-CHAIN001 — the contributing findings, the evidence, the proposed fix for each link."*

The assistant calls `get_finding(finding_id="FND-CHAIN001")`. The chain finding's body lists contributing finding ids; the assistant calls `get_finding` for each one in parallel. The result is a layered narrative: chain → links → per-link evidence → per-link remediation.

**Compliance mode.** *"Map every finding on PRJ-A5B7C291 to its MASVS control. Tell me which MASVS categories are clean and which have at least one violation."*

The assistant calls `list_findings(project_id="PRJ-A5B7C291")`, groups by the `masvs` field on each finding, and produces the matrix. Same data the web UI's OWASP tab shows — but with the assistant's prose synthesis.

**Decode-flag mode.** *"What does Intent flag `0x10000000` mean?"*

The assistant calls `decode_android_flag(value="0x10000000")`. Receives back the symbolic decomposition (FLAG_GRANT_READ_URI_PERMISSION, FLAG_ACTIVITY_NEW_TASK, etc.) across the relevant namespaces and reports.

## Where the loop genuinely shines

The pattern that surprises developers most often is the *cross-finding synthesis*. A typical audit produces 40-100 findings; reading them individually is slow; reading them grouped by category is faster but loses the chain context. The MCP loop produces *narrative groupings* the assistant decides on dynamically:

> "The app's biggest risk surface is the WebView subsystem. I found 7 WebView-related findings (3 HIGH, 4 MEDIUM) that collectively form a credential-exfiltration primitive. The single highest-leverage fix is on FND-3F4B1290 — adding a host allowlist to AccountHubActivity — which breaks the 1-click ATO chain *and* the alternate path through SettingsWebView *and* removes the need to fix FND-AA12F45E and FND-D17E0066 individually."

That synthesis would take a human analyst 20 minutes of cross-referencing. The assistant produces it in 30 seconds because it can hold the full finding set in context and the chain correlator already pre-computed the inter-finding relationships.

The other pattern that pays off quickly: *"explain this finding for a developer who's never read a security report."* The assistant has the precise vocabulary from article 2 built into its training and the MASVS taxonomy in the finding's metadata. It translates between the formal language of the finding and the informal language of the engineer reading it, without losing rigor.

## Where the loop deliberately doesn't go

A few patterns the loop refuses today:

* **No automatic patching.** The assistant cannot call `patch_apk` because that tool isn't exposed. If you want to apply the remediation the assistant proposed, you copy the fix into your codebase or apply it via the REPL — but the *assistant doesn't touch your artefacts*.
* **No live device hooks.** No `start_dynamic_session`. If the assistant proposes a Frida hook to validate a static finding, you load it manually. The reason: a Frida session has side effects on the device that an AI loop shouldn't trigger without confirmation.
* **No active network probes against the target's infrastructure.** The Firebase probe tool *is* exposed, because it's a known-safe pattern (read-only, scoped to the configs the static scan already extracted). The Burp probe-plan executor, which fires actual HTTP traffic against the target's backend, is not exposed — too easy to violate scope.
* **No write to the codebase.** The MCP server doesn't touch your source files. If you want the assistant to write a patch, that's a different MCP server (e.g., the local-files-edit server) — and the security-of-its-own discussion is a different article.

The general principle: read-only tools are always safe; write tools are scoped to read-only side effects (a new project, a new analysis result); side-effect tools are not in the audit loop.

## Operational pitfalls

* **The MCP server is stateless; the Nexus server is stateful.** The MCP driver makes fresh HTTP calls per tool invocation. State (which projects exist, which findings have been viewed) lives in the Nexus server's SQLite. If the Nexus server isn't running, every MCP call fails.
* **MCP catalogue refresh requires restart.** When you add a new tool to `mnexus/mcp_server.py` and restart `mnexus mcp-serve`, the AI client doesn't automatically see the new tool — you have to restart the client too. Annoying but operationally trivial.
* **Tool outputs are truncated.** MCP responses have a practical size limit (~60KB for Claude Desktop). For very large finding sets, the assistant has to paginate via `list_findings(severity="…")` calls. The MCP driver pre-truncates aggressively to stay under the limit; the loss is fidelity but never structural.
* **Authentication doesn't exist for local MCP.** The MCP server speaks to whoever connects to its stdio. On a single-user laptop this is fine; for shared infrastructure, route MCP through a stricter access boundary.

## TL;DR

MCP turns AI assistants into audit drivers — they call structured operations on your security tools, read the results, and synthesize the narrative. MedusaNexus's MCP server exposes ten tools today (seven read-only, three write), covering the full audit read path and the static-scan-trigger path. The line between read-only inspection and write-side mutation stays explicit by design: nothing on the AI loop today touches devices, patches binaries, or fires active probes against the target's backend without an explicit human-in-the-loop step.

For a developer doing security work, the leverage is genuinely high. The vocabulary from article 2 is built into the assistant. The chain correlator from article 5 produces narrative output. The CI gate from article 6 hands its summary into the same AI loop for prose commentary. Audits go from *hours of cross-referencing* to *minutes of synthesis driven by the assistant on the data the platform already had*.

> The most useful thing an AI assistant does in security work is not generate exploit code. It's read a hundred findings, group them by chain, and tell you the three changes that fix the most of them at once. MCP is the cable that makes that loop possible. The tools at the other end of the cable are what make it precise.

---

**Next in the series →** *iOS without a jailbroken iPhone — what's possible and what isn't.* The closing article. Static-only iOS workflow, the FairPlay encryption gap, what `bagbak` / `ldid` / `super-tart-vphone` unlock, and when you genuinely need physical hardware vs when you don't.

---

*The series continues weekly on [Medium](https://medium.com/@jacksonfdam/). For the broader picture of AI in security work — `Trust No One`, `Hackers Need Hobbies` — see the Codex at [Umain Fortress](https://umain-fortress.vercel.app/).*
