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

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 13b — RUNTIME (Medusa-flavoured introspection, auto-bound to package)
 *
 *  Doesn't replace the Dynamic tab — Dynamic still owns the long-lived
 *  session + console. This screen is the "ad-hoc Medusa command" surface:
 *  enumerate classes, describe a class, install a method tracer, list
 *  modules, log lifecycle. Everything routes back to the server, which
 *  returns a generated Frida script the analyst can copy or auto-load.
 *
 *  Cross-links to existing Nexus features at the bottom so we don't
 *  duplicate the Recipes library, SSL Map, Native Libs viewer, or
 *  Doctor — each gets a 1-click jump.
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_runtime(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase" id="rt-breadcrumb">🔱 NEXUS / ${id} / runtime</div>
      ${projectTabs(id, "runtime")}

      <section class="row" style="gap:10px;align-items:center;flex-wrap:wrap;padding:8px 10px;background:var(--bg-accent-panel);border:1px solid var(--border-accent);border-radius:2px">
        <span class="muted small uppercase" style="letter-spacing:2px">package:</span>
        <span class="t-mono" id="rt-package" style="color:var(--acid)">…</span>
        <span class="spacer"></span>
        <span class="muted small" id="rt-frida-status">checking frida-server…</span>
        <a class="btn" href="#/adb" style="padding:2px 10px">[ DEVICE BRIDGE ]</a>
      </section>

      <div class="row" style="gap:12px;align-items:flex-start;flex-wrap:wrap">
        <section class="panel grow" style="min-width:340px">
          <div class="panel-head"><span>// CLASS TOOLS</span><span class="muted small">enumerate · describe</span></div>
          <div class="panel-body col" style="gap:8px">
            <div class="row" style="gap:6px;flex-wrap:wrap">
              <input id="rt-enum-pattern" class="input t-mono grow" placeholder="filter regex — e.g. .*Cipher.* or com\\.target\\..*" />
              <input id="rt-enum-limit"   class="input t-mono" type="number" min="1" max="5000" value="500" style="width:90px" />
              <button class="btn primary" id="rt-enum-go" style="white-space:nowrap">[ ENUMERATE CLASSES ]</button>
            </div>
            <div class="row" style="gap:6px;flex-wrap:wrap">
              <input id="rt-desc-class" class="input t-mono grow" placeholder="fully-qualified class — e.g. javax.crypto.Cipher" />
              <button class="btn" id="rt-desc-go" style="white-space:nowrap">[ DESCRIBE CLASS ]</button>
            </div>
            <div class="muted small">
              Mirrors Medusa's <code>enumerate classes &lt;pattern&gt;</code> and
              <code>describe_java_class &lt;fqcn&gt;</code>. Output streams into the
              <code>runtime</code> channel via the existing Dynamic session.
            </div>
          </div>
        </section>

        <section class="panel grow" style="min-width:340px">
          <div class="panel-head"><span>// METHOD TRACER (jtrace)</span><span class="muted small">per-call args / return / stack</span></div>
          <div class="panel-body col" style="gap:8px">
            <input id="rt-jt-class"  class="input t-mono" placeholder="class — e.g. com.target.crypto.AESHelper" />
            <input id="rt-jt-method" class="input t-mono" placeholder="method — e.g. encrypt" />
            <div class="row" style="gap:14px;flex-wrap:wrap;font-size:11px">
              <label class="row" style="gap:4px;cursor:pointer"><input type="checkbox" id="rt-jt-args" checked>args</label>
              <label class="row" style="gap:4px;cursor:pointer"><input type="checkbox" id="rt-jt-return" checked>return</label>
              <label class="row" style="gap:4px;cursor:pointer"><input type="checkbox" id="rt-jt-stack">stack trace</label>
            </div>
            <button class="btn primary" id="rt-jt-go" style="white-space:nowrap">[ ▶ INSTALL TRACER ]</button>
          </div>
        </section>
      </div>

      <div class="row" style="gap:12px;align-items:flex-start;flex-wrap:wrap">
        <section class="panel grow" style="min-width:340px">
          <div class="panel-head"><span>// NATIVE MODULES (libs)</span><span class="muted small">Process.enumerateModules</span></div>
          <div class="panel-body col" style="gap:8px">
            <div class="row" style="gap:14px;flex-wrap:wrap;font-size:11px">
              <label class="row" style="gap:4px;cursor:pointer"><input type="checkbox" id="rt-mod-system">include system libs</label>
              <span class="spacer"></span>
              <button class="btn" id="rt-mod-go" style="white-space:nowrap">[ ENUMERATE MODULES ]</button>
            </div>
            <div class="muted small">
              Defaults to <code>/data/app|/data/data</code> only — app-private <code>.so</code> files.
              Tick the box to see Bionic + system libs too.
            </div>
          </div>
        </section>

        <section class="panel grow" style="min-width:340px">
          <div class="panel-head"><span>// LIFECYCLE LOG</span><span class="muted small">spawn-log onCreate</span></div>
          <div class="panel-body col" style="gap:8px">
            <div class="muted small">
              Hooks <code>Application.onCreate</code> + <code>Activity.onCreate</code> so you
              know the script attached before the app started doing work.
            </div>
            <button class="btn" id="rt-life-go" style="white-space:nowrap">[ INSTALL LIFECYCLE LOG ]</button>
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="panel-head">
          <span>// GENERATED SCRIPT</span>
          <span class="spacer"></span>
          <span class="muted small" id="rt-script-hint">pick an action above</span>
          <button class="btn" id="rt-copy" style="padding:2px 10px;display:none">[ COPY ]</button>
          <button class="btn primary" id="rt-load" style="padding:2px 10px;display:none">[ ▶ LOAD INTO DYNAMIC SESSION ]</button>
        </div>
        <div class="panel-body" style="padding:0">
          <pre id="rt-script" style="margin:0;padding:12px;background:#050505;color:var(--cyan);font-family:inherit;font-size:11px;max-height:340px;overflow:auto;white-space:pre">// generated Frida script will appear here</pre>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <span>// LIVE EVENTS (runtime channel)</span>
          <span class="spacer"></span>
          <span class="muted small" id="rt-events-meta">—</span>
        </div>
        <div class="panel-body col" style="gap:4px" id="rt-events">
          <div class="muted small">Load a script into a Dynamic session and the runtime-channel events will stream here.</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><span>// MANGO TOOLBOX</span><span class="muted small">deeplink fire · flag decoder · manifest diff</span></div>
        <div class="panel-body col" style="gap:12px">
          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:110px">deeplink:</span>
            <select id="rt-mango-dl" class="input t-mono" style="flex:1;min-width:240px">
              <option value="">loading deeplinks…</option>
            </select>
            <button class="btn primary" id="rt-mango-dl-fire" style="white-space:nowrap" title="adb shell am start -a VIEW -d <uri>">[ ▶ FIRE ON DEVICE ]</button>
            <button class="btn" id="rt-mango-dl-poc" style="white-space:nowrap" title="download a one-click HTML page that fires this deeplink">[ HTML POC ]</button>
          </div>
          <div class="muted small" id="rt-mango-dl-out" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px;white-space:pre-wrap;font-family:inherit"></div>

          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:110px">decode flag:</span>
            <input id="rt-mango-flag" class="input t-mono" placeholder="0x10000004 · 268435460 · 0b1010" style="flex:1;min-width:200px">
            <button class="btn primary" id="rt-mango-flag-go" style="white-space:nowrap">[ DECODE ]</button>
          </div>
          <div id="rt-mango-flag-out" class="muted small" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px"></div>

          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:110px">version diff:</span>
            <a class="btn" id="rt-mango-diff-link" href="#" style="white-space:nowrap">[ → MANIFEST DIFF AGAINST PRIOR SCAN ]</a>
            <a class="btn" id="rt-mango-findings-diff-link" href="#" style="white-space:nowrap">[ → FINDINGS DIFF ]</a>
            <span class="muted small">manifest diff = surface changes · findings diff = security changes</span>
          </div>

          <div class="row" style="gap:8px;align-items:flex-start;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:110px;padding-top:6px">patch apk:</span>
            <div class="col" style="gap:6px;flex:1;min-width:280px">
              <label class="row small" style="gap:6px;align-items:center;cursor:pointer">
                <input type="checkbox" data-patch="user_ca_trust" checked>
                <span><b style="color:var(--cyan)">user_ca_trust</b> — trust user-installed CAs (unblocks Burp/Caido/Moxy)</span>
              </label>
              <label class="row small" style="gap:6px;align-items:center;cursor:pointer">
                <input type="checkbox" data-patch="debuggable">
                <span><b style="color:var(--cyan)">debuggable</b> — flip android:debuggable=true (jdb attach)</span>
              </label>
              <label class="row small" style="gap:6px;align-items:center;cursor:pointer">
                <input type="checkbox" data-patch="cleartext_traffic">
                <span><b style="color:var(--cyan)">cleartext_traffic</b> — allow plain HTTP</span>
              </label>
            </div>
            <button class="btn primary" id="rt-mango-patch-go" style="white-space:nowrap" title="apktool + apksigner under the hood; produces a re-signed APK in the workspace">[ ▶ PATCH APK ]</button>
          </div>
          <div id="rt-mango-patch-out" class="muted small" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px;white-space:pre-wrap"></div>

          <!-- IPA patch panel — only mounted for iOS projects (toggled by mount fn) -->
          <div id="rt-mango-ipa-block" style="display:none">
            <div class="row" style="gap:8px;align-items:flex-start;flex-wrap:wrap">
              <span class="muted small uppercase" style="letter-spacing:2px;width:110px;padding-top:6px;color:var(--magenta)">patch ipa:</span>
              <div class="col" style="gap:6px;flex:1;min-width:280px">
                <div class="muted small">
                  Mach-O byte patcher. Reads the file offset from your disassembler
                  (Ghidra's Offset column / Hopper's File offset) and overwrites bytes.
                  See <a href="https://github.com/jacksonfdam/medusa-nexus/blob/main/docs/IOS.md" target="_blank">docs/IOS.md</a> for the workflow.
                </div>
                <div class="row small" style="gap:6px;align-items:center">
                  <select id="rt-ipa-patch-kind" class="input t-mono" style="min-width:240px">
                    <option value="return_zero_at_offset">return_zero_at_offset (mov x0,#0; ret)</option>
                    <option value="nop_at_offset">nop_at_offset (NOPs × count)</option>
                    <option value="inject_load_dylib">inject_load_dylib (LC_LOAD_DYLIB)</option>
                  </select>
                  <select id="rt-ipa-patch-addrkind" class="input t-mono" title="va = Ghidra's Address column; offset = Ghidra's Offset column">
                    <option value="offset">offset (file)</option>
                    <option value="va">va (virtual)</option>
                  </select>
                  <input id="rt-ipa-patch-offset" class="input t-mono" placeholder="0x100123456" style="flex:1;min-width:140px">
                  <input id="rt-ipa-patch-count" class="input t-mono" type="number" min="1" max="64" value="1" title="NOP count (return_zero ignores)" style="width:80px">
                  <button class="btn" id="rt-ipa-patch-add" style="white-space:nowrap">[ + ADD ]</button>
                </div>
                <div id="rt-ipa-patch-queue" class="col" style="gap:3px;font-size:11px;color:var(--muted)"></div>
              </div>
              <button class="btn primary" id="rt-ipa-patch-go" style="white-space:nowrap;border-color:var(--magenta)" title="ldid -S preferred; codesign --force --sign - as fallback">[ ▶ PATCH IPA ]</button>
            </div>
            <div id="rt-ipa-patch-out" class="muted small" style="display:none;padding:6px 8px;background:#050505;border:1px solid var(--border);border-radius:2px;white-space:pre-wrap;font-family:'Courier Prime',monospace;max-height:200px;overflow:auto"></div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><span>// REUSE WHAT NEXUS ALREADY HAS</span></div>
        <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
          <a class="btn" href="#/recipes">[ RECIPES LIBRARY ]</a>
          <a class="btn" href="#/project/${id}/dynamic">[ DYNAMIC SESSION ]</a>
          <a class="btn" href="#/project/${id}/ssl-map">[ SSL MAP ]</a>
          <a class="btn" href="#/project/${id}/static/native">[ NATIVE LIBS (static) ]</a>
          <a class="btn" href="#/project/${id}/network">[ NETWORK ]</a>
          <a class="btn" href="#/doctor">[ DOCTOR ]</a>
          <span class="spacer"></span>
          <span class="muted small">avoiding duplication — Medusa modules + frida-server + recipes live in the panels above.</span>
        </div>
      </section>
    </div>`;
}

async function mount_project_runtime(ctx) {
    const id = ctx.params.id;
    const project = await getJSON(`/v1/projects/${encodeURIComponent(id)}`).catch(() => null);
    if (!project) {
        const view = $(".main");
        if (view) view.innerHTML += `<div class="empty-state"><span style="color:var(--sev-crit)">project ${id} not found</span></div>`;
        return;
    }
    const pkg = project.package_name || "";
    $("#rt-package").textContent = pkg || "—";

    // Frida-server liveness — reuse the existing /v1/device/info endpoint.
    try {
        const info = await getJSON("/v1/device/info");
        const ok = info && info.connected && info.frida_server_running;
        const statusEl = $("#rt-frida-status");
        if (statusEl) {
            statusEl.innerHTML = ok
                ? `<span style="color:var(--acid)">● frida-server up</span> · ${escapeHtml(info.abi || "")}`
                : info && info.connected
                    ? `<span style="color:var(--sev-high)">● frida-server not running</span> — start via /#/adb`
                    : `<span style="color:var(--sev-crit)">● no device</span>`;
        }
    } catch (_) { /* leave the badge as-is */ }

    // Last-generated state so [ COPY ] / [ LOAD ] know what to do.
    let lastScript = "";
    let lastAction = "";

    const render = (out) => {
        if (!out || !out.script) return;
        lastScript = out.script;
        lastAction = out.action;
        $("#rt-script").textContent = out.script;
        $("#rt-script-hint").textContent = `${out.action} · ${out.hint || ""}`;
        $("#rt-copy").style.display = "";
        $("#rt-load").style.display = "";
    };

    const post = async (action, params) => {
        const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/runtime/script`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, params }),
        });
        if (!r.ok) { alert(`[${r.status}] ${(await r.text()).slice(0, 200)}`); return; }
        render(await r.json());
    };

    $("#rt-enum-go").addEventListener("click", () => post("enumerate_classes", {
        pattern: $("#rt-enum-pattern").value || ".*",
        limit:   parseInt($("#rt-enum-limit").value || "500", 10),
    }));
    $("#rt-desc-go").addEventListener("click", () => {
        const c = ($("#rt-desc-class").value || "").trim();
        if (!c) { alert("enter a class name first"); return; }
        post("describe_class", { class: c });
    });
    $("#rt-jt-go").addEventListener("click", () => {
        const c = ($("#rt-jt-class").value || "").trim();
        const m = ($("#rt-jt-method").value || "").trim();
        if (!c || !m) { alert("class + method required"); return; }
        post("jtrace_method", {
            class: c, method: m,
            log_args:   $("#rt-jt-args").checked,
            log_return: $("#rt-jt-return").checked,
            log_stack:  $("#rt-jt-stack").checked,
        });
    });
    $("#rt-mod-go").addEventListener("click", () => post("enumerate_modules", {
        include_system: $("#rt-mod-system").checked,
    }));
    $("#rt-life-go").addEventListener("click", () => post("spawn_log", {}));

    // ── MANGO TOOLBOX ──────────────────────────────────────────────────
    // Populate the deeplink picker from the project's surface so the
    // analyst doesn't have to copy URIs around. Falls back to a free-text
    // input when the project never had deeplinks recovered.
    const surface = (project.attack_surface || {});
    const allDeeplinks = [
        ...(surface.deeplinks || []),
        ...((surface.url_schemes || []).map((s) => `${s}://`)),
    ];
    const dlSel = $("#rt-mango-dl");
    if (allDeeplinks.length) {
        dlSel.innerHTML = allDeeplinks.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join("");
    } else {
        // No deeplinks discovered statically → swap the select for a text
        // input so the analyst can still test arbitrary URIs.
        const replacement = document.createElement("input");
        replacement.id = "rt-mango-dl";
        replacement.className = "input t-mono";
        replacement.placeholder = "myapp://path  ·  https://app.target.com/…";
        replacement.style.flex = "1";
        replacement.style.minWidth = "240px";
        dlSel.replaceWith(replacement);
    }

    const dlOut = $("#rt-mango-dl-out");
    $("#rt-mango-dl-fire").addEventListener("click", async () => {
        const cur = $("#rt-mango-dl");
        const uri = (cur && (cur.value || "")).trim();
        if (!uri) { alert("pick or type a deeplink first"); return; }
        dlOut.style.display = "";
        dlOut.style.color = "var(--cyan)";
        dlOut.textContent = `firing ${uri}…`;
        try {
            const form = new FormData(); form.append("uri", uri);
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/mango/deeplink/fire`, { method: "POST", body: form });
            const j = await r.json().catch(() => null);
            if (!r.ok) throw new Error((j && j.detail) || r.statusText);
            dlOut.style.color = j.fired ? "var(--acid)" : "var(--sev-high)";
            dlOut.textContent = j.fired
                ? `✓ resolved to ${j.activity}\n\n${j.raw}`
                : `! am didn't resolve an Activity — the URI may not be exported, or the app isn't installed.\n\n${j.raw}`;
        } catch (e) {
            dlOut.style.color = "var(--sev-crit)";
            dlOut.textContent = `request failed: ${e.message || e}`;
        }
    });
    $("#rt-mango-dl-poc").addEventListener("click", () => {
        const cur = $("#rt-mango-dl");
        const uri = (cur && (cur.value || "")).trim();
        if (!uri) { alert("pick or type a deeplink first"); return; }
        // Open the HTML PoC in a new tab so the analyst can save / share it.
        window.open(`/v1/projects/${encodeURIComponent(id)}/mango/deeplink/poc?uri=${encodeURIComponent(uri)}`, "_blank");
    });

    // Flag decoder
    const flagOut = $("#rt-mango-flag-out");
    $("#rt-mango-flag-go").addEventListener("click", async () => {
        const value = ($("#rt-mango-flag").value || "").trim();
        if (!value) { alert("paste a flag value first"); return; }
        flagOut.style.display = "";
        flagOut.textContent = "decoding…";
        try {
            const r = await fetch("/v1/mango/decode-flags", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ value }),
            });
            const j = await r.json().catch(() => null);
            if (!r.ok) throw new Error((j && j.detail) || r.statusText);
            const blocks = Object.entries(j.decoded).map(([ns, names]) => `
                <div style="margin-bottom:6px">
                  <span class="muted small uppercase">${escapeHtml(ns)}</span>
                  ${names.length
                    ? `<div class="t-mono small" style="color:var(--cyan);padding-left:8px">${names.map(escapeHtml).join("<br>")}</div>`
                    : `<div class="t-mono small" style="color:var(--muted);padding-left:8px">— no flags matched —</div>`
                  }
                </div>`).join("");
            flagOut.innerHTML = `<div class="t-mono small" style="color:var(--acid);margin-bottom:6px">${j.hex} · ${j.value}</div>${blocks}`;
        } catch (e) {
            flagOut.style.color = "var(--sev-crit)";
            flagOut.textContent = `request failed: ${e.message || e}`;
        }
    });

    // Manifest diff link — auto-points at /manifest-diff which the
    // backend resolves to the latest prior scan of the same package.
    $("#rt-mango-diff-link").addEventListener("click", (e) => {
        e.preventDefault();
        location.hash = `#/project/${id}/manifest-diff`;
    });
    $("#rt-mango-findings-diff-link")?.addEventListener("click", (e) => {
        e.preventDefault();
        location.hash = `#/project/${id}/findings-diff`;
    });

    // APK patcher — POST /v1/projects/<id>/patch with the selected
    // checkboxes, render the result inline (path + warnings + skipped).
    const patchOut = $("#rt-mango-patch-out");
    $("#rt-mango-patch-go").addEventListener("click", async () => {
        const selected = [];
        $$('input[data-patch]').forEach((cb) => { if (cb.checked) selected.push(cb.dataset.patch); });
        if (!selected.length) {
            alert("pick at least one patch (user_ca_trust is usually enough)");
            return;
        }
        const btn = $("#rt-mango-patch-go");
        const orig = btn.textContent;
        btn.textContent = "[ PATCHING… ]";
        btn.disabled = true;
        patchOut.style.display = "";
        patchOut.style.color = "var(--cyan)";
        patchOut.textContent = `patching with: ${selected.join(", ")}…`;
        try {
            const fd = new FormData(); fd.append("patches", selected.join(","));
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/patch`, { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) throw new Error((j && j.detail) || r.statusText);
            const lines = [];
            if (j.preview) {
                lines.push("preview mode — apktool isn't installed on the server, no APK produced.");
            } else if (j.patched_path) {
                lines.push(`✓ patched APK at ${j.patched_path}`);
            }
            if (j.patches_applied && j.patches_applied.length) {
                lines.push(`applied: ${j.patches_applied.join(", ")}`);
            }
            if (j.patches_skipped && j.patches_skipped.length) {
                lines.push(`skipped: ${j.patches_skipped.map((s) => s.name + " (" + s.reason + ")").join(" · ")}`);
            }
            if (j.warnings && j.warnings.length) {
                lines.push("warnings:");
                j.warnings.forEach((w) => lines.push("  · " + w));
            }
            patchOut.style.color = j.preview ? "var(--magenta)" : "var(--acid)";
            patchOut.textContent = lines.join("\n");
            btn.textContent = "[ ✓ DONE ]";
            btn.style.color = "var(--acid)";
            btn.disabled = false;
            setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 6000);
        } catch (e) {
            patchOut.style.color = "var(--sev-crit)";
            patchOut.textContent = `request failed: ${e.message || e}`;
            btn.textContent = "[ FAILED ]";
            btn.style.color = "var(--sev-crit)";
            btn.disabled = false;
        }
    });

    // IPA patch panel — only visible for iOS projects. Mounts a small
    // queue editor (one patch entry per row) + dispatch to /ios/patch.
    if ((project && project.platform) === "ios") {
        const block = $("#rt-mango-ipa-block");
        if (block) {
            block.style.display = "";
            // Swap the manifest-diff label on iOS so the analyst doesn't
            // think the surface diff is the iOS Mach-O patch.
            const queue = [];  // [{name, offset, count?}]
            const queueEl = $("#rt-ipa-patch-queue");
            const renderQueue = () => {
                if (!queue.length) {
                    queueEl.innerHTML = `<span class="muted small">no patches queued — add one above</span>`;
                    return;
                }
                queueEl.innerHTML = queue.map((p, i) => {
                    const addrLabel = p.va ? `va=${p.va}` : `offset=${p.offset}`;
                    return `
                    <div class="row small" style="gap:6px;align-items:center;padding:2px 0">
                      <span class="t-mono" style="color:var(--cyan);flex:1">${escapeHtml(p.name)} ${escapeHtml(addrLabel)}${p.count ? " ×" + p.count : ""}</span>
                      <a href="#" data-rm="${i}" class="muted small">[ × ]</a>
                    </div>`;
                }).join("");
                $$('[data-rm]').forEach((a) => a.addEventListener("click", (e) => {
                    e.preventDefault();
                    queue.splice(parseInt(a.dataset.rm, 10), 1);
                    renderQueue();
                }));
            };
            renderQueue();

            $("#rt-ipa-patch-add").addEventListener("click", () => {
                const kind = $("#rt-ipa-patch-kind").value;
                const addrKind = ($("#rt-ipa-patch-addrkind") || {}).value || "offset";
                const addr = ($("#rt-ipa-patch-offset").value || "").trim();
                const count = parseInt($("#rt-ipa-patch-count").value || "1", 10);
                if (!addr) { alert(`${addrKind} required (hex like 0x100123456 or decimal)`); return; }
                const entry = { name: kind };
                entry[addrKind] = addr;   // 'offset' or 'va'
                if (kind === "nop_at_offset") entry.count = count;
                queue.push(entry);
                $("#rt-ipa-patch-offset").value = "";
                renderQueue();
            });

            const ipaOut = $("#rt-ipa-patch-out");
            $("#rt-ipa-patch-go").addEventListener("click", async () => {
                if (!queue.length) { alert("add at least one patch first"); return; }
                if (!confirm(`Patch ${queue.length} byte location(s) and re-sign the IPA?\nMistakes can crash the app — keep the previous_hex echoes for rollback.`)) return;
                const btn2 = $("#rt-ipa-patch-go");
                const orig2 = btn2.textContent;
                btn2.textContent = "[ PATCHING… ]";
                btn2.disabled = true;
                ipaOut.style.display = "";
                ipaOut.style.color = "var(--cyan)";
                ipaOut.textContent = `patching ${queue.length} location(s)…`;
                try {
                    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/ios/patch`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ patches: queue }),
                    });
                    const j = await r.json();
                    if (!r.ok) throw new Error((j && j.detail) || r.statusText);
                    const lines = [];
                    if (j.patched_path) lines.push(`✓ patched IPA · ${j.patched_path}`);
                    if (j.signing_tool) lines.push(`  signed with ${j.signing_tool}`);
                    if (j.patches_applied && j.patches_applied.length) {
                        lines.push("applied:");
                        j.patches_applied.forEach((p) => lines.push(
                            `  · ${p.name}@${p.offset} · ${p.bytes_written}B · rollback: ${p.previous_hex || "<unreadable>"}`
                        ));
                    }
                    if (j.patches_skipped && j.patches_skipped.length) {
                        lines.push("skipped:");
                        j.patches_skipped.forEach((s) => lines.push(`  · ${s.name}@${s.offset} · ${s.reason}`));
                    }
                    (j.warnings || []).forEach((w) => lines.push("  warn: " + w));
                    ipaOut.style.color = "var(--acid)";
                    ipaOut.textContent = lines.join("\n");
                    btn2.textContent = "[ ✓ DONE ]";
                    btn2.style.color = "var(--acid)";
                    btn2.disabled = false;
                    setTimeout(() => { btn2.textContent = orig2; btn2.style.color = ""; }, 6000);
                    // Clear the queue so a second click doesn't re-patch.
                    queue.length = 0;
                    renderQueue();
                } catch (e) {
                    ipaOut.style.color = "var(--sev-crit)";
                    ipaOut.textContent = `patch failed: ${e.message || e}`;
                    btn2.textContent = "[ FAILED ]";
                    btn2.style.color = "var(--sev-crit)";
                    btn2.disabled = false;
                }
            });
        }
    }

    $("#rt-copy").addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(lastScript);
            $("#rt-copy").textContent = "[ ✓ COPIED ]";
            setTimeout(() => { $("#rt-copy").textContent = "[ COPY ]"; }, 1500);
        } catch (e) { alert("clipboard blocked — select the script manually"); }
    });

    $("#rt-load").addEventListener("click", async () => {
        const btn = $("#rt-load");
        const orig = btn.textContent;
        btn.disabled = true;
        btn.textContent = "[ LOADING… ]";
        try {
            // The Dynamic session POST accepts a hooks list — we pass the
            // action name so the session log carries something readable.
            // The actual script body lives in 'script_body' (the Dynamic
            // endpoint ignores it today; a future enhancement will pass it
            // through to the Frida session manager). For now this hand-off
            // mostly serves as a UI affordance + a hint that the Recipes
            // library is the canonical home for stable hooks.
            const form = new FormData();
            form.append("hooks", `runtime:${lastAction}`);
            form.append("script_body", lastScript);
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/dynamic/start`, {
                method: "POST", body: form,
            });
            if (!r.ok) throw new Error(`[${r.status}] ${(await r.text()).slice(0, 200)}`);
            const j = await r.json();
            btn.textContent = `[ ✓ SESSION ${j.session_id} ]`;
            btn.style.color = "var(--acid)";
            // Bring the user to the Dynamic tab so they see the console.
            setTimeout(() => { location.hash = `#/project/${id}/dynamic`; }, 800);
        } catch (e) {
            btn.textContent = "[ FAILED ]";
            btn.style.color = "var(--sev-crit)";
            btn.title = String(e);
            btn.disabled = false;
            setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 3500);
        }
    });

    // Live runtime events — poll /v1/projects/{id}/dynamic/events every 3s
    // and pick out channel === 'runtime' rows. Reuses pollingScope so it
    // tears down cleanly on navigate-away.
    pollingScope(async () => {
        const ev = await getJSON(`/v1/projects/${encodeURIComponent(id)}/dynamic/events`).catch(() => null);
        if (!ev || !ev.log) return;
        const rows = ev.log.filter((e) => (e.channel || e.kind || "") === "runtime");
        $("#rt-events-meta").textContent = `${rows.length} runtime event(s)`;
        const out = $("#rt-events");
        if (!rows.length) {
            out.innerHTML = `<div class="muted small">no runtime events yet — install a tracer or load an action.</div>`;
            return;
        }
        out.innerHTML = rows.slice(-100).reverse().map((e) => {
            const kind = (e.kind || (e.payload && e.payload.kind) || "?");
            const body = JSON.stringify(e.payload || e, null, 0).slice(0, 280);
            return `<div class="t-mono small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                      <span style="color:var(--magenta)">[${escapeHtml(kind)}]</span> ${escapeHtml(body)}
                    </div>`;
        }).join("");
    }, 3000);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 13c — MANIFEST DIFF (Mango's `diff`, structured)
 *
 *  Mango compares raw AndroidManifest XML across stored sessions; we
 *  compare the AttackSurface dict we already keep, which is far more
 *  useful: per-component export/permission deltas, deeplink + permission
 *  set diffs, SSL pinning posture change.
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_manifest_diff(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / manifest-diff</div>
      ${projectTabs(id, "static")}
      <section class="panel">
        <div class="panel-head">
          <span>// MANIFEST DIFF</span>
          <span class="spacer"></span>
          <span class="muted small" id="md-summary">loading…</span>
        </div>
        <div class="panel-body col" style="gap:12px" id="md-body">
          <div class="muted small">resolving prior scan of the same package…</div>
        </div>
      </section>
    </div>`;
}

async function mount_project_manifest_diff(ctx) {
    const id = ctx.params.id;
    let data;
    try {
        data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/manifest-diff`);
    } catch (e) {
        $("#md-body").innerHTML = `<div class="empty-state"><span style="color:var(--sev-crit)">${escapeHtml(e.message || String(e))}</span></div>`;
        return;
    }
    const summary = data.diff && data.diff.summary || {};
    $("#md-summary").innerHTML = data.base
        ? `<span class="t-mono">${escapeHtml(data.base.version_name || "?")} → ${escapeHtml(data.head.version_name || "?")}</span>`
        : `<span style="color:var(--magenta)">no prior scan of ${escapeHtml(data.package || "?")}</span>`;

    const body = $("#md-body");
    if (data.base === null) {
        body.innerHTML = `
          <div class="empty-state">
            <div style="color:var(--magenta);font-size:18px;letter-spacing:2px">NO PRIOR SCAN</div>
            <div class="muted small">${escapeHtml(data.note || "Scan another version of this package first.")}</div>
          </div>`;
        return;
    }

    const _row = (cls, label, items, render) => {
        if (!items || !items.length) return "";
        return `
          <div style="margin-bottom:10px">
            <div class="muted small uppercase" style="letter-spacing:2px;margin-bottom:4px">
              <span style="color:var(--${cls})">${escapeHtml(label)}</span> · ${items.length}
            </div>
            <div class="col" style="gap:3px;padding-left:8px">${items.map(render).join("")}</div>
          </div>`;
    };
    const _comp = (c) => `<div class="t-mono small">
        <span class="chip ${c.unprotected ? "high" : "info"}" style="font-size:9px;letter-spacing:1px">${escapeHtml((c.component_type || "?").toUpperCase().slice(0,3))}</span>
        ${escapeHtml(c.name || "?")}
        ${c.unprotected ? `<span class="muted small" style="color:var(--sev-high)">unprotected</span>` : ""}
      </div>`;
    const _changed = (c) => `<div class="t-mono small">
        <span class="chip info" style="font-size:9px">${escapeHtml(c.type ? c.type.toUpperCase().slice(0,3) : "?")}</span>
        ${escapeHtml(c.name)} <span class="muted small">${c.fields.join(", ")}</span>
        <div style="padding-left:14px;color:var(--muted)" class="small">before: ${escapeHtml(JSON.stringify(c.before))}<br>after: ${escapeHtml(JSON.stringify(c.after))}</div>
      </div>`;
    const _str = (s) => `<div class="t-mono small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(s)}">${escapeHtml(s)}</div>`;

    const d = data.diff || {};
    const sections = [
        _row("acid", "components — added", d.components && d.components.added, _comp),
        _row("sev-crit", "components — removed", d.components && d.components.removed, _comp),
        _row("magenta", "components — changed", d.components && d.components.changed, _changed),
        _row("acid", "deeplinks — added", d.deeplinks && d.deeplinks.added, _str),
        _row("sev-crit", "deeplinks — removed", d.deeplinks && d.deeplinks.removed, _str),
        _row("acid", "permissions — added", d.permissions && d.permissions.added, _str),
        _row("sev-crit", "permissions — removed", d.permissions && d.permissions.removed, _str),
        _row("acid", "url schemes — added", d.url_schemes && d.url_schemes.added, _str),
        _row("sev-crit", "url schemes — removed", d.url_schemes && d.url_schemes.removed, _str),
    ];
    const ssl = d.ssl_pinning || {};
    if (summary.ssl_pinning_changed) {
        sections.push(`
          <div style="margin-bottom:10px">
            <div class="muted small uppercase" style="letter-spacing:2px;margin-bottom:4px"><span style="color:var(--magenta)">ssl pinning — changed</span></div>
            <div class="t-mono small" style="padding-left:8px">
              before: ${ssl.detected_before ? "<span style=\"color:var(--sev-high)\">detected</span> · " + escapeHtml(ssl.library_before || "?") : "<span style=\"color:var(--acid)\">none</span>"}
              <br>after:  ${ssl.detected_after  ? "<span style=\"color:var(--sev-high)\">detected</span> · " + escapeHtml(ssl.library_after  || "?") : "<span style=\"color:var(--acid)\">none</span>"}
            </div>
          </div>`);
    }
    body.innerHTML = `
      <div class="row small" style="gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11px">
        <span>base: <span class="t-mono" style="color:var(--cyan)">${escapeHtml(data.base.id)}</span> · ${escapeHtml(data.base.version_name || "?")}</span>
        <span>head: <span class="t-mono" style="color:var(--acid)">${escapeHtml(data.head.id)}</span> · ${escapeHtml(data.head.version_name || "?")}</span>
        <span class="spacer"></span>
        <span>${summary.any_changes ? "<span style=\"color:var(--magenta)\">changes detected</span>" : "<span style=\"color:var(--acid)\">identical</span>"}</span>
      </div>
      ${summary.any_changes ? sections.join("") : `<div class="empty-state">no manifest-level changes between these versions.</div>`}`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 13d — FINDINGS DIFF (security delta between two versions)
 *
 *  Complements manifest-diff: where that one compares the static
 *  surface (components / deeplinks / permissions), this one compares
 *  the actual Findings. Useful for 'did v1.3 actually fix CVE-…?'
 *  questions during release-gate reviews.
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_findings_diff(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / findings-diff</div>
      ${projectTabs(id, "static")}
      <section class="panel">
        <div class="panel-head">
          <span>// FINDINGS DIFF</span>
          <span class="spacer"></span>
          <span class="muted small" id="fd-summary">loading…</span>
        </div>
        <div class="panel-body col" style="gap:12px" id="fd-body">
          <div class="muted small">resolving prior scan of the same package…</div>
        </div>
      </section>
    </div>`;
}

async function mount_project_findings_diff(ctx) {
    const id = ctx.params.id;
    let data;
    try {
        data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/findings-diff`);
    } catch (e) {
        $("#fd-body").innerHTML = `<div class="empty-state"><span style="color:var(--sev-crit)">${escapeHtml(e.message || String(e))}</span></div>`;
        return;
    }
    const diff = data.diff || {};
    const summary = diff.summary || {};

    $("#fd-summary").innerHTML = data.base
        ? `<span class="t-mono">${escapeHtml(data.base.version_name || "?")} → ${escapeHtml(data.head.version_name || "?")}</span>`
        : `<span style="color:var(--magenta)">no prior scan of ${escapeHtml(data.package || "?")}</span>`;

    const body = $("#fd-body");
    if (data.base === null) {
        body.innerHTML = `
          <div class="empty-state">
            <div style="color:var(--magenta);font-size:18px;letter-spacing:2px">NO PRIOR SCAN</div>
            <div class="muted small">${escapeHtml(data.note || "Scan another version of this package first.")}</div>
          </div>`;
        return;
    }

    const _finding = (f) => `
      <div class="finding" style="cursor:default;padding:6px 10px">
        <div class="head">
          ${chip((f.severity || "info").toLowerCase())}
          <span class="tag">${escapeHtml(f.id || "?")}</span>
          <span class="spacer"></span>
          <span class="tag">[${escapeHtml(f.source_engine || "?")}]</span>
        </div>
        <div class="title">${escapeHtml(f.title || "?")}</div>
        <div class="meta">${escapeHtml(f.location || "—")}${f.cwe_id ? " · " + escapeHtml(f.cwe_id) : ""}${f.masvs ? " · " + escapeHtml(f.masvs) : ""}</div>
      </div>`;

    const _changed = (c) => `
      <div class="finding" style="cursor:default;padding:6px 10px">
        <div class="head">
          ${chip((c.after.severity || "info").toLowerCase())}
          <span class="tag">${escapeHtml(c.after.id || "?")}</span>
          <span class="spacer"></span>
          <span class="muted small">${c.fields.map((x) => escapeHtml(x)).join(", ")}</span>
        </div>
        <div class="title">${escapeHtml(c.after.title || "?")}</div>
        ${c.fields.includes("severity") ? `<div class="muted small">severity: <span style="color:var(--sev-${(c.before.severity || "info").toLowerCase()})">${escapeHtml((c.before.severity || "info").toUpperCase())}</span> → <span style="color:var(--sev-${(c.after.severity || "info").toLowerCase()})">${escapeHtml((c.after.severity || "info").toUpperCase())}</span></div>` : ""}
        ${c.fields.includes("remediation") ? `<div class="muted small" style="margin-top:4px;white-space:pre-wrap">remediation diff:\nbefore: ${escapeHtml((c.before.remediation || "—").slice(0, 240))}\nafter:  ${escapeHtml((c.after.remediation || "—").slice(0, 240))}</div>` : ""}
      </div>`;

    const _section = (cls, label, items, render) => {
        if (!items || !items.length) return "";
        return `
          <div style="margin-bottom:12px">
            <div class="muted small uppercase" style="letter-spacing:2px;margin-bottom:6px">
              <span style="color:var(--${cls})">${escapeHtml(label)}</span> · ${items.length}
            </div>
            <div class="col" style="gap:6px;padding-left:6px">${items.map(render).join("")}</div>
          </div>`;
    };

    const headerLine = `
      <div class="row small" style="gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11px">
        <span>base: <span class="t-mono" style="color:var(--cyan)">${escapeHtml(data.base.id)}</span> · ${escapeHtml(data.base.version_name || "?")}</span>
        <span>head: <span class="t-mono" style="color:var(--acid)">${escapeHtml(data.head.id)}</span> · ${escapeHtml(data.head.version_name || "?")}</span>
        <span class="spacer"></span>
        <span>${summary.any_changes ? "<span style=\"color:var(--magenta)\">changes detected</span>" : "<span style=\"color:var(--acid)\">identical</span>"}</span>
      </div>
      <div class="row small" style="gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11px">
        <span><span class="muted">added</span> <b style="color:var(--sev-crit)">${summary.added_count || 0}</b></span>
        <span><span class="muted">removed</span> <b style="color:var(--acid)">${summary.removed_count || 0}</b></span>
        <span><span class="muted">changed</span> <b style="color:var(--magenta)">${summary.changed_count || 0}</b></span>
        <span><span class="muted">escalated</span> <b style="color:var(--sev-crit)">${summary.severity_escalated || 0}</b></span>
        <span><span class="muted">relieved</span> <b style="color:var(--sev-low)">${summary.severity_relieved || 0}</b></span>
      </div>`;

    body.innerHTML = headerLine + (summary.any_changes
        ? _section("sev-crit", "added in head — new issues",  diff.added,   _finding)
          + _section("acid",   "removed since base — fixed", diff.removed, _finding)
          + _section("magenta","changed (severity / remediation / evidence)", diff.changed, _changed)
        : `<div class="empty-state">no finding-level changes between these versions.</div>`);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 14 — Network Analysis (real attack-surface + traffic)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_network(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase" id="net-breadcrumb">🔱 NEXUS / ${id} / network</div>
      ${projectTabs(id, "network")}

      <section class="row" style="gap:12px;flex-wrap:wrap">
        <div class="metric-card grow" style="min-width:180px">
          <div class="metric-label">// API ENDPOINTS</div>
          <div class="metric-value" id="net-endpoints-count">—</div>
          <div class="metric-sub" id="net-endpoints-sub">discovered statically</div>
        </div>
        <div class="metric-card grow" style="min-width:180px">
          <div class="metric-label">// CAPTURED TRAFFIC</div>
          <div class="metric-value" id="net-traffic-count">—</div>
          <div class="metric-sub" id="net-traffic-sub">via Burp / Moxy / mitm</div>
        </div>
        <div class="metric-card grow" style="min-width:180px">
          <div class="metric-label">// SSL PINNING</div>
          <div class="metric-value" id="net-ssl">—</div>
          <div class="metric-sub" id="net-ssl-sub">library</div>
        </div>
        <div class="metric-card grow" style="min-width:180px">
          <div class="metric-label">// CLEARTEXT</div>
          <div class="metric-value" id="net-cleartext">—</div>
          <div class="metric-sub" id="net-cleartext-sub">manifest flag</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <span>// API ENDPOINTS</span>
          <span class="spacer"></span>
          <a class="btn primary" href="#/project/${id}/api-map">[ FULL MAP ]</a>
          <a class="btn" href="#/project/${id}/ssl-map">[ SSL MAP ]</a>
        </div>
        <div class="panel-body" id="net-endpoints">loading…</div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <span>// CAPTURED TRAFFIC</span>
          <span class="spacer"></span>
          <span class="muted small" id="net-traffic-meta">—</span>
          <button class="btn" id="net-traffic-refresh" style="padding:2px 10px;font-size:10px">[ ⟳ REFRESH ]</button>
        </div>
        <div class="panel-body tight col" style="gap:6px">
          <div class="row" id="net-traffic-controls" style="gap:8px;align-items:center;flex-wrap:wrap;padding:6px 8px;background:var(--bg-accent-panel);border:1px solid var(--border-accent);border-radius:2px;font-size:10px">
            <span class="muted uppercase">moxy workspace:</span>
            <select id="net-moxy-project" class="t-mono" style="background:var(--bg-base);color:var(--cyan);border:1px solid var(--border);padding:2px 6px;font-family:inherit;font-size:10px"></select>
            <label class="row" style="gap:6px;cursor:pointer">
              <input type="checkbox" id="net-moxy-match-only">
              <span>matches-only</span>
            </label>
            <span class="spacer"></span>
            <span class="muted t-mono" id="net-moxy-status">—</span>
          </div>
          <div id="net-traffic">loading…</div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">// NETWORK FINDINGS</div>
        <div class="panel-body col" style="gap:8px" id="net-findings">loading…</div>
      </section>

      ${_exports_panel(id)}
    </div>`;
}

function view_project_report(ctx) {
    // Jump to main Report screen with context.
    location.hash = "#/report?project=" + encodeURIComponent(ctx.params.id || "");
    return view_report(ctx);
}

