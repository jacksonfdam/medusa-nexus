// ── auto-wired ES-module imports ──
import { $, $$, escapeHtml, getJSON, h, sectionHeader } from "./01-core.js";
import { renderRoute } from "./11-router.js";

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 05 — Pull from Device
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_device_pull() {
    return h`
    <div class="main">
      ${sectionHeader("P", "05 // INTAKE", "PULL FROM DEVICE")}
      ${deviceTabs("pull")}
      <section class="row" style="align-items:center;gap:10px;flex-wrap:wrap">
        <div class="input grow"><span class="prompt">&gt;</span><input id="pull-filter" placeholder="filter — substring of package name"><span class="cursor">_</span></div>
        <span class="badge" id="pull-device-badge"><span class="dot">●</span>scanning…</span>
      </section>
      <section class="row" id="pull-scope" style="gap:6px;align-items:center;flex-wrap:wrap;font-size:11px">
        <span class="muted uppercase" style="letter-spacing:2px">scope:</span>
        <button class="btn primary" data-scope="3rd">[ 3RD-PARTY ]</button>
        <button class="btn"         data-scope="all">[ ALL ]</button>
        <button class="btn"         data-scope="system">[ SYSTEM ]</button>
        <span class="spacer"></span>
        <span class="muted small">tip: 3rd-party skips Samsung/Google/Knox bloat — flip to ALL only if you need a system package.</span>
      </section>
      <section class="panel">
        <div class="panel-head">
          <span>// PACKAGES</span>
          <span class="spacer"></span>
          <span class="muted small" id="pull-count">scanning…</span>
        </div>
        <div class="panel-body" id="pull-table">
          <div class="empty-state"><span class="muted small uppercase">scanning device…</span></div>
        </div>
      </section>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 06 — Device Bridge (tabs: INFO · SHELL · FILES · SCREEN · LOGCAT)
 * ═══════════════════════════════════════════════════════════════════════════ */
function deviceTabs(active) {
    const tabs = [
        ["bridge",  "INFO"],
        ["shell",   "SHELL"],
        ["files",   "FILES"],
        ["screen",  "SCREEN"],
        ["logcat",  "LOGCAT"],
        ["pull",    "PULL APK"],
    ];
    return `
    <div class="tab-bar">
      ${tabs.map(([k, label]) => `<a class="tab ${k === active ? "active" : ""}" href="#/device/${k}">${k === active ? "> " : "  "}${label}</a>`).join("")}
      <span class="grow"></span>
      <a class="tab" href="#/adb" style="color:var(--magenta)">+ ADB CONTROL ↗</a>
    </div>
    <div id="device-status-strip" class="row" style="padding:6px 10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;margin:6px 0 12px;font-size:11px"><span class="muted small">device:</span><span class="t-mono" id="device-status-text">checking…</span><span class="grow"></span><span class="muted small">commands routed via the singular /v1/device/* endpoints — for per-serial control, switch to ADB →</span></div>`;
}

async function fillDeviceStatusStrip() {
    const text = $("#device-status-text");
    if (!text) return;
    const info = await getJSON("/v1/device/info").catch(() => ({connected: false}));
    if (info.connected) {
        text.textContent = `${info.manufacturer || ""} ${info.model || ""} · A${info.android_release || "?"} · ${info.abi || ""}`.trim();
        text.style.color = "var(--acid)";
    } else {
        text.textContent = "no device connected";
        text.style.color = "var(--sev-crit)";
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 03b — Decrypt IPA (iOS)
 *
 *  FairPlay-encrypted IPAs need a JB device + bagbak / frida-ios-dump
 *  to land as analysable Mach-O. This screen drives /v1/ios/decrypt,
 *  auto-ingests the result, and links straight to the new project.
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_ios_decrypt() {
    return h`
    <div class="main">
      ${sectionHeader("D", "03b // iOS INTAKE", "DECRYPT IPA FROM JB DEVICE")}
      <section class="panel">
        <div class="panel-head">
          <span>// DECRYPTOR STATUS</span>
          <span class="spacer"></span>
          <span class="muted small" id="ios-dec-status">checking…</span>
        </div>
        <div class="panel-body col" style="gap:10px">
          <div class="muted small">
            Wraps <code>bagbak</code> (preferred) or <code>frida-ios-dump</code>.
            Spawn the target on a jailbroken iPhone, wait for the kernel to
            decrypt <code>__TEXT</code>/<code>__DATA</code> segments, dump
            them, fix up <code>LC_ENCRYPTION_INFO.cryptid</code>, repack.
          </div>
          <div class="muted small">
            <a href="#/help" onclick="event.preventDefault();window.open('/docs#/v1/ios/decrypt','_blank')">API reference</a>
            · <a href="https://github.com/jacksonfdam/medusa-nexus/blob/main/docs/IOS.md" target="_blank">full iOS workflow doc</a>
          </div>

          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:120px">bundle id:</span>
            <input id="ios-dec-bundle" class="input t-mono" placeholder="com.target.bank.test" style="flex:1;min-width:240px">
          </div>
          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:120px">device id:</span>
            <input id="ios-dec-device" class="input t-mono" placeholder="(first USB by default)" style="flex:1;min-width:240px">
            <span class="muted small uppercase" style="letter-spacing:2px">timeout:</span>
            <input id="ios-dec-timeout" class="input t-mono" type="number" min="30" max="900" value="180" style="width:90px">
          </div>
          <div class="row" style="gap:8px;align-items:center">
            <label class="row small" style="gap:6px;align-items:center;cursor:pointer">
              <input type="checkbox" id="ios-dec-ingest" checked>
              <span>auto-ingest after decrypt (recommended)</span>
            </label>
            <span class="spacer"></span>
            <button class="btn primary" id="ios-dec-go" style="white-space:nowrap">[ ▶ DECRYPT ]</button>
          </div>
          <div id="ios-dec-out" class="muted small" style="display:none;padding:8px 10px;background:#050505;border:1px solid var(--border);border-radius:2px;white-space:pre-wrap;font-family:'Courier Prime',monospace;max-height:220px;overflow:auto"></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><span>// HOW TO FIND THE BUNDLE ID</span></div>
        <div class="panel-body col" style="gap:6px;color:var(--muted)">
          <div class="small">On the connected JB device, over SSH:</div>
          <div class="t-mono small" style="padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px">ssh root@iphone "ls /var/containers/Bundle/Application/*/*.app/Info.plist | xargs grep -l -A1 'CFBundleIdentifier'"</div>
          <div class="small">Or pull the apps list from frida directly:</div>
          <div class="t-mono small" style="padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px">frida-ps -Uai</div>
        </div>
      </section>
    </div>`;
}

async function mount_ios_decrypt() {
    const statusEl = $("#ios-dec-status");
    try {
        const status = await getJSON("/v1/ios/decrypt/status");
        if (status.available) {
            statusEl.innerHTML = `<span style="color:var(--acid)">✓ ${escapeHtml(status.tool)} ready</span> · <span class="t-mono">${escapeHtml(status.path || "")}</span>`;
        } else {
            statusEl.innerHTML = `<span style="color:var(--sev-crit)">no decryptor installed</span> · <code>${escapeHtml(status.install_hint || "scripts/setup.sh --ios-tools")}</code>`;
        }
    } catch (e) {
        statusEl.innerHTML = `<span style="color:var(--sev-crit)">status check failed: ${escapeHtml(e.message || String(e))}</span>`;
    }

    const outEl = $("#ios-dec-out");
    $("#ios-dec-go").addEventListener("click", async () => {
        const bundle = ($("#ios-dec-bundle").value || "").trim();
        if (!bundle) { alert("bundle id required"); return; }
        const device = ($("#ios-dec-device").value || "").trim();
        const timeout = parseInt($("#ios-dec-timeout").value || "180", 10);
        const ingest = $("#ios-dec-ingest").checked;
        const btn = $("#ios-dec-go");
        const orig = btn.textContent;
        btn.textContent = "[ DECRYPTING… ]";
        btn.disabled = true;
        outEl.style.display = "";
        outEl.style.color = "var(--cyan)";
        outEl.textContent = `decrypting ${bundle}… (can take 30–180s)`;
        try {
            const fd = new FormData();
            fd.append("bundle_id", bundle);
            if (device) fd.append("device_id", device);
            fd.append("ingest", ingest ? "true" : "false");
            fd.append("timeout_s", String(timeout));
            const r = await fetch("/v1/ios/decrypt", { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            const lines = [
                `✓ decrypted via ${j.tool} in ${j.duration_ms}ms`,
                `  IPA → ${j.ipa_path}`,
            ];
            (j.warnings || []).forEach((w) => lines.push(`  warn: ${w}`));
            if (j.project_id) {
                lines.push(`  ingested → ${j.project_id}`);
            }
            outEl.style.color = "var(--acid)";
            outEl.textContent = lines.join("\n");
            btn.textContent = j.project_id ? `[ ✓ OPEN ${j.project_id} ]` : "[ ✓ DONE ]";
            btn.style.color = "var(--acid)";
            btn.disabled = false;
            if (j.project_id) {
                btn.onclick = () => { location.hash = `#/project/${j.project_id}/overview`; };
                setTimeout(() => {
                    if (location.hash.startsWith("#/ios/decrypt")) {
                        location.hash = `#/project/${j.project_id}/overview`;
                    }
                }, 1500);
            }
        } catch (e) {
            outEl.style.color = "var(--sev-crit)";
            outEl.textContent = `decrypt failed: ${e.message || e}`;
            btn.textContent = "[ FAILED ]";
            btn.style.color = "var(--sev-crit)";
            btn.disabled = false;
            setTimeout(() => { if (btn.textContent === "[ FAILED ]") { btn.textContent = orig; btn.style.color = ""; } }, 6000);
        }
    });
}

