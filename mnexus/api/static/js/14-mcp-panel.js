// ── auto-wired ES-module imports ──
import { $, escapeHtml, fmtAgo, h, pollingScope, sectionHeader } from "./01-core.js";

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN — MCP control plane
 *
 *  Decide which tools the stdio MCP driver may expose to an AI assistant,
 *  copy the paste-ready setup for each client, and watch a live connection
 *  dot. The driver is a process the *agent* spawns, so this panel governs
 *  what it's ALLOWED to do — not whether it's running.
 * ═══════════════════════════════════════════════════════════════════════════ */

const GROUP_META = {
    read:  { label: "READ",  hint: "inspect the workspace",       color: "var(--cyan)" },
    nav:   { label: "NAV",   hint: "read the decompiled source",  color: "var(--acid)" },
    write: { label: "WRITE", hint: "mutate state / run pipelines", color: "var(--magenta)" },
};
const AGENTS = [
    { id: "claude", name: "Claude Desktop" },
    { id: "cursor", name: "Cursor" },
    { id: "zed",    name: "Zed" },
];

function view_mcp() {
    return h`
    <div class="main">
      ${sectionHeader("M", "28 // SHELL", "MCP CONTROL PLANE")}

      <section class="panel accent">
        <div class="panel-head" style="color:var(--acid)">// DRIVER STATUS</div>
        <div class="panel-body col" id="mcp-status">
          <div class="muted small">probing…</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">// MASTER SWITCH</div>
        <div class="panel-body">
          <label class="row" style="gap:12px;align-items:center;cursor:pointer">
            <input type="checkbox" id="mcp-enabled" style="accent-color:var(--acid);width:18px;height:18px">
            <span class="col" style="gap:2px">
              <span class="t-mono" style="letter-spacing:2px">MCP ENABLED</span>
              <span class="muted small">Off = the driver exposes nothing, every tool call refused.</span>
            </span>
          </label>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          // ALLOWED TOOLS
          <span class="row" style="float:right;gap:8px">
            <button class="btn small" id="mcp-allow-all">[ ALLOW ALL ]</button>
            <button class="btn small" id="mcp-block-all">[ BLOCK ALL ]</button>
          </span>
        </div>
        <div class="panel-body col" id="mcp-tools">
          <div class="muted small">loading catalogue…</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">// AGENT SETUP</div>
        <div class="panel-body col" id="mcp-setup">
          <div class="muted small">building snippets…</div>
        </div>
      </section>
    </div>`;
}

/* ─── data plumbing ─── */

async function fetchConfig() {
    const r = await fetch("/v1/mcp/config", { cache: "no-store" });
    if (!r.ok) throw new Error(`config ${r.status}`);
    return r.json();
}

