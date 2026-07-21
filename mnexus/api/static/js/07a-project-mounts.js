// ── auto-wired ES-module imports ──
import { $, $$, attrTag, chip, escapeHtml, getJSON, h } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";
import { classifyTraceClass } from "./10a-project-chrome.js";

async function mount_project_dynamic(ctx) {
    const id = ctx.params.id;
    if (!id) return;
    const [project, hooks] = await Promise.all([
        getJSON(`/v1/projects/${encodeURIComponent(id)}`).catch(() => null),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/hooks`).catch(() => []),
    ]);

    // Breadcrumb with the real package name.
    const crumb = $("#dyn-breadcrumb");
    if (crumb && project) {
        crumb.innerHTML = `🔱 NEXUS / ${id} / dynamic · <span class="t-mono" style="color:var(--cyan)">${escapeHtml(project.package_name || "")}</span>`;
    }

    // Hooks list.
    const hookEl = $("#dyn-hooks");
    if (hookEl) {
        if (!hooks.length) {
            hookEl.innerHTML = `<div class="muted small">no auto-hooks generated yet — needs at least one CRYPTO / SSL / ROOT / AUTH finding. <a href="#/project/${id}/static">view findings</a></div>`;
        } else {
            const checked = new Set(hooks.slice(0, Math.min(3, hooks.length)).map((h) => h.name));
            hookEl.innerHTML = `<div class="muted small" style="margin-bottom:6px">Generated from this project's surface — ${hooks.length} hook(s).</div>`
                + hooks.map((h) => {
                    const on = checked.has(h.name);
                    const isAuto = !!h.source_finding_id;
                    return `
                    <label class="row" data-hook="${escapeHtml(h.name)}" style="padding:6px 10px;background:${on ? "var(--bg-accent-panel)" : "var(--bg-panel)"};border:1px solid ${on ? "var(--border-accent)" : "var(--border)"};border-radius:2px;cursor:pointer">
                      <input type="checkbox" ${on ? "checked" : ""} style="accent-color:var(--acid)">
                      <span class="t-mono small" style="color:${on ? "var(--acid)" : "var(--cyan)"};flex:1;overflow:hidden;text-overflow:ellipsis">${escapeHtml(h.name)}</span>
                      <span class="muted small" title="${escapeHtml(h.description || "")}">${isAuto ? "auto" : "recipe"}</span>
                    </label>`;
                }).join("");
        }
    }

    // ── Medusa recipes picker ─────────────────────────────────────────
    const recipesPanel = $("#dyn-recipes");
    if (recipesPanel) {
        try {
            const all = await getJSON("/v1/recipes");
            // Filter to recipes that target this project's platform.
            const platform = (project && project.platform) || "android";
            const matching = (all || []).filter((r) => {
                const p = r.platform || "android";
                return p === platform || p === "both";
            });
            const _renderRecipeList = (filter = "") => {
                const needle = filter.toLowerCase().trim();
                const filtered = needle
                    ? matching.filter((r) =>
                        (r.name || "").toLowerCase().includes(needle)
                        || (r.category || "").toLowerCase().includes(needle)
                        || (r.description || "").toLowerCase().includes(needle))
                    : matching;
                const filterRow = recipesPanel.querySelector(".row");
                const body = filtered.length
                    ? filtered.slice(0, 30).map((r) => `
                        <label class="row" data-recipe="${escapeHtml(r.name)}" style="padding:4px 8px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;cursor:pointer;align-items:center">
                          <input type="checkbox" style="accent-color:var(--acid)">
                          <span class="t-mono small" style="color:var(--cyan);flex:1;overflow:hidden;text-overflow:ellipsis">${escapeHtml(r.name)}</span>
                          <span class="muted small" title="${escapeHtml(r.description || "")}">${escapeHtml((r.category || "?").toLowerCase())}</span>
                        </label>`).join("")
                      + (filtered.length > 30 ? `<div class="muted small">+${filtered.length - 30} more — narrow with filter</div>` : "")
                    : `<div class="muted small">no recipes match</div>`;
                recipesPanel.innerHTML = "";
                if (filterRow) recipesPanel.appendChild(filterRow);
                else {
                    // Rebuild the filter row — happens after the first render.
                    const row = document.createElement("div");
                    row.className = "row";
                    row.style.cssText = "align-items:center;gap:6px";
                    row.innerHTML = `<input id="dyn-recipes-filter" placeholder="filter / SSL / encryption / …" style="flex:1;background:transparent;color:var(--cyan);border:1px solid var(--border);padding:3px 6px;font-family:inherit;font-size:11px">`;
                    recipesPanel.appendChild(row);
                }
                const listWrap = document.createElement("div");
                listWrap.className = "col";
                listWrap.style.cssText = "gap:4px;max-height:280px;overflow:auto";
                listWrap.innerHTML = body;
                recipesPanel.appendChild(listWrap);
            };
            _renderRecipeList("");
            // Wire the filter input — re-rendered on every keystroke,
            // but matching is in-memory so it's cheap.
            recipesPanel.addEventListener("input", (e) => {
                if (e.target && e.target.id === "dyn-recipes-filter") {
                    _renderRecipeList(e.target.value || "");
                }
            });
        } catch (e) {
            recipesPanel.innerHTML = `<div class="muted small">recipes unavailable: ${escapeHtml(e.message || String(e))}</div>`;
        }
    }

    // Console — empty until session starts.
    const consoleEl = $("#dyn-console");
    if (consoleEl) {
        const pkg = project?.package_name || "?";
        consoleEl.innerHTML = `<span class="muted">[NEXUS] target: ${escapeHtml(pkg)} · ${hooks.length} auto-hook(s) ready</span>
<span class="muted">[NEXUS] click [ START SESSION ] to attach Frida on the connected device</span>`;
    }

    let activeSession = null;
    let activeStream = null;

    const renderLogLine = (entry) => {
        if (!consoleEl) return;
        const line = typeof entry === "string" ? entry : (entry.line || _formatStreamEvent(entry));
        const channel = (entry && entry.channel) || "nexus";
        const div = document.createElement("div");
        div.innerHTML = `<span class="${classifyTraceClass(channel)}">${escapeHtml(line)}</span>`;
        consoleEl.appendChild(div);
        // Auto-scroll the console to the bottom on every new line so
        // a busy crypto-loop hook doesn't push the latest event off-screen.
        consoleEl.scrollTop = consoleEl.scrollHeight;
    };
    const replaceLog = (lines) => {
        if (!consoleEl) return;
        consoleEl.innerHTML = "";
        (lines || []).forEach((l) => renderLogLine(l));
        if (!lines || !lines.length) consoleEl.innerHTML = `<span class="muted">no events</span>`;
    };

    const openStream = (sessionId) => {
        if (activeStream) { activeStream.close(); activeStream = null; }
        const url = `/v1/projects/${encodeURIComponent(id)}/dynamic/stream?session_id=${encodeURIComponent(sessionId)}`;
        const es = new EventSource(url);
        activeStream = es;
        // Each backend event-type lands on its own EventSource event;
        // we register a generic + named handlers so unknown channels
        // (future recipes adding their own send({channel:...})) still surface.
        const onMsg = (e) => {
            try {
                const data = JSON.parse(e.data);
                renderLogLine(data);
            } catch (_) {
                renderLogLine({ channel: e.type, line: e.data });
            }
        };
        ["log", "nexus", "ssl_pin", "mem_trace", "crypto", "intent", "net", "fs", "clip", "error", "frida", "raw"].forEach((ch) => es.addEventListener(ch, onMsg));
        es.addEventListener("end", (e) => {
            try {
                const reason = JSON.parse(e.data || "{}");
                renderLogLine({ channel: "nexus", line: `[NEXUS] stream closed · ${reason.reason || "ended"}${reason.error ? " · " + reason.error : ""}` });
            } catch (_) {
                renderLogLine({ channel: "nexus", line: "[NEXUS] stream closed" });
            }
            es.close();
            activeStream = null;
        });
        es.onerror = () => {
            // SSE error events are uninformative — the network panel has the actual status.
            renderLogLine({ channel: "error", line: "[NEXUS] stream lost — server reachable?" });
            es.close();
            activeStream = null;
        };
    };

    $("#dyn-start")?.addEventListener("click", async () => {
        const selected = [];
        $$('label[data-hook]').forEach((label) => {
            const cb = label.querySelector('input[type="checkbox"]');
            if (cb && cb.checked) selected.push(label.dataset.hook);
        });
        const recipesSelected = [];
        $$('label[data-recipe]').forEach((label) => {
            const cb = label.querySelector('input[type="checkbox"]');
            if (cb && cb.checked) recipesSelected.push(label.dataset.recipe);
        });
        const btn = $("#dyn-start");
        btn.textContent = "[ STARTING… ]";
        btn.disabled = true;
        const fd = new FormData();
        fd.append("hooks", selected.join(","));
        fd.append("recipes", recipesSelected.join(","));
        fd.append("spawn", "true");
        try {
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/dynamic/start`, { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) {
                btn.textContent = `[ ${r.status === 503 ? "NO DEVICE" : "FAILED"} ]`;
                btn.style.color = "var(--sev-crit)";
                btn.title = (j && j.detail) || r.statusText;
                replaceLog([{ channel: "error", line: `[NEXUS] start failed · ${j && j.detail || r.statusText}` }]);
                btn.disabled = false;
                return;
            }
            activeSession = j.session_id;
            btn.textContent = `[ ATTACHED · ${activeSession} · pid ${j.pid || "?"} ]`;
            btn.style.color = "var(--acid)";
            btn.disabled = false;
            replaceLog(j.log);
            // Open the SSE stream right after the synchronous start
            // response so we don't miss the first batch of events.
            openStream(activeSession);
            // Memory Inspector panel goes live too. Only when the
            // tooling script loaded — j.tooling is false otherwise.
            if (j.tooling) {
                mountMemoryInspector(activeSession);
            }
        } catch (e) {
            btn.textContent = "[ FAILED ]";
            btn.style.color = "var(--sev-crit)";
            btn.title = e.message || String(e);
            btn.disabled = false;
        }
    });
    $("#dyn-stop")?.addEventListener("click", async () => {
        if (!activeSession) return;
        const fd = new FormData(); fd.append("session_id", activeSession);
        const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/dynamic/stop`, { method: "POST", body: fd });
        const j = await r.json();
        if (r.ok) {
            $("#dyn-stop").textContent = "[ DETACHED ]";
            renderLogLine({ channel: "nexus", line: "[NEXUS] detached cleanly" });
            if (activeStream) { activeStream.close(); activeStream = null; }
            // Memory Inspector panel goes back to idle.
            const memPanel = $("#dyn-memory");
            if (memPanel) memPanel.style.display = "none";
        }
    });
}