function view_device_bridge() {
    return h`
    <div class="main">
      ${sectionHeader("B", "06 // INTAKE", "DEVICE BRIDGE")}
      ${deviceTabs("bridge")}
      <section class="row" style="gap:16px;align-items:flex-start">
        <section class="panel grow">
          <div class="panel-head"><span>// DEVICE</span><span class="spacer"></span><span class="badge connected" id="bridge-badge"><span class="dot">●</span>loading…</span></div>
          <div class="panel-body col" id="bridge-info" style="gap:6px">loading…</div>
        </section>
        <section class="panel" style="width:280px;flex:none">
          <div class="panel-head">// ACTIONS</div>
          <div class="panel-body col">
            <button class="btn primary">[ START FRIDA-SERVER ]</button>
            <button class="btn">[ PUSH SCRIPTS ]</button>
            <button class="btn">[ PATCH WITH STHENO ]</button>
            <button class="btn danger">[ FORCE REBOOT ]</button>
          </div>
        </section>
      </section>
      <section class="row" style="gap:16px;align-items:flex-start">
        <section class="panel grow">
          <div class="panel-head">// BATTERY</div>
          <div class="panel-body col" id="bridge-battery">loading…</div>
        </section>
        <section class="panel grow">
          <div class="panel-head">// MEMORY</div>
          <div class="panel-body col" id="bridge-memory">loading…</div>
        </section>
        <section class="panel grow">
          <div class="panel-head">// STORAGE</div>
          <div class="panel-body" id="bridge-storage">loading…</div>
        </section>
      </section>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 07 — Project Overview (tabbed with Static / Dynamic / Network / Report)
 * ═══════════════════════════════════════════════════════════════════════════ */
function projectTabs(id, active) {
    const tabs = [
        ["overview", "OVERVIEW"],
        ["static", "STATIC"],
        ["dynamic", "DYNAMIC"],
        ["runtime", "RUNTIME"],
        ["network", "NETWORK"],
        ["report", "REPORT"],
    ];
    return `
    <div class="tab-bar">
      ${tabs.map(([k, label]) => `<a class="tab ${k === active ? "active" : ""}" href="#/project/${encodeURIComponent(id)}/${k}">${k === active ? "> " : "  "}${label}</a>`).join("")}
      <span class="grow"></span>
      <button class="tab" onclick="projectChromeManifest('${id}')" title="View the decoded AndroidManifest.xml (or Info.plist on iOS)">📄 MANIFEST</button>
      <button class="tab" onclick="projectChromeAttribute('${id}')" title="Re-tag findings with their SDK / first-party owner (LibraryAttributionAudit)" style="color:var(--cyan)">⌖ ATTRIBUTE</button>
      <button class="tab" onclick="projectChromeBackup('${id}')" title="Zip up the entire project — model + findings + workspace + reports">↓ BACKUP</button>
      <button class="tab" onclick="projectChromeDelete('${id}')" title="Wipe every disk + DB trace of this project (destructive)" style="color:var(--sev-high)">🗑 DELETE</button>
      <button class="tab" data-rescan="${id}" title="re-run static fan-out + rebuild attack surface">⟳ RESCAN</button>
      <a class="tab" href="#/project/${encodeURIComponent(id)}/${active}" data-refresh="${id}" title="reload current view">↻ REFRESH</a>
    </div>`;
}

/* Wired by every project-* mount so the tab-bar buttons work everywhere. */
function bindProjectTabActions() {
    $$('[data-rescan]').forEach((btn) => {
        if (btn._wired) return; btn._wired = true;
        btn.addEventListener("click", async () => {
        const id = btn.dataset.rescan;
        if (!confirm(`re-run static fan-out on ${id}?`)) return;
        const orig = btn.textContent;
        btn.textContent = "⟳ rescanning…";
        btn.style.color = "var(--magenta)";
        try {
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/rescan`, { method: "POST" });
            const j = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(j.detail || r.statusText);
            btn.textContent = `✓ ${j.findings_count} findings · risk ${j.risk_score?.toFixed?.(1) || "?"}`;
            btn.style.color = "var(--acid)";
            // re-render the current route
            setTimeout(() => { renderRoute(); }, 600);
        } catch (e) {
            btn.textContent = "✕ rescan failed";
            btn.style.color = "var(--sev-crit)";
            console.error(e);
            setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 3500);
        }
        });
    });
    $$('[data-refresh]').forEach((btn) => {
        if (btn._wired) return; btn._wired = true;
        btn.addEventListener("click", (e) => { e.preventDefault(); renderRoute(); });
    });
}