async function putConfig(body) {
    const r = await fetch("/v1/mcp/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`put ${r.status}`);
    return r.json();
}

/* ─── renderers ─── */

function renderStatus(status) {
    const el = $("#mcp-status");
    if (!el) return;
    const connected = !!status.connected;
    const dot = `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;
        background:${connected ? "var(--acid)" : "var(--muted)"};
        box-shadow:${connected ? "0 0 8px var(--acid)" : "none"}"></span>`;
    const seen = status.last_seen_ts
        ? `last seen ${fmtAgo(new Date(status.last_seen_ts * 1000).toISOString())}`
        : "no driver has connected yet";
    const who = status.client ? ` · <code>${escapeHtml(status.client)}</code>` : "";
    el.innerHTML = `
      <div class="row" style="gap:10px;align-items:center">
        ${dot}
        <span class="t-mono" style="letter-spacing:2px;color:${connected ? "var(--acid)" : "var(--muted)"}">
          ${connected ? "DRIVER CONNECTED" : "IDLE"}
        </span>
        <span class="muted small">${seen}${who}</span>
      </div>
      <div class="row" style="gap:10px;align-items:center">
        <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--acid);box-shadow:0 0 8px var(--acid)"></span>
        <span class="muted small">API reachable</span>
      </div>`;
}

function renderTools(cfg) {
    const el = $("#mcp-tools");
    if (!el) return;
    const byGroup = { read: [], nav: [], write: [] };
    for (const t of cfg.tools) (byGroup[t.group] || byGroup.read).push(t);

    el.innerHTML = ["read", "nav", "write"].map((g) => {
        const meta = GROUP_META[g];
        const rows = byGroup[g].map((t) => `
          <label class="row mcp-tool" style="gap:10px;align-items:flex-start;cursor:pointer;padding:4px 0">
            <input type="checkbox" data-tool="${t.name}" ${t.enabled ? "checked" : ""}
                   ${cfg.enabled ? "" : "disabled"} style="accent-color:${meta.color};margin-top:3px">
            <span class="col" style="gap:1px;flex:1;min-width:0">
              <span class="row" style="gap:8px;align-items:center">
                <code style="color:${t.enabled ? meta.color : "var(--muted)"}">${t.name}</code>
                <span class="muted small">${escapeHtml(t.route || "")}</span>
              </span>
              <span class="muted small">${escapeHtml((t.description || "").slice(0, 130))}</span>
            </span>
          </label>`).join("");
        return `
          <div class="col" style="gap:2px;margin-bottom:10px">
            <div class="row" style="gap:8px;align-items:baseline">
              <span class="t-mono" style="color:${meta.color};letter-spacing:2px">${meta.label}</span>
              <span class="muted small">${meta.hint}</span>
            </div>
            ${rows}
          </div>`;
    }).join("");
}

async function renderSetup() {
    const el = $("#mcp-setup");
    if (!el) return;
    const blocks = await Promise.all(AGENTS.map(async (a) => {
        let snip;
        try {
            const r = await fetch(`/v1/mcp/setup/${a.id}`, { cache: "no-store" });
            snip = await r.json();
        } catch (_) {
            return `<div class="muted small">${a.name}: unavailable</div>`;
        }
        return `
          <div class="col" style="gap:4px;margin-bottom:12px">
            <div class="row" style="gap:10px;align-items:center">
              <span class="t-mono" style="color:var(--cyan);letter-spacing:2px">${a.name}</span>
              <button class="btn small mcp-copy" data-copy="${escapeHtml(snip.snippet)}">[ COPY ]</button>
            </div>
            <div class="muted small">${escapeHtml(snip.config_file)}</div>
            <pre style="background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;padding:10px;overflow:auto;max-height:220px"><code>${escapeHtml(snip.snippet)}</code></pre>
          </div>`;
    }));
    el.innerHTML = blocks.join("");
    el.querySelectorAll(".mcp-copy").forEach((btn) => {
        btn.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(btn.dataset.copy);
                const was = btn.textContent;
                btn.textContent = "[ COPIED ]";
                setTimeout(() => { btn.textContent = was; }, 1200);
            } catch (_) { /* clipboard blocked — the pre is selectable anyway */ }
        });
    });
}

/* ─── mount ─── */

async function mount_mcp() {
    let cfg;
    try {
        cfg = await fetchConfig();
    } catch (_) {
        const el = $("#mcp-status");
        if (el) el.innerHTML = `<div class="chip high">control plane unreachable</div>`;
        return;
    }

    const apply = (fresh) => { cfg = fresh; renderTools(cfg); const sw = $("#mcp-enabled"); if (sw) sw.checked = cfg.enabled; renderStatus(cfg.status); };
    apply(cfg);
    await renderSetup();

    // Master switch.
    $("#mcp-enabled")?.addEventListener("change", async (e) => {
        apply(await putConfig({ enabled: e.target.checked }));
    });

    // Per-tool toggle → send the explicit list of currently-checked tools.
    $("#mcp-tools")?.addEventListener("change", async (e) => {
        const box = e.target.closest("input[data-tool]");
        if (!box) return;
        const checked = Array.from(document.querySelectorAll("#mcp-tools input[data-tool]:checked"))
            .map((b) => b.dataset.tool);
        apply(await putConfig({ allowed_tools: checked }));
    });

    // Quick actions.
    $("#mcp-allow-all")?.addEventListener("click", async () => { apply(await putConfig({ allowed_tools: null })); });
    $("#mcp-block-all")?.addEventListener("click", async () => { apply(await putConfig({ allowed_tools: [] })); });

    // Live status dot — cheap poll; keep-alive-safe (pollingScope registers
    // its own teardown so it dies with the pane).
    pollingScope(async () => {
        try {
            const fresh = await fetchConfig();
            renderStatus(fresh.status);
        } catch (_) { /* transient — next tick retries */ }
    }, 5000);
}

export { mount_mcp, view_mcp };