/* ── Memory Inspector wiring — Bloco 3 ──────────────────────────────
 *
 *  Called once a FridaSession with tooling=true comes online. Wires
 *  the four endpoints (modules / scan / read / write) to the panel
 *  the Dynamic view rendered hidden by default.
 *
 *  Token-swap workflow in the talk maps to:
 *    1. SCAN  pattern=<JWT header bytes> → list of addresses
 *    2. READ  address=<one of the hits> → confirm it's the right one
 *    3. WRITE address=<that one> hex=<victim's token bytes>
 *    The previous_hex returned by WRITE is the rollback. */
async function mountMemoryInspector(sessionId) {
    const panel = $("#dyn-memory");
    if (!panel) return;
    panel.style.display = "";
    const statusEl = $("#dyn-mem-status");
    statusEl.textContent = "tooling ready · loading modules…";

    // Populate the module dropdown so the analyst can scope a scan.
    try {
        const r = await fetch(`/v1/dynamic/sessions/${encodeURIComponent(sessionId)}/memory/modules`);
        const j = await r.json();
        const select = $("#dyn-mem-module");
        const opts = [`<option value="">(every module — slower)</option>`];
        (j.modules || []).slice(0, 200).forEach((m) => {
            opts.push(`<option value="${escapeHtml(m.name)}">${escapeHtml(m.name)} · ${m.size}B</option>`);
        });
        select.innerHTML = opts.join("");
        statusEl.textContent = `${(j.modules || []).length} module(s) · idle`;
    } catch (e) {
        statusEl.innerHTML = `<span style="color:var(--sev-crit)">modules failed: ${escapeHtml(e.message || String(e))}</span>`;
    }

    // Scan ─────────────────────────────
    const resultsEl = $("#dyn-mem-results");
    $("#dyn-mem-scan-go").addEventListener("click", async () => {
        const pattern = ($("#dyn-mem-pattern").value || "").trim();
        const moduleName = $("#dyn-mem-module").value || null;
        const maxResults = parseInt($("#dyn-mem-max").value || "100", 10);
        if (!pattern) { alert("paste a Frida pattern first ('65 79 4a 68' or 'aa ?? bb')"); return; }
        resultsEl.style.display = "";
        resultsEl.style.color = "var(--cyan)";
        resultsEl.textContent = "scanning…";
        try {
            const r = await fetch(`/v1/dynamic/sessions/${encodeURIComponent(sessionId)}/memory/scan`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ pattern, module: moduleName, max_results: maxResults }),
            });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            const matches = j.results || [];
            statusEl.textContent = `${matches.length} hit(s) · scanned ${j.ranges_scanned} range(s)${j.truncated ? " (truncated)" : ""}`;
            resultsEl.innerHTML = matches.length
                ? matches.map((m) => `
                    <div class="t-mono small" style="padding:2px 0;display:flex;gap:10px;align-items:center">
                      <a href="#" data-pick-addr="${escapeHtml(m.address)}" style="color:var(--acid);text-decoration:none">${escapeHtml(m.address)}</a>
                      <span class="muted">${m.range_protection} · ${m.range_base}+${m.range_size}B</span>
                    </div>`).join("")
                : `<div class="muted small">no hits — pattern absent in scanned range</div>`;
            // Click-to-pick: shove the address into the read input so
            // the analyst doesn't copy-paste.
            $$('[data-pick-addr]').forEach((a) => a.addEventListener("click", (e) => {
                e.preventDefault();
                const addr = a.dataset.pickAddr;
                $("#dyn-mem-addr").value = addr;
                $("#dyn-mem-write-addr").value = addr;
            }));
        } catch (e) {
            resultsEl.style.color = "var(--sev-crit)";
            resultsEl.textContent = `scan failed: ${e.message || e}`;
        }
    });

    // Read ─────────────────────────────
    const hexEl = $("#dyn-mem-hex");
    $("#dyn-mem-read-go").addEventListener("click", async () => {
        const address = ($("#dyn-mem-addr").value || "").trim();
        const size = parseInt($("#dyn-mem-size").value || "64", 10);
        if (!address) { alert("address required"); return; }
        hexEl.style.display = "";
        hexEl.style.color = "var(--cyan)";
        hexEl.textContent = "reading…";
        try {
            const r = await fetch(`/v1/dynamic/sessions/${encodeURIComponent(sessionId)}/memory/read`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ address, size }),
            });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            if (j.error) throw new Error(j.error);
            // Format as 16 bytes per line + ASCII gutter, like xxd.
            const hex = (j.hex || "").split(/\s+/);
            const lines = [];
            for (let i = 0; i < hex.length; i += 16) {
                const row = hex.slice(i, i + 16);
                const ascii = row.map((b) => {
                    const c = parseInt(b, 16);
                    return (c >= 0x20 && c < 0x7f) ? String.fromCharCode(c) : ".";
                }).join("");
                lines.push(row.join(" ").padEnd(48, " ") + "  " + ascii);
            }
            hexEl.style.color = "var(--cyan)";
            hexEl.textContent = lines.join("\n");
        } catch (e) {
            hexEl.style.color = "var(--sev-crit)";
            hexEl.textContent = `read failed: ${e.message || e}`;
        }
    });

    // Write ────────────────────────────
    const writeOutEl = $("#dyn-mem-write-out");
    $("#dyn-mem-write-go").addEventListener("click", async () => {
        const address = ($("#dyn-mem-write-addr").value || "").trim();
        const hex = ($("#dyn-mem-write-hex").value || "").trim();
        if (!address || !hex) { alert("address + hex bytes required"); return; }
        const byteCount = hex.split(/\s+/).filter(Boolean).length;
        if (!confirm(`Overwrite ${byteCount} byte(s) at ${address}?\n\nThis can crash the target. The previous bytes will be returned so you can roll back manually.`)) {
            return;
        }
        writeOutEl.style.display = "";
        writeOutEl.style.color = "var(--cyan)";
        writeOutEl.textContent = "writing…";
        try {
            const r = await fetch(`/v1/dynamic/sessions/${encodeURIComponent(sessionId)}/memory/write`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ address, hex }),
            });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            if (j.error) throw new Error(j.error);
            writeOutEl.style.color = "var(--acid)";
            writeOutEl.textContent =
                `✓ wrote ${j.written} byte(s) at ${j.address}\n` +
                `rollback hex (keep this around): ${j.previous_hex || "<no prev — was unreadable>"}`;
        } catch (e) {
            writeOutEl.style.color = "var(--sev-crit)";
            writeOutEl.textContent = `write failed: ${e.message || e}`;
        }
    });

    // Trace ────────────────────────────
    // MemoryAccessMonitor arming/disarming. Each first-page-touch fires
    // a mem_trace event on the SSE stream — same channel the dynamic
    // console renders, so the analyst doesn't need a separate viewer.
    const traceStatus = $("#dyn-mem-trace-status");
    $("#dyn-mem-trace-go").addEventListener("click", async () => {
        const addr = ($("#dyn-mem-trace-addr").value || "").trim();
        const size = parseInt($("#dyn-mem-trace-size").value || "256", 10);
        if (!addr) { alert("address required"); return; }
        traceStatus.style.color = "var(--cyan)";
        traceStatus.textContent = "arming…";
        try {
            const r = await fetch(`/v1/dynamic/sessions/${encodeURIComponent(sessionId)}/memory/trace`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ranges: [{ base: addr, size }] }),
            });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            if (j.error) throw new Error(j.error);
            traceStatus.style.color = "var(--acid)";
            traceStatus.textContent = `armed · ${addr} +${size}B · waiting for first touch`;
        } catch (e) {
            traceStatus.style.color = "var(--sev-crit)";
            traceStatus.textContent = `arm failed: ${e.message || e}`;
        }
    });
    $("#dyn-mem-trace-stop").addEventListener("click", async () => {
        try {
            const r = await fetch(`/v1/dynamic/sessions/${encodeURIComponent(sessionId)}/memory/trace`, { method: "DELETE" });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            if (j.error) throw new Error(j.error);
            traceStatus.style.color = "var(--muted)";
            traceStatus.textContent = "stopped";
        } catch (e) {
            traceStatus.style.color = "var(--sev-crit)";
            traceStatus.textContent = `stop failed: ${e.message || e}`;
        }
    });
}