function view_project_overview(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / overview</div>
      ${projectTabs(id, "overview")}
      <div class="empty-state"><span class="muted small uppercase">loading project ${id}…</span></div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 08 — Static Analysis (real APK data — populated by mount)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_static(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase" id="static-breadcrumb">🔱 NEXUS / ${id} / static</div>
      ${projectTabs(id, "static")}

      <section class="row" id="static-filters" style="gap:8px;flex-wrap:wrap">
        <span class="muted small">filter:</span>
        <button class="btn" data-fsev="">[ ALL ]</button>
        <button class="btn" data-fsev="critical">[ CRIT ]</button>
        <button class="btn" data-fsev="high">[ HIGH ]</button>
        <button class="btn" data-fsev="medium">[ MED ]</button>
        <button class="btn" data-fsev="low">[ LOW ]</button>
        <button class="btn" data-fsev="info">[ INFO ]</button>
        <span class="grow"></span>
        <span class="muted small" id="static-count">loading…</span>
      </section>

      <div class="row" style="align-items:flex-start;gap:12px;flex-wrap:wrap">
        <section class="panel" style="width:300px;flex:none;min-width:0">
          <div class="panel-head">// SDK FINGERPRINT</div>
          <div class="panel-body col" style="gap:6px" id="static-sdks">loading…</div>
        </section>

        <section class="panel grow" style="min-width:0">
          <div class="panel-head"><span>// FINDINGS</span><span class="spacer"></span><span class="muted small" id="static-active-filter">all severities</span></div>
          <div class="panel-body col" style="gap:8px" id="static-findings">loading…</div>
        </section>

        <section class="panel" style="width:300px;flex:none;min-width:0">
          <div class="panel-head">// CRYPTO OPS</div>
          <div class="panel-body col" style="gap:4px" id="static-crypto">loading…</div>
        </section>
      </div>

      <div class="row muted small" style="justify-content:center;gap:18px;flex-wrap:wrap">
        <a href="#/project/${id}/secrets">secrets + crypto</a> ·
        <a href="#/project/${id}/components">components + deeplinks</a> ·
        <a href="#/project/${id}/native">native (ghidra)</a> ·
        <a href="#/project/${id}/owasp">OWASP MASVS matrix</a>
      </div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 12 — Dynamic Analysis (real package + real auto-hooks)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_dynamic(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase" id="dyn-breadcrumb">🔱 NEXUS / ${id} / dynamic</div>
      ${projectTabs(id, "dynamic")}
      <div class="row" style="align-items:flex-start;gap:12px;flex-wrap:wrap">
        <section class="panel" style="width:280px;flex:none;min-width:0">
          <div class="panel-head">// AUTO-HOOKS</div>
          <div class="panel-body col" style="gap:6px" id="dyn-hooks">loading…</div>
          <div class="panel-head" style="margin-top:10px">// MEDUSA RECIPES</div>
          <div class="panel-body col" style="gap:6px" id="dyn-recipes">
            <div class="row" style="align-items:center;gap:6px">
              <input id="dyn-recipes-filter" placeholder="filter / SSL / encryption / …" style="flex:1;background:transparent;color:var(--cyan);border:1px solid var(--border);padding:3px 6px;font-family:inherit;font-size:11px">
            </div>
            <div class="muted small">loading…</div>
          </div>
        </section>
        <section class="panel grow" style="min-width:0">
          <div class="panel-head">
            <span>// FRIDA CONSOLE</span>
            <span class="spacer"></span>
            <button class="btn primary" id="dyn-start">[ START SESSION ]</button>
            <button class="btn" id="dyn-stop">[ STOP ]</button>
          </div>
          <div class="panel-body console" id="dyn-console" style="min-height:340px"></div>
        </section>
      </div>

      <!-- Memory Inspector (Bloco 3) — enabled when a session is attached
           AND its tooling script loaded. Hidden by default; mount toggles it on. -->
      <section class="panel" id="dyn-memory" style="display:none">
        <div class="panel-head">
          <span>// MEMORY INSPECTOR</span>
          <span class="spacer"></span>
          <span class="muted small" id="dyn-mem-status">idle</span>
        </div>
        <div class="panel-body col" style="gap:10px">
          <div class="muted small">
            Scan readable memory for a pattern, peek the bytes, write over them.
            <strong style="color:var(--sev-high)">Writes can crash the target</strong> —
            keep the rollback hex around.
          </div>

          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
            <span class="muted small uppercase" style="letter-spacing:2px;width:90px">scan:</span>
            <input id="dyn-mem-pattern" class="input t-mono" placeholder="65 79 4a 68  (=  'eyJ…' JWT header)" style="flex:2;min-width:200px">
            <select id="dyn-mem-module" class="input t-mono" style="min-width:160px"><option value="">(every module)</option></select>
            <input id="dyn-mem-max" class="input t-mono" type="number" min="1" max="2000" value="100" style="width:80px">
            <button class="btn primary" id="dyn-mem-scan-go" style="white-space:nowrap">[ SCAN ]</button>
          </div>
          <div id="dyn-mem-results" class="muted small" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px;max-height:200px;overflow:auto"></div>

          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
            <span class="muted small uppercase" style="letter-spacing:2px;width:90px">peek:</span>
            <input id="dyn-mem-addr" class="input t-mono" placeholder="0x1234abcd" style="flex:2;min-width:180px">
            <input id="dyn-mem-size" class="input t-mono" type="number" min="1" max="4096" value="64" style="width:80px">
            <button class="btn" id="dyn-mem-read-go" style="white-space:nowrap">[ READ ]</button>
          </div>
          <div id="dyn-mem-hex" class="muted small" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px;font-family:'Courier Prime',monospace;white-space:pre-wrap;word-break:break-all"></div>

          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
            <span class="muted small uppercase" style="letter-spacing:2px;width:90px;color:var(--sev-high)">write:</span>
            <input id="dyn-mem-write-addr" class="input t-mono" placeholder="0x1234abcd" style="flex:1;min-width:160px">
            <input id="dyn-mem-write-hex" class="input t-mono" placeholder="65 79 4a 68 …" style="flex:2;min-width:200px">
            <button class="btn" id="dyn-mem-write-go" style="white-space:nowrap;color:var(--sev-high);border-color:var(--sev-high)">[ OVERWRITE ]</button>
          </div>
          <div id="dyn-mem-write-out" class="muted small" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px;white-space:pre-wrap"></div>

          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;border-top:1px dashed var(--border);padding-top:8px">
            <span class="muted small uppercase" style="letter-spacing:2px;width:90px">trace:</span>
            <input id="dyn-mem-trace-addr" class="input t-mono" placeholder="0x10f234000" style="flex:1;min-width:160px">
            <input id="dyn-mem-trace-size" class="input t-mono" type="number" min="1" max="65536" value="256" style="width:90px">
            <button class="btn" id="dyn-mem-trace-go" style="white-space:nowrap" title="Arm a MemoryAccessMonitor — first read/write at this address fires a mem_trace event on the SSE stream">[ ▶ ARM ]</button>
            <button class="btn" id="dyn-mem-trace-stop" style="white-space:nowrap">[ ⏹ STOP ]</button>
            <span class="muted small" id="dyn-mem-trace-status" style="margin-left:8px">idle</span>
          </div>
        </div>
      </section>

      <div class="row muted small" style="justify-content:center;gap:18px;flex-wrap:wrap">
        <a href="#/project/${id}/tracer">live method tracer →</a>
        <a href="#/recipes">+ recipes library</a>
        <a href="#/adb">ADB control panel</a>
      </div>
    </div>`;
}


export { bindProjectTabActions, deviceTabs, fillDeviceStatusStrip, mount_ios_decrypt, projectTabs, view_device_bridge, view_device_pull, view_ios_decrypt, view_project_dynamic, view_project_overview, view_project_static };
