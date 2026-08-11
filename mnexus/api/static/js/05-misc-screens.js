// ── auto-wired ES-module imports ──
import { $, AVAILABLE_THEMES, getJSON, getTheme, h, sectionHeader, setTheme } from "./01-core.js";

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 22 — Report Generator
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_report() {
    return h`
    <div class="main">
      ${sectionHeader("R", "22 // FINDING + REPORT", "REPORT GENERATOR")}
      <div class="row" style="align-items:flex-start;gap:16px">
        <section class="panel" id="report-template-panel" style="width:320px;flex:none">
          <div class="panel-head">// TEMPLATE</div>
          <div class="panel-body col" style="gap:8px">
            <div class="row report-template-row active" data-template="technical" style="padding:10px;background:var(--bg-accent-panel);border:1px solid var(--border-accent);border-radius:2px;cursor:pointer">
              <span style="color:var(--acid)">●</span><span class="t-mono" style="color:var(--acid);font-weight:700">TECHNICAL</span>
            </div>
            <div class="row report-template-row" data-template="executive" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;cursor:pointer">
              <span class="muted">○</span><span class="t-mono">EXECUTIVE</span>
            </div>
            <div class="row report-template-row" data-template="owasp-matrix" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;cursor:pointer">
              <span class="muted">○</span><span class="t-mono">OWASP MATRIX</span>
            </div>
            <div class="row report-template-row" data-template="diff" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;cursor:pointer">
              <span class="muted">○</span><span class="t-mono">DIFF</span>
            </div>
            <div style="height:1px;background:var(--border);margin:8px 0"></div>
            <div class="panel-head" style="background:transparent;border:0;padding:0">// INCLUDE</div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span style="color:var(--acid);flex:1">Mitigation Playbook</span><span class="small" style="color:var(--magenta)">mandatory</span></div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span>Evidence snippets</span></div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span>Frida scripts used</span></div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span>Traffic captures (sanitized)</span></div>
            <div style="height:1px;background:var(--border);margin:8px 0"></div>
            <div class="panel-head" style="background:transparent;border:0;padding:0">// EXPORT</div>
            <div class="row" style="gap:8px">
              <button class="btn primary" data-export="pdf">[ PDF ]</button>
              <button class="btn" data-export="html">[ HTML ]</button>
            </div>
            <div class="row" style="gap:8px">
              <button class="btn" data-export="markdown">[ .MD ]</button>
              <button class="btn" data-export="json">[ JSON ]</button>
            </div>
          </div>
        </section>
        <section class="panel grow">
          <div class="panel-head" id="report-preview-head">// PREVIEW</div>
          <div class="panel-body col" style="gap:12px;background:var(--bg-code)" id="report-preview">
            <div class="empty-state">
              <span class="muted small uppercase">no project picked yet</span>
              <div class="muted small" style="margin-top:6px">scan an APK at <a href="#/scan">/#/scan</a>, then come back to render its real Mitigation Playbook here.</div>
            </div>
          </div>
        </section>
      </div>
      <div class="row muted small" style="justify-content:center">
        <a href="#/report/diff">diff report →</a>
      </div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 25 — Recipes Library
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_recipes() {
    // Empty shell — mount_recipes() fetches /v1/recipes and renders the grid
    // from real data (built-ins + the recursive walk over ~/.mnexus/tools/medusa
    // /modules). No hardcoded placeholder rows: if the endpoint returns
    // nothing the empty state is honest.
    return h`
    <div class="main">
      ${sectionHeader("R", "25 // AUTOMATION", "RECIPES LIBRARY")}
      <section class="row" style="flex-wrap:wrap;gap:8px;align-items:center">
        <span class="muted small">platform:</span>
        <button class="btn primary" data-rplat="">[ ALL ]</button>
        <button class="btn" data-rplat="android">[ 🤖 ANDROID ]</button>
        <button class="btn" data-rplat="ios">[ 🍎 iOS ]</button>
        <span style="width:18px"></span>
        <span class="muted small">origin:</span>
        <button class="btn primary" data-rorigin="">[ ANY ]</button>
        <button class="btn" data-rorigin="builtin">[ BUILTIN ]</button>
        <button class="btn" data-rorigin="medusa">[ MEDUSA ]</button>
        <button class="btn" data-rorigin="stheno">[ STHENO ]</button>
        <span class="spacer"></span>
        <div class="input" style="width:260px">
          <span class="prompt">&gt;</span>
          <input id="recipes-search" placeholder="search name / category / description…">
          <span class="cursor">_</span>
        </div>
      </section>
      <section class="row" id="recipes-categories" style="flex-wrap:wrap;gap:6px;align-items:center"></section>
      <section class="row" style="gap:12px;align-items:center">
        <span class="muted small" id="recipes-count">scanning…</span>
        <span class="spacer"></span>
        <span class="muted small">tip: <b>[ PREVIEW ]</b> shows the Frida script · <b>[ LOAD ]</b> stages it for the next dynamic session</span>
      </section>
      <section class="recipes-grid" id="recipes-grid">
        <div class="empty-state"><span class="muted small uppercase">scanning recipes on disk…</span></div>
      </section>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 26 — Tools / Doctor (dedicated page)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_tools() {
    return h`
    <div class="main">
      <div class="row" style="align-items:flex-end">
        <div class="section-header grow">
          <div class="ascii">D</div>
          <div class="label-group">
            <div class="kicker">26 // SYSTEM</div>
            <div class="title">TOOLS DOCTOR</div>
          </div>
        </div>
        <span class="badge connected" id="doctor-badge"><span class="dot">●</span>loading…</span>
      </div>
      <div class="gradient-underline"></div>
      <section class="panel">
        <div class="panel-head">
          <span class="t-mono">ENGINE</span>
          <span style="width:100px">STATUS</span>
          <span style="width:120px">VERSION</span>
          <span class="grow">PATH</span>
          <span style="width:260px">NOTE</span>
        </div>
        <div class="panel-body tight" id="doctor-table">loading…</div>
      </section>
      <div class="muted small">
        run <code>mnexus doctor</code> in a terminal for the same check with colored output.
        <br>setup helpers: <code>scripts/setup.sh --mobsf</code> · <code>--burp-rest-api</code> · <code>--moxy</code> · <code>--device</code>.
      </div>
    </div>`;
}

async function mount_tools() {
    const rows = await getJSON("/v1/doctor").catch(() => []);
    const ok = rows.filter((r) => r.installed).length;
    const total = rows.length;
    const badge = $("#doctor-badge");
    if (badge) {
        badge.classList.toggle("connected", ok === total && total > 0);
        badge.classList.toggle("scanning", ok < total);
        badge.innerHTML = `<span class="dot">●</span>${ok}/${total} ${ok === total ? "HEALTHY" : "NEEDS ATTENTION"}`;
    }
    const el = $("#doctor-table");
    el.innerHTML = rows.map((r) => `
      <div class="table-row" style="grid-template-columns: 160px 100px 120px 1fr 260px">
        <span class="t-mono" style="font-weight:700">${r.name}</span>
        <span class="t-mono" style="color:var(--${r.installed ? "acid" : "sev-crit"});font-weight:700;letter-spacing:2px">${r.installed ? "● OK" : "● MISSING"}</span>
        <span class="t-muted">${r.version || "—"}</span>
        <span class="t-muted">${r.path || "—"}</span>
        <span class="t-muted" style="color:var(--magenta)">${r.message || ""}</span>
      </div>`).join("");
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 27 — Settings
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_settings() {
    return h`
    <div class="main">
      ${sectionHeader("S", "27 // SHELL", "SETTINGS")}

      <section class="panel">
        <div class="panel-head">// THEME</div>
        <div class="panel-body col" id="theme-picker">${renderThemePicker()}</div>
      </section>

      <section class="panel">
        <div class="panel-head">// ENGINE PATHS</div>
        <div class="panel-body col">
          <div class="row"><span class="muted small" style="width:140px">ADB</span><code>/opt/homebrew/bin/adb</code></div>
          <div class="row"><span class="muted small" style="width:140px">JADX</span><code>/opt/homebrew/bin/jadx</code></div>
          <div class="row"><span class="muted small" style="width:140px">APKTOOL</span><code>/opt/homebrew/bin/apktool</code></div>
          <div class="row"><span class="muted small" style="width:140px">GHIDRA</span><code>~/.mnexus/tools/ghidra</code></div>
          <div class="row"><span class="muted small" style="width:140px">MEDUSA</span><code>~/.mnexus/tools/medusa</code></div>
          <div class="row"><span class="muted small" style="width:140px">STHENO</span><code>~/.mnexus/tools/stheno</code></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">// SERVICE URLS</div>
        <div class="panel-body col">
          <div class="row"><span class="muted small" style="width:140px">MOBSF</span><code>http://localhost:8000</code></div>
          <div class="row"><span class="muted small" style="width:140px">BURP</span><code>http://localhost:8090</code></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">// UI</div>
        <div class="panel-body col">
          <div class="row"><span class="muted small" style="width:140px">GLITCH</span><input type="range" min="0" max="100" value="40" style="flex:1"></div>
          <div class="row"><span class="muted small" style="width:140px">SCANLINES</span><span class="chip low">ON</span></div>
          <div class="row"><span class="muted small" style="width:140px">CRT FLICKER</span><span class="chip low">ON</span></div>
          <div class="row"><span class="muted small" style="width:140px">REDUCED MOTION</span><span class="chip info">OFF</span></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">// ABOUT</div>
        <div class="panel-body">
          <a class="btn" href="#/about">[ OPEN CREDITS ]</a>
        </div>
      </section>
    </div>`;
}

function bindThemePicker() {
    const root = $("#theme-picker");
    if (!root) return;
    root.addEventListener("click", (e) => {
        const card = e.target.closest("[data-theme-id]");
        if (!card) return;
        const id = card.dataset.themeId;
        if (id === getTheme()) return;
        setTheme(id);
        root.innerHTML = renderThemePicker();
    });
}

function renderThemePicker() {
    const active = getTheme();
    return AVAILABLE_THEMES.map((t) => {
        const isOn = t.id === active;
        const swatches = t.swatches.map((c) =>
            `<span style="display:inline-block;width:18px;height:18px;border:1px solid var(--border);border-radius:2px;background:${c}"></span>`
        ).join("");
        return `
          <label class="row theme-card" data-theme-id="${t.id}" style="
              cursor:pointer; padding:12px;
              background:${isOn ? "var(--bg-accent-panel)" : "var(--bg-panel)"};
              border:1px solid ${isOn ? "var(--border-accent)" : "var(--border)"};
              border-radius:2px; gap:14px; align-items:center;
              transition:border-color 120ms, background 120ms;
          ">
            <input type="radio" name="theme" value="${t.id}" ${isOn ? "checked" : ""} style="accent-color:var(--acid)">
            <div class="col" style="gap:2px;flex:1;min-width:0">
              <span class="t-mono" style="color:${isOn ? "var(--acid)" : "var(--cyan)"};font-weight:700;letter-spacing:2px">${t.name}</span>
              <span class="muted small">${t.kicker}</span>
            </div>
            <div class="row" style="gap:4px">${swatches}</div>
            ${isOn ? '<span class="chip low" style="margin-left:8px">ACTIVE</span>' : ""}
          </label>`;
    }).join("");
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 31 — About / Credits
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_about() {
    return h`
    <div class="main" style="align-items:center;text-align:center">
      <div style="font-size:96px">🔱</div>
      <div style="font-size:56px;font-weight:700;letter-spacing:8px;color:var(--cyan);text-shadow:0 0 20px rgba(0,255,255,.45);animation:flicker 3.2s infinite">MEDUSA NEXUS</div>
      <div class="muted" style="letter-spacing:2px">unified mobile threat analysis platform · every head sees a different angle</div>
      <div class="gradient-underline" style="width:720px"></div>
      <div class="row" style="gap:24px;width:100%;align-items:flex-start">
        <section class="panel accent grow">
          <div class="panel-head" style="color:var(--acid)">// AUTHOR</div>
          <div class="panel-body col">
            <div style="font-size:24px;font-weight:700">Jackson Mafra</div>
            <div style="color:var(--acid);letter-spacing:2px">Mobile Threat Engineer @ Umain</div>
            <div style="height:1px;background:var(--border-accent);margin:8px 0"></div>
            <a href="https://github.com/jacksonmafra-umain" target="_blank">github.com/jacksonmafra-umain</a>
            <a href="https://github.com/jacksonfdam" target="_blank">github.com/jacksonfdam</a>
          </div>
        </section>
        <section class="panel grow">
          <div class="panel-head" style="color:var(--magenta)">// BUILT ON OTHER PEOPLE'S RESEARCH</div>
          <div class="panel-body col">
            <div>ch0pin · Medusa + Stheno · the brainstem of dynamic analysis</div>
            <div>Skylot · JADX · the only decompiler that does not apologize</div>
            <div>NSA · Ghidra · yes, really</div>
            <div>MobSF · Ajin Abraham · the static lecturer</div>
            <div>Frida · Ole André Vadla Ravnås · JavaScript in your JVM</div>
            <div>PortSwigger · Burp Suite · proxy all the things</div>
            <div>iBotPeaches et al. · APKTool · resource whisperer</div>
            <div>AOSP · adb · the glue</div>
          </div>
        </section>
      </div>
      <div class="muted" style="letter-spacing:4px;animation:pulse 1.1s infinite">_ SYSTEM READY _</div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 00 — Boot
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_boot() {
    const lines = [
        "[boot] kernel::init                       [  OK  ]",
        "[boot] nexus::orchestrator                [  OK  ]",
        "[boot] engine::adb         v34.0.5        [  OK  ]",
        "[boot] engine::frida       v16.1.4        [  OK  ]",
        "[boot] engine::jadx        v1.4.7         [  OK  ]",
        "[boot] engine::ghidra      v11.0          [  OK  ]",
        "[boot] engine::mobsf       v3.7.6         [  OK  ]",
        "[boot] engine::burp        v2024.1        [  OK  ]",
        "[boot] engine::medusa      v2.0           [  OK  ]",
        "[boot] engine::stheno      v1.0           [  OK  ]",
        "[boot] engine::apktool     v2.9.3         [  OK  ]",
        "[boot] intelligence::correlator            [  OK  ]",
        "[boot] intelligence::hook_generator        [  OK  ]",
        "[boot] artifact_store::open(sqlite)        [  OK  ]",
        "",
        "&gt; _ SYSTEM READY _",
    ];
    return h`
    <div class="main" style="padding:80px;gap:24px">
      <div style="font-size:64px;font-weight:700;letter-spacing:4px;color:var(--cyan);text-shadow:0 0 16px rgba(0,255,255,.45);animation:flicker 3.2s infinite">🔱 MEDUSA::NEXUS</div>
      <div class="muted" style="letter-spacing:2px">v0.1.0-alpha // every head sees a different angle</div>
      <div class="gradient-underline" style="width:600px"></div>
      <section class="panel" style="max-width:960px">
        <div class="panel-body console" style="color:var(--acid)">${lines.map(l => `<div>${l}</div>`).join("")}</div>
      </section>
      <div><a class="btn primary" href="#/dashboard">[ ENTER DASHBOARD ]</a></div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Finding Detail (full-screen, mimics the drawer in the Pencil deck)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_finding_detail(ctx) {
    const id = ctx.params.fid || ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    // Empty shell — mount_finding_detail fetches /v1/findings/{id} and fills.
    return h`
    <div class="main">
      <div class="row muted small">
        <a href="#/projects">← projects</a>
        <span>·</span>
        <span id="finding-breadcrumb">finding ${id}</span>
      </div>
      <div class="finding" style="max-width:900px" id="finding-card">
        <div class="head">
          <span class="tag" id="finding-id">${id}</span>
          <span id="finding-chip"></span>
          <span class="tag" style="color:var(--magenta)" id="finding-cwe"></span>
          <span class="tag" style="color:var(--magenta)" id="finding-owasp"></span>
          <span class="tag" id="finding-attribution" title="Library attribution — owner of the offending code" style="display:none"></span>
          <span class="grow"></span>
          <span class="badge" id="finding-state"></span>
        </div>
        <div class="title" style="font-size:20px" id="finding-title">loading…</div>
        <div class="meta" id="finding-desc"></div>
        <div class="meta" id="finding-attribution-paths" style="display:none"></div>
        <div style="height:1px;background:var(--border);margin:8px 0"></div>
        <div class="block-label">// EVIDENCE</div>
        <pre class="code" id="finding-evidence"></pre>
        <div class="block-label" id="finding-hook-label" style="display:none">// AUTO-HOOK (frida)</div>
        <pre class="code" id="finding-hook" style="display:none"></pre>
        <div class="row"><div class="block-label mitigation-label">// MITIGATION</div><span class="muted small">— code-level, not vibes</span></div>
        <div class="mitigation" id="finding-mitigation"></div>
        <div class="row" id="finding-actions" style="display:none">
          <button class="btn primary" id="finding-run-hook">[ RUN HOOK ]</button>
          <button class="btn" id="finding-copy-mitigation">[ COPY MITIGATION ]</button>
          <span class="grow"></span>
        </div>
      </div>
    </div>`;
}


export { bindThemePicker, mount_tools, view_about, view_boot, view_finding_detail, view_recipes, view_report, view_settings, view_tools };