/** Format an event from /dynamic/stream into a single console line. */
function _formatStreamEvent(event) {
    if (!event) return "";
    if (event.line) return event.line;
    const payload = event.payload || {};
    if (event.channel === "ssl_pin") {
        return `[SSL_PIN] ${payload.host || "?"} · ${payload.lib || "?"} → ${payload.outcome || "?"}`;
    }
    if (event.channel === "mem_trace") {
        return `[MEM_TRACE] ${payload.operation || "?"} at ${payload.address || "?"}` +
               (payload.from ? ` from ${payload.from}` : "");
    }
    if (event.channel === "error") {
        return `[ERROR] ${payload.description || "?"}${payload.line ? " @" + payload.line : ""}`;
    }
    if (event.channel === "nexus") {
        return payload.line || "";
    }
    const parts = Object.entries(payload || {})
        .filter(([k]) => k !== "channel")
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(" ");
    return `[${(event.channel || "?").toUpperCase()}] ${parts}`;
}

async function mount_project_network(ctx) {
    const id = ctx.params.id;
    if (!id) return;
    const [project, apimap, sslmap, traffic, findings, moxy] = await Promise.all([
        getJSON(`/v1/projects/${encodeURIComponent(id)}`).catch(() => null),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/api-map`).catch(() => ({tree: {}, endpoints: [], flagged: []})),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/ssl-map`).catch(() => ({pinning_detected: false, library: "—", rows: []})),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/traffic`).catch(() => ({captured: []})),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/findings?category=network-security`).catch(() => []),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/moxy-traffic`).catch((e) => ({captured: [], moxy_project: null, available_projects: [], error: e.message || "moxy unreachable"})),
    ]);

    const surface = (project && project.attack_surface) || {};
    const cleartext = (project?.uses_cleartext_traffic === true) || surface.uses_cleartext_traffic === true
        // The project model doesn't store the manifest flag separately — derive
        // from whether any apktool finding flagged it.
        || (findings.some((f) => /cleartext/i.test(f.title || "")));

    // Breadcrumb
    const crumb = $("#net-breadcrumb");
    if (crumb && project) {
        crumb.innerHTML = `🔱 NEXUS / ${id} / network · <span class="t-mono" style="color:var(--cyan)">${escapeHtml(project.package_name || "")}</span>`;
    }

    // Metric cards
    const ec = (apimap.endpoints || []).length;
    $("#net-endpoints-count").textContent = String(ec).padStart(2, "0");
    $("#net-endpoints-count").className = "metric-value " + (ec ? "cyan" : "");
    $("#net-endpoints-sub").textContent = ec ? `${Object.keys(apimap.tree || {}).length} host(s)` : "none — needs Burp capture or static URL extraction";

    const burpRows = (traffic.captured || []).map((r) => ({...r, origin: r.origin || "burp"}));
    const moxyRows = (moxy && moxy.captured) || [];
    const tc = burpRows.length + moxyRows.length;
    $("#net-traffic-count").textContent = String(tc).padStart(2, "0");
    $("#net-traffic-count").className = "metric-value " + (tc ? "acid" : "");
    $("#net-traffic-sub").textContent = tc
        ? `${burpRows.length} burp · ${moxyRows.length} moxy`
        : "no proxy data yet";

    const sslMetric = $("#net-ssl");
    sslMetric.textContent = sslmap.pinning_detected ? "ON" : "—";
    sslMetric.className = "metric-value " + (sslmap.pinning_detected ? "acid" : "");
    $("#net-ssl-sub").textContent = sslmap.library || "none";

    const ctMetric = $("#net-cleartext");
    ctMetric.textContent = cleartext ? "YES" : "no";
    ctMetric.className = "metric-value " + (cleartext ? "crit" : "acid");
    $("#net-cleartext-sub").textContent = cleartext ? "android:usesCleartextTraffic=true" : "TLS only";

    // Endpoints panel — host tree if we have any.
    const epEl = $("#net-endpoints");
    const tree = apimap.tree || {};
    const hosts = Object.keys(tree).sort();
    if (!hosts.length) {
        epEl.innerHTML = `<div class="empty-state">no API endpoints discovered yet — drop a Burp session into the workspace or wait for static URL extraction (iter 3).</div>`;
    } else {
        epEl.innerHTML = hosts.map((host) => {
            const paths = Object.keys(tree[host]).sort();
            return `
              <div style="margin-bottom:10px">
                <div class="t-mono" style="color:var(--cyan);font-weight:700">▾ ${escapeHtml(host)}</div>
                ${paths.slice(0, 12).map((p) => {
                    const node = tree[host][p];
                    const methods = Array.isArray(node) ? node : ((node && node.methods) || []);
                    const hits = (node && node.hits) || 0;
                    return `<div class="t-mono small" style="padding-left:18px">${methods.map((m) => `<span class="chip ${m === "POST" ? "high" : "info"}" style="font-size:9px">${m}</span>`).join(" ")} ${escapeHtml(p)}${hits ? ` <span style="color:var(--acid)">×${hits}</span>` : ""}</div>`;
                }).join("")}
              </div>`;
        }).join("");
    }

    // Traffic panel — merged Burp + Moxy
    const tEl = $("#net-traffic");
    const moxyStatusEl = $("#net-moxy-status");
    const moxyProjEl = $("#net-moxy-project");
    const matchOnlyEl = $("#net-moxy-match-only");
    const refreshBtn = $("#net-traffic-refresh");
    $("#net-traffic-meta").textContent = tc ? `${tc} request(s)` : "no traffic captured yet";

    // Populate the Moxy workspace picker from /moxy-traffic's available_projects.
    if (moxyProjEl) {
        const avail = (moxy && moxy.available_projects) || [];
        const picked = moxy && moxy.moxy_project ? moxy.moxy_project.id : null;
        moxyProjEl.innerHTML = avail.length
            ? avail.map((p) => `<option value="${p.id}" ${p.id === picked ? "selected" : ""}>${escapeHtml(p.name || ("#" + p.id))}</option>`).join("")
            : `<option value="">(no moxy workspaces)</option>`;
        if (moxyStatusEl) {
            if (moxy && moxy.error) {
                moxyStatusEl.innerHTML = `<span style="color:var(--magenta)">${escapeHtml(moxy.error)}</span>`;
            } else if (moxy && moxy.moxy_project) {
                moxyStatusEl.innerHTML = `picked <span style="color:var(--acid)">${escapeHtml(moxy.moxy_project.name || "?")}</span> · ${(moxy.hosts || []).length} known host(s)`;
            } else {
                moxyStatusEl.textContent = "moxy idle";
            }
        }
    }

    const renderRows = (rows) => {
        if (!rows.length) {
            tEl.innerHTML = `<div class="empty-state">no captured traffic — start a Burp / Moxy session and proxy the device through it. The events will surface here.</div>`;
            return;
        }
        const sevColor = (status) => {
            const s = Number(status) || 0;
            if (!s) return "info";
            if (s < 300) return "acid";
            if (s < 400) return "info";
            if (s < 500) return "sev-high";
            return "sev-crit";
        };
        tEl.innerHTML = `
          <div class="table-hdr" style="grid-template-columns: 50px 60px 180px 1fr 70px 80px 60px 80px">
            <span>SRC</span><span>M</span><span>HOST</span><span>PATH</span><span>STATUS</span><span>SIZE</span><span>MS</span><span>FLAGS</span>
          </div>` + rows.map((row) => {
            const m = row.method || "GET";
            const sev = sevColor(row.status);
            const origin = row.origin || "burp";
            const originColor = origin === "moxy" ? "var(--magenta)" : "var(--cyan)";
            const matched = row.matches_project === false ? false : true;
            const dim = !matched ? "opacity:0.55" : "";
            return `
              <div class="table-row" style="grid-template-columns: 50px 60px 180px 1fr 70px 80px 60px 80px;${dim}">
                <span class="t-mono" style="color:${originColor};font-weight:700;font-size:9px;letter-spacing:1px">${escapeHtml(origin.toUpperCase())}</span>
                <span class="t-mono" style="color:${m === "POST" ? "var(--acid)" : "var(--cyan)"};font-weight:700">${escapeHtml(m)}</span>
                <span class="t-mono" style="color:var(--cyan)">${escapeHtml(row.host || "?")}</span>
                <span class="t-mono" style="color:var(--cyan);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(row.url || row.path || "")}">${escapeHtml(row.path || "/")}</span>
                <span class="t-mono" style="color:var(--${sev});font-weight:700">${row.status || "—"}</span>
                <span class="t-muted">${fmtBytes(row.size || 0)}</span>
                <span class="t-muted">${row.ms || "—"}</span>
                <span style="font-size:9px;color:var(--sev-info);font-weight:700">${(row.flags || []).map((f) => "[" + escapeHtml(f) + "]").join("")}${matched && row.origin === "moxy" ? "[✓]" : ""}</span>
              </div>`;
        }).join("");
    };

    // Initial render: Burp rows on top, Moxy rows underneath. Sort by timestamp
    // descending so the most recent flow is at the top regardless of origin.
    const merged = [...burpRows, ...moxyRows].sort((a, b) => String(b.ts || "").localeCompare(String(a.ts || "")));
    renderRows(merged);

    // Workspace switcher → re-fetch /moxy-traffic and merge.
    const reloadMoxy = async () => {
        const wsId = moxyProjEl && moxyProjEl.value;
        const matchOnly = matchOnlyEl && matchOnlyEl.checked;
        const params = new URLSearchParams();
        if (wsId) params.set("moxy_project", wsId);
        if (matchOnly) params.set("match_only", "true");
        if (moxyStatusEl) moxyStatusEl.textContent = "reloading…";
        try {
            const fresh = await getJSON(`/v1/projects/${encodeURIComponent(id)}/moxy-traffic?${params.toString()}`);
            const freshMoxy = fresh.captured || [];
            if (moxyStatusEl) {
                moxyStatusEl.innerHTML = `picked <span style="color:var(--acid)">${escapeHtml(fresh.moxy_project && fresh.moxy_project.name || "?")}</span> · ${freshMoxy.length} flow(s)${matchOnly ? " · matches only" : ""}`;
            }
            $("#net-traffic-count").textContent = String(burpRows.length + freshMoxy.length).padStart(2, "0");
            $("#net-traffic-sub").textContent = `${burpRows.length} burp · ${freshMoxy.length} moxy`;
            $("#net-traffic-meta").textContent = `${burpRows.length + freshMoxy.length} request(s)`;
            const merged2 = [...burpRows, ...freshMoxy].sort((a, b) => String(b.ts || "").localeCompare(String(a.ts || "")));
            renderRows(merged2);
        } catch (e) {
            if (moxyStatusEl) moxyStatusEl.innerHTML = `<span style="color:var(--magenta)">${escapeHtml(e.message || "moxy fetch failed")}</span>`;
        }
    };

    if (moxyProjEl) moxyProjEl.addEventListener("change", reloadMoxy);
    if (matchOnlyEl) matchOnlyEl.addEventListener("change", reloadMoxy);
    if (refreshBtn) refreshBtn.addEventListener("click", reloadMoxy);

    // Findings panel — two layers: persisted static findings on top,
    // live proxy-derived findings (cleartext / JWT leak / insecure
    // cookies / API key in URL / 5xx run / discovered hosts) beneath
    // a divider. The live ones don't link to a stored finding (they're
    // recomputed each request from the current window) — render them
    // inline instead of as anchors.
    const fEl = $("#net-findings");
    const liveFindings = (moxy && moxy.findings) || [];
    const staticBlock = findings.length
        ? findings.map((f) => `
            <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
              <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span>${attrTag(f)}<span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
              <div class="title">${escapeHtml(f.title)}</div>
              <div class="meta">${escapeHtml(f.location || "—")} · ${f.cwe_id || ""} ${f.owasp_mobile || ""}</div>
            </a>`).join("")
        : `<div class="empty-state">no network-category findings from the static scan</div>`;
    const liveBlock = liveFindings.length
        ? `<div class="muted small uppercase" style="letter-spacing:2px;margin-top:8px;padding-top:6px;border-top:1px dashed var(--border)">
              // live — derived from proxy traffic · ${liveFindings.length}
           </div>` + liveFindings.map((f) => `
            <div class="finding" style="cursor:default">
              <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
              <div class="title">${escapeHtml(f.title)}</div>
              <div class="meta">${escapeHtml(f.location || "—")} · ${f.cwe_id || ""} ${f.owasp_mobile || ""}</div>
              ${f.remediation ? `<div class="muted small" style="margin-top:6px;padding-top:4px;border-top:1px dotted var(--border);white-space:pre-wrap">${escapeHtml(f.remediation)}</div>` : ""}
            </div>`).join("")
        : "";
    fEl.innerHTML = staticBlock + liveBlock;
}


export { mount_project_dynamic, mount_project_network };
