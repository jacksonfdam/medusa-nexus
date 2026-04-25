/* MEDUSA NEXUS — SPA router + all 31 screen templates.
 *
 * Every route is a function of (ctx) that returns an HTML string. The router
 * injects that into #view, re-wires sidebar active state, and calls an optional
 * `mount()` hook (for live data / event listeners).
 *
 * Route table at the bottom of this file. Sidebar labels come from ROUTE_META.
 */

/* ─── tiny helpers ─── */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const h = (strings, ...values) => String.raw({ raw: strings }, ...values);

async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`${url} → ${r.status}`);
    return r.json();
}

function classifyRisk(score) {
    if (score >= 75) return "crit";
    if (score >= 50) return "high";
    if (score >= 25) return "med";
    return "acid";
}

function chip(sev) {
    const cls = ["crit", "high", "med", "low", "info"].includes(sev) ? sev : "info";
    return `<span class="chip ${cls}">${cls.toUpperCase()}</span>`;
}

function sectionHeader(ascii, kicker, title) {
    return `
    <div>
      <div class="section-header">
        <div class="ascii">${ascii}</div>
        <div class="label-group">
          <div class="kicker">${kicker}</div>
          <div class="title">${title}</div>
        </div>
      </div>
      <div class="gradient-underline"></div>
    </div>`;
}

/* ─── stub renderer: rich wireframe for screens still under construction ─── */
function stub({ id, kicker, title, hero, detail, features = [], cta }) {
    return h`
    <div class="main">
      ${sectionHeader(hero, kicker, title)}
      <section class="panel">
        <div class="panel-head">// SPEC — from docs/SPEC.md</div>
        <div class="panel-body">
          <p class="muted" style="margin:0 0 12px">${detail}</p>
          <ul style="margin:0;padding-left:18px;color:var(--cyan);font-size:12px;line-height:1.7">
            ${features.map((f) => `<li>${f}</li>`).join("")}
          </ul>
        </div>
      </section>
      <section class="empty-state">
        <div style="font-size:20px;letter-spacing:4px;color:var(--magenta);margin-bottom:12px">
          [ ${id}  ·  iteration 2 // full fidelity ]
        </div>
        ${cta ? `<div>${cta}</div>` : ""}
        <div style="margin-top:12px">the design is locked in the Pencil deck · <a href="#/about">design INDEX</a></div>
      </section>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 01 — Dashboard
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_dashboard() {
    return h`
    <div class="main">
      <section class="metrics">
        <div class="metric-card">
          <div class="metric-label">// AVG RISK</div>
          <div class="metric-value" id="m-risk">—</div>
          <div class="metric-sub" id="m-risk-sub">no projects yet</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">// OPEN CRITICALS</div>
          <div class="metric-value crit" id="m-crit">—</div>
          <div class="metric-sub" id="m-crit-sub">nothing blocking release</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">// DEVICES</div>
          <div class="metric-value acid" id="m-dev">—</div>
          <div class="metric-sub" id="m-dev-sub">plug a device + scripts/setup.sh --device</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">// ENGINES</div>
          <div class="metric-value acid" id="m-eng">—</div>
          <div class="metric-sub" id="m-eng-sub">answered doctor</div>
        </div>
      </section>

      ${sectionHeader("P", "02 // RECENT", "PROJECTS")}
      <section class="projects" id="projects">
        <a class="project-card" href="#/scan" style="justify-content:center;text-align:center">
          <div class="muted small uppercase">empty</div>
          <div style="font-size:18px;color:var(--acid);letter-spacing:2px">NO PROJECTS — GO BREAK SOMETHING</div>
          <div class="muted small"><code>mnexus scan ./target.apk</code></div>
        </a>
      </section>

      <section class="panel">
        <div class="panel-head">// ENGINE STATUS · live from /v1/doctor</div>
        <div class="panel-body tight" id="engines">loading…</div>
      </section>
    </div>`;
}

async function mount_dashboard() {
    const [doctor, projects] = await Promise.all([
        getJSON("/v1/doctor").catch(() => []),
        getJSON("/v1/projects").catch(() => []),
    ]);
    renderEngines(doctor);
    renderProjects(projects);
    updateMetrics(doctor, projects);
    updateSidebarCounts(doctor, projects);
}

function renderEngines(rows) {
    const el = $("#engines");
    if (!el) return;
    if (!rows.length) {
        el.innerHTML = `<div class="empty-state">no engines registered</div>`;
        return;
    }
    el.innerHTML = rows.map((r) => {
        const stat = r.installed ? "ok" : "miss";
        const badge = r.installed ? "● OK" : "● MISSING";
        return `
        <div class="table-row" style="grid-template-columns: 110px 90px 200px 1fr">
          <span class="t-mono" style="font-weight:700">${r.name}</span>
          <span class="t-mono" style="font-weight:700;letter-spacing:2px;color:var(--${stat === "ok" ? "acid" : "sev-crit"})">${badge}</span>
          <span class="t-muted">${(r.version || "—").toString().slice(0, 40)}</span>
          <span class="t-muted" style="color:var(--magenta)">${r.message || ""}</span>
        </div>`;
    }).join("");
}

function renderProjects(projects) {
    const el = $("#projects");
    if (!el || !projects.length) return;
    el.innerHTML = projects.slice(0, 3).map((p) => {
        const score = typeof p.risk_score === "number" ? p.risk_score : 0;
        const sev = p.worst_severity || "info";
        const counts = p.counts || "0c · 0h · 0m · 0l";
        return `
        <a class="project-card" href="#/project/${encodeURIComponent(p.id)}/overview">
          <div class="project-head">
            <div class="project-icon" style="background:${iconColor(p.package_name || p.id)}"></div>
            <div class="project-title">
              <span class="pkg">${p.package_name || p.name || p.id}</span>
              <span class="ver">${p.version_name || ""}${p.updated_at ? " · " + p.updated_at.slice(0, 10) : ""}</span>
            </div>
            ${chip(sev.toLowerCase())}
          </div>
          <div class="project-stats">
            <span class="project-score" style="color:var(--sev-${classifyRisk(score)})">${score.toFixed(1)}</span>
            <span class="project-score-suffix">/100</span>
            <span class="project-counts">${counts}</span>
          </div>
        </a>`;
    }).join("");
}

function iconColor(str) {
    const palette = ["#00FFFF22", "#E879F922", "#F1C40F22", "#22DE8022", "#FF386022", "#FF950022"];
    let hash = 0;
    for (let i = 0; i < str.length; i++) hash = (hash * 31 + str.charCodeAt(i)) >>> 0;
    return palette[hash % palette.length];
}

function updateMetrics(doctor, projects) {
    const total = doctor.length;
    const ok = doctor.filter((r) => r.installed).length;
    const eng = $("#m-eng");
    if (eng) {
        eng.textContent = `${String(ok).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
        eng.classList.toggle("acid", ok === total && total > 0);
        eng.classList.toggle("high", ok < total);
        $("#m-eng-sub").textContent = ok === total ? "every head answered" : `${total - ok} engine(s) missing`;
    }
    const risk = $("#m-risk");
    const riskSub = $("#m-risk-sub");
    if (risk && projects.length) {
        const avg = projects.reduce((a, p) => a + (p.risk_score || 0), 0) / projects.length;
        risk.textContent = avg.toFixed(1);
        risk.className = "metric-value " + classifyRisk(avg);
        riskSub.textContent = `across ${projects.length} project${projects.length === 1 ? "" : "s"}`;
    }
    const crit = $("#m-crit");
    if (crit) {
        const c = projects.reduce((a, p) => a + (p.critical_count || 0), 0);
        crit.textContent = String(c).padStart(2, "0");
        $("#m-crit-sub").textContent = c ? `${c} blocker(s) — review ASAP` : "nothing blocking release";
    }
}

function updateSidebarCounts(doctor, projects) {
    const navTools = $('[data-route="tools"] .count');
    if (navTools) navTools.textContent = `${doctor.filter((r) => r.installed).length}/${doctor.length}`;
    const navProjects = $('[data-route="projects"] .count');
    if (navProjects) navProjects.textContent = projects.length ? String(projects.length) : "";
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 02 — Projects List
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_projects() {
    return h`
    <div class="main">
      ${sectionHeader("P", "02 // SHELL", "PROJECTS")}
      <section class="row">
        <div class="input grow"><span class="prompt">&gt;</span><input placeholder="filter by package, min risk, critical-only…"><span class="cursor">_</span></div>
        <a class="btn primary" href="#/scan">[ + IMPORT APK ]</a>
      </section>
      <section class="panel">
        <div class="panel-head">
          <span>// PROJECTS</span>
          <span class="spacer"></span>
          <span class="muted" id="projects-count">loading…</span>
        </div>
        <div class="panel-body tight" id="projects-table">loading…</div>
      </section>
    </div>`;
}

async function mount_projects() {
    const projects = await getJSON("/v1/projects").catch(() => []);
    const el = $("#projects-table");
    $("#projects-count").textContent = `${projects.length} stored`;
    if (!projects.length) {
        el.innerHTML = `
          <div class="empty-state">
            <div style="font-size:24px;color:var(--magenta);letter-spacing:4px;margin-bottom:12px">NO PROJECTS YET</div>
            <div>drop an APK on the <a href="#/scan">Scan</a> screen or pull one off a device</div>
          </div>`;
        return;
    }
    const header = `
      <div class="table-hdr" style="grid-template-columns: 40px 1fr 140px 90px 100px 120px 140px">
        <span></span><span>PACKAGE</span><span>VERSION</span><span>RISK</span><span>SEVERITIES</span><span>UPDATED</span><span></span>
      </div>`;
    const rows = projects.map((p) => {
        const score = p.risk_score || 0;
        return `
        <a class="table-row" href="#/project/${encodeURIComponent(p.id)}/overview" style="grid-template-columns: 40px 1fr 140px 90px 100px 120px 140px;text-decoration:none;color:inherit">
          <div class="project-icon" style="background:${iconColor(p.package_name || p.id)};width:24px;height:24px"></div>
          <span class="t-mono" style="font-weight:700">${p.package_name || p.name || p.id}</span>
          <span class="t-muted">${p.version_name || "—"}</span>
          <span class="t-mono" style="color:var(--sev-${classifyRisk(score)})">${score.toFixed(1)}</span>
          <span class="t-muted">${p.counts || "—"}</span>
          <span class="t-muted">${(p.updated_at || "").slice(0, 10)}</span>
          <span style="text-align:right">${chip((p.worst_severity || "info").toLowerCase())}</span>
        </a>`;
    }).join("");
    el.innerHTML = header + rows;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 03 — APK Intake / Scan
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_scan() {
    return h`
    <div class="main">
      ${sectionHeader("I", "03 // INTAKE", "APK RECONNAISSANCE")}
      <section class="dropzone" id="dz">
        <div class="heading">[ DROP .APK / .XAPK HERE ]</div>
        <div class="sub">or click BROWSE · or pull from device</div>
        <div class="wink">SHA-256 gets computed. apktool detects package+version. ingest runs.</div>
        <input type="file" id="dz-picker" accept=".apk,.xapk" style="display:none" />
        <div class="actions">
          <button class="btn primary" onclick="document.getElementById('dz-picker').click()">[ BROWSE ]</button>
          <a class="btn" href="#/device/pull">[ PULL FROM DEVICE ]</a>
          <a class="btn" href="#/device/bridge">[ DEVICE BRIDGE ]</a>
        </div>
        <div id="dz-status" class="muted small" style="min-height:18px;margin-top:6px"></div>
      </section>
      <section class="panel">
        <div class="panel-head"><span>// RECENT IMPORTS · last 10</span><span class="spacer"></span><a class="btn" href="#/projects" style="padding:4px 10px">[ SEE ALL ]</a></div>
        <div class="panel-body tight" id="recent-imports">loading…</div>
      </section>
    </div>`;
}

async function mount_scan_after_upload_wiring() {
    const projects = await getJSON("/v1/projects").catch(() => []);
    const el = $("#recent-imports");
    if (!el) return;
    if (!projects.length) {
        el.innerHTML = `<div class="empty-state">nothing imported yet. drop an APK above or run <code>mnexus scan ./target.apk</code></div>`;
        return;
    }
    el.innerHTML = projects.slice(0, 10).map((p) => `
        <a class="table-row" href="#/project/${encodeURIComponent(p.id)}/overview" style="grid-template-columns: 1fr 140px 100px 120px;text-decoration:none;color:inherit">
          <span class="t-mono" style="font-weight:700">${p.package_name || p.name || p.id}</span>
          <span class="t-muted">${p.version_name || "—"}</span>
          <span class="t-mono" style="color:var(--sev-${classifyRisk(p.risk_score || 0)})">${(p.risk_score || 0).toFixed(1)}</span>
          <span class="t-muted">${(p.updated_at || "").slice(0, 10)}</span>
        </a>`).join("");
}

function mount_scan() {
    const dz = $("#dz");
    if (!dz) return;

    const picker = $("#dz-picker");
    const status = $("#dz-status");

    ["dragenter", "dragover"].forEach((e) =>
        dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.add("over"); })
    );
    ["dragleave", "drop"].forEach((e) => dz.addEventListener(e, () => dz.classList.remove("over")));
    dz.addEventListener("drop", (ev) => { ev.preventDefault(); handleUpload(ev.dataTransfer?.files?.[0]); });
    if (picker) picker.addEventListener("change", (ev) => handleUpload(ev.target.files?.[0]));

    async function handleUpload(file) {
        if (!file) return;
        status.innerHTML = `<span style="color:var(--acid)">↑ uploading <b>${file.name}</b> (${fmtBytes(file.size)}) · detecting package via apktool…</span>`;

        const fd = new FormData();
        fd.append("file", file);
        try {
            const r = await fetch("/v1/apks/upload", { method: "POST", body: fd });
            const payload = await r.json().catch(() => ({}));
            if (!r.ok) {
                status.innerHTML = `<span style="color:var(--sev-crit)">✕ upload failed: ${payload.detail || r.statusText}</span>`;
                return;
            }
            status.innerHTML = `<span style="color:var(--acid)">✓ ingested as <b>${payload.project_id}</b> (${payload.package} ${payload.version}) — redirecting…</span>`;
            setTimeout(() => { location.hash = `#/project/${encodeURIComponent(payload.project_id)}/overview`; }, 900);
        } catch (e) {
            status.innerHTML = `<span style="color:var(--sev-crit)">✕ upload error: ${e.message}</span>`;
        }
    }
}

function fmtBytes(n) {
    if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${n} B`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 05 — Pull from Device
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_device_pull() {
    const sample = [
        ["com.target.banking", 10237, "4.12.0", "—", "3x", "48.2 MB"],
        ["com.target.social", 10254, "2.3.1", "yes", "—", "22.1 MB"],
        ["com.target.fitness", 10278, "1.0.8", "—", "—", "15.6 MB"],
        ["com.target.legacy.auth", 10121, "0.9.4", "yes", "—", "8.4 MB"],
        ["com.android.vending", 10001, "38.5.18", "—", "5x", "102.3 MB"],
    ];
    return h`
    <div class="main">
      ${sectionHeader("P", "05 // INTAKE", "PULL FROM DEVICE")}
      ${deviceTabs("pull")}
      <section class="row">
        <div class="input grow"><span class="prompt">&gt;</span><input placeholder="pm list packages | grep target"><span class="cursor">_</span></div>
        <span class="badge connected"><span class="dot">●</span>Pixel 6 · android 14</span>
      </section>
      <section class="panel">
        <div class="panel-head">// PACKAGES · 5 matched · scope: com.target.*</div>
        <div class="panel-body tight">
          <div class="table-hdr" style="grid-template-columns: 1fr 80px 120px 70px 60px 100px 120px">
            <span>PACKAGE</span><span>UID</span><span>VERSION</span><span>DEBUG</span><span>SPLIT</span><span>SIZE</span><span></span>
          </div>
          ${sample.map(([pkg, uid, ver, dbg, split, size]) => `
            <div class="table-row" style="grid-template-columns: 1fr 80px 120px 70px 60px 100px 120px">
              <span class="t-mono" style="font-weight:700">${pkg}</span>
              <span class="t-muted">${uid}</span>
              <span class="t-mono">${ver}</span>
              <span class="${dbg === "yes" ? "" : "t-muted"}" style="color:${dbg === "yes" ? "var(--sev-high)" : ""}">${dbg}</span>
              <span class="${split === "—" ? "t-muted" : "t-mono"}" style="color:${split !== "—" ? "var(--magenta)" : ""}">${split}</span>
              <span class="t-muted">${size}</span>
              <span style="text-align:right"><button class="btn primary" style="padding:4px 10px">[ PULL ]</button></span>
            </div>`).join("")}
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
        ["network", "NETWORK"],
        ["report", "REPORT"],
    ];
    return `
    <div class="tab-bar">
      ${tabs.map(([k, label]) => `<a class="tab ${k === active ? "active" : ""}" href="#/project/${encodeURIComponent(id)}/${k}">${k === active ? "> " : "  "}${label}</a>`).join("")}
    </div>`;
}

function view_project_overview(ctx) {
    const id = ctx.params.id || "PRJ-SAMPLE";
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / overview</div>
      ${projectTabs(id, "overview")}
      <section class="row" style="align-items:flex-start;gap:24px">
        <div class="col" style="width:280px">
          <div class="risk-gauge" style="--deg: 260deg">
            <div class="arc"></div>
            <div class="label">
              <div class="value">72.4</div>
              <div class="caption">RISK / 100</div>
            </div>
          </div>
          <section class="panel">
            <div class="panel-head">// SEVERITY</div>
            <div class="panel-body col" style="gap:4px">
              <div class="row"><span style="color:var(--sev-crit);width:40px">CRIT</span><span class="t-mono" style="color:var(--sev-crit)">██████░░░░░░░░░</span><span class="grow" style="text-align:right">03</span></div>
              <div class="row"><span style="color:var(--sev-high);width:40px">HIGH</span><span class="t-mono" style="color:var(--sev-high)">████████████░░░</span><span class="grow" style="text-align:right">07</span></div>
              <div class="row"><span style="color:var(--sev-med);width:40px">MED</span><span class="t-mono" style="color:var(--sev-med)">██████████████░░</span><span class="grow" style="text-align:right">12</span></div>
              <div class="row"><span style="color:var(--sev-low);width:40px">LOW</span><span class="t-mono" style="color:var(--sev-low)">████████░░░░░░░</span><span class="grow" style="text-align:right">05</span></div>
              <div class="row"><span class="muted" style="width:40px">INFO</span><span class="t-mono muted">██████████████░░</span><span class="grow" style="text-align:right">09</span></div>
            </div>
          </section>
        </div>
        <div class="col grow">
          <section class="panel">
            <div class="panel-head"><span>// FINDINGS TIMELINE</span><span class="spacer"></span><span class="muted">36 total</span></div>
            <div class="panel-body col" style="gap:8px">
              ${[
                  ["crit", "Hardcoded AES key in com.target.crypto.KeyManager", "[JADX + GHIDRA]"],
                  ["crit", "SQL injection in ContentProvider (no input validation)", "[MOBSF]"],
                  ["crit", "WebView.addJavascriptInterface exposed to untrusted content", "[JADX]"],
                  ["high", "SSL pinning via legacy TrustManager (bypassable)", "[GHIDRA]"],
                  ["high", "Root detection only in Java layer (no native checks)", "[MEDUSA]"],
                  ["med", "Clipboard data exposure (no sensitive-field clearing)", "[FRIDA]"],
                  ["med", "PII exposed in Logcat (info, email, device id)", "[FRIDA]"],
              ].map(([sev, title, src]) => `
                <div class="row" style="padding:8px 12px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px">
                  ${chip(sev)}
                  <span class="grow">${title}</span>
                  <span class="t-muted">${src}</span>
                </div>`).join("")}
            </div>
          </section>
          <section class="panel">
            <div class="panel-head">// ATTACK SURFACE</div>
            <div class="panel-body row" style="gap:24px">
              <div class="col grow"><span class="muted small uppercase">ACTIVITIES</span><span class="t-mono">24 · 9 exported · 2 unprotected</span></div>
              <div class="col grow"><span class="muted small uppercase">PROVIDERS</span><span class="t-mono" style="color:var(--sev-crit)">3 · 1 unprotected</span></div>
              <div class="col grow"><span class="muted small uppercase">DEEP LINKS</span><span class="t-mono">7 schemes · 14 hosts</span></div>
              <div class="col grow"><span class="muted small uppercase">NATIVE LIBS</span><span class="t-mono" style="color:var(--sev-high)">3 · arm64-v8a · crypto found</span></div>
            </div>
          </section>
        </div>
      </section>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 08 — Static Analysis (split view)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_static(ctx) {
    const id = ctx.params.id || "PRJ-SAMPLE";
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / static</div>
      ${projectTabs(id, "static")}
      <div class="row" style="align-items:flex-start;gap:12px;min-height:540px">
        <section class="panel" style="width:280px;flex:none">
          <div class="panel-head">// CLASS TREE</div>
          <div class="panel-body col" style="gap:2px">
            <div class="t-mono">▾ com.target.banking</div>
            <div class="t-mono" style="padding-left:14px">▾ auth/</div>
            <div class="t-mono" style="padding-left:28px">LoginActivity.java</div>
            <div class="t-mono" style="padding-left:28px">BiometricGate.java</div>
            <div class="t-mono" style="padding-left:14px;color:var(--sev-crit);font-weight:700">▾ crypto/</div>
            <div class="t-mono" style="padding-left:28px;color:var(--sev-crit);font-weight:700">● KeyManager.java</div>
            <div class="t-mono" style="padding-left:28px">Cipher1Wrapper.java</div>
            <div class="t-mono" style="padding-left:14px">▸ net/</div>
            <div class="t-mono" style="padding-left:14px">▸ storage/</div>
            <div class="t-mono" style="padding-left:14px;color:var(--sev-high);font-weight:700">▸ webview/</div>
            <div class="t-mono" style="padding-left:14px">▸ ui/</div>
            <div class="t-mono muted" style="padding-top:8px">▸ okhttp3</div>
            <div class="t-mono muted">▸ com.google.firebase</div>
          </div>
        </section>
        <section class="panel grow">
          <div class="panel-head">
            <span class="t-mono">com/target/banking/crypto/KeyManager.java</span>
            <span class="spacer"></span>
            <span class="muted">L42–L58</span>
            <a class="btn primary" href="#/finding/FND-0042" style="padding:4px 10px">[ DETAIL ]</a>
          </div>
          <div class="panel-body">
            <pre class="code"><span class="ln">40</span>
<span class="ln">41</span>  public final class KeyManager {
<span class="ln">42</span>      public static SecretKeySpec loadKey() {
<span class="ln">43</span>          <span class="comment">// CWE-798: hardcoded key bytes — also present in libcrypto.so .rodata 0x1A2F</span>
<span class="ln">44</span>          <span class="crit">byte[] key = "MedusaSays\u0000\u0000".getBytes(StandardCharsets.UTF_8);</span>
<span class="ln">45</span>          return new SecretKeySpec(key, "AES");
<span class="ln">46</span>      }
<span class="ln">47</span>
<span class="ln">48</span>      public static byte[] encrypt(byte[] in) throws Exception {
<span class="ln">49</span>          <span class="hot">Cipher c = Cipher.getInstance("AES/CBC/PKCS5Padding"); // CWE-327 candidate</span>
<span class="ln">50</span>          <span class="crit">c.init(Cipher.ENCRYPT_MODE, loadKey(), new IvParameterSpec(new byte[16])); // static IV</span>
<span class="ln">51</span>          return c.doFinal(in);
<span class="ln">52</span>      }
<span class="ln">53</span>  }</pre>
          </div>
        </section>
        <section class="panel" style="width:340px;flex:none">
          <div class="panel-head">
            <span>// FINDINGS · 36</span>
            <span class="spacer"></span>
            <span class="chip low">JADX</span>
          </div>
          <div class="panel-body col" style="gap:8px">
            <a class="finding" href="#/finding/FND-0042" style="text-decoration:none;background:var(--bg-accent-panel);border-color:var(--border-accent)">
              <div class="head">${chip("crit")}<span class="tag">FND-0042</span><span class="spacer"></span><span class="tag">[JADX+GHIDRA]</span></div>
              <div class="title">Hardcoded AES key in KeyManager.loadKey()</div>
              <div class="meta">KeyManager.java:44 · CWE-798 · confirmed</div>
            </a>
            <a class="finding" href="#/finding/FND-0050" style="text-decoration:none">
              <div class="head">${chip("crit")}<span class="tag">FND-0050</span><span class="spacer"></span><span class="tag">[JADX]</span></div>
              <div class="title">Static IV with AES/CBC in encrypt()</div>
              <div class="meta">KeyManager.java:50 · CWE-329</div>
            </a>
            <a class="finding" href="#/finding/FND-0044" style="text-decoration:none">
              <div class="head">${chip("crit")}<span class="tag">FND-0044</span><span class="spacer"></span><span class="tag">[MOBSF]</span></div>
              <div class="title">WebView.addJavascriptInterface + unrestricted URLs</div>
              <div class="meta">webview/SupportBrowser.java:120 · CWE-79/749</div>
            </a>
            <a class="finding" href="#/finding/FND-0045" style="text-decoration:none">
              <div class="head">${chip("high")}<span class="tag">FND-0045</span><span class="spacer"></span><span class="tag">[GHIDRA]</span></div>
              <div class="title">Legacy TrustManager in libnet.so — pinning bypassable</div>
              <div class="meta">libnet.so+0x312C · CWE-295</div>
            </a>
          </div>
        </section>
      </div>
      <div class="row muted small" style="justify-content:center">
        <a href="#/project/${id}/secrets">secrets</a> ·
        <a href="#/project/${id}/components">components</a> ·
        <a href="#/project/${id}/native">native (ghidra)</a>
      </div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 12 — Dynamic Analysis (Frida console)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_dynamic(ctx) {
    const id = ctx.params.id || "PRJ-SAMPLE";
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / dynamic <span class="badge scanning" style="margin-left:12px"><span class="dot">●</span>FRIDA ATTACHED</span></div>
      ${projectTabs(id, "dynamic")}
      <div class="row" style="align-items:flex-start;gap:12px;min-height:520px">
        <section class="panel" style="width:260px;flex:none">
          <div class="panel-head">// HOOKS</div>
          <div class="panel-body col" style="gap:6px">
            <div class="muted small">Auto-generated from static findings. Untick at your own risk.</div>
            ${[
                ["x", "ssl_pinning_bypass", true],
                ["x", "root_detection_bypass", true],
                ["x", "crypto_logger", true],
                [" ", "intent_monitor", false],
                [" ", "file_io_monitor", false],
                [" ", "clipboard_watcher", false],
            ].map(([mark, name, on]) => `
                <div class="row" style="padding:6px 10px;background:${on ? "var(--bg-accent-panel)" : "var(--bg-panel)"};border:1px solid ${on ? "var(--border-accent)" : "var(--border)"};border-radius:2px">
                  <span style="color:${on ? "var(--acid)" : "var(--muted)"}">[${mark}]</span>
                  <span class="t-mono" style="color:${on ? "var(--acid)" : "var(--muted)"}">${name}</span>
                </div>`).join("")}
            <a class="btn" href="#/recipes" style="margin-top:10px">[ LOAD RECIPE ]</a>
          </div>
        </section>
        <section class="panel grow">
          <div class="panel-head">// FRIDA CONSOLE</div>
          <div class="panel-body console">
<span class="nexus">[NEXUS] attaching to com.target.banking (pid 14827)</span>
<span class="nexus">[NEXUS] loaded module: ssl_pinning_bypass</span>
<span class="nexus">[NEXUS] loaded module: root_detection_bypass</span>
<span class="nexus">[NEXUS] loaded module: crypto_logger</span>
<span class="nexus">[NEXUS] auto-hooks injected: 14 (rooted-detection: RootBeer v0.0.9)</span>
<span class="nexus">[NEXUS] session active · spawn resumed</span>

<span class="meta">[ROOT ] RootBeer.isRooted() = true → returning false (because yes)</span>
<span class="meta">[SSL  ] CertificatePinner.check("api.target.com") → noop</span>
<span class="crypto">[CRYPTO] SecretKeySpec(AES/CBC/PKCS5Padding) key=4d656475736153617973...</span>
<span class="crypto">[CRYPTO]   iv=000000000000000000000000 ← static IV, because of course it is</span>
<span class="crit">[CRYPTO] Cipher.doFinal → pt={"user":"admin","token":"eyJhbGciOi..."}</span>
<span class="intent">[INTENT] tx: com.target.banking/.ui.LoginActivity  extras={remember=true}</span>
<span class="intent">[FS    ] read: /data/data/com.target.banking/shared_prefs/session.xml</span>
<span class="crypto">[CLIP  ] ClipboardManager.setPrimaryClip("4532-7800-...") — send help</span>
<span class="nexus">frida&gt; _</span>
          </div>
        </section>
      </div>
      <div class="row muted small" style="justify-content:center">
        <a href="#/project/${id}/tracer">live method tracer →</a>
      </div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 14 — Network Analysis
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_project_network(ctx) {
    const id = ctx.params.id || "PRJ-SAMPLE";
    const rows = [
        ["POST", "api.target.com", "/v2/auth/login", 200, "1.8 KB", 412, ["JWT","PII"], "crit"],
        ["GET", "api.target.com", "/v2/accounts/me", 200, "4.2 KB", 187, ["PII"], "high"],
        ["POST", "beacon.analytics.io", "/collect", 204, "512 B", 89, ["IDF"], "med"],
        ["GET", "api.target.com", "/v2/transfers/recent", 401, "120 B", 102, [], "info"],
        ["POST", "crashlytics.firebase", "/v1/reports", 200, "6.1 KB", 304, ["STACK"], "med"],
        ["GET", "cdn.target.com", "/static/promo.html", 200, "12.4 KB", 78, ["WV"], "high"],
    ];
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / network <span style="margin-left:12px">burp @ 127.0.0.1:8080</span></div>
      ${projectTabs(id, "network")}
      <section class="panel">
        <div class="panel-head">
          <span>// TRAFFIC · 247 · scope: com.target.*</span>
          <span class="spacer"></span>
          <button class="btn">[ REPLAY ]</button>
          <button class="btn">[ DIFF ]</button>
          <a class="btn primary" href="#/project/${id}/api-map">[ API MAP ]</a>
        </div>
        <div class="panel-body tight">
          <div class="table-hdr" style="grid-template-columns: 50px 180px 1fr 70px 80px 60px 90px">
            <span>M</span><span>HOST</span><span>PATH</span><span>STATUS</span><span>SIZE</span><span>MS</span><span>FLAGS</span>
          </div>
          ${rows.map(([m, host, path, status, size, ms, flags, sev]) => `
            <div class="table-row" style="grid-template-columns: 50px 180px 1fr 70px 80px 60px 90px">
              <span class="t-mono" style="color:${m === "POST" ? "var(--acid)" : "var(--cyan)"};font-weight:700">${m}</span>
              <span class="t-mono" style="color:${sev === "info" ? "var(--muted)" : "var(--cyan)"}">${host}</span>
              <span class="t-mono" style="color:${sev === "info" ? "var(--muted)" : "var(--cyan)"}">${path}</span>
              <span class="t-mono" style="color:var(--${status < 300 ? "acid" : status < 500 ? "sev-high" : "sev-crit"});font-weight:700">${status}</span>
              <span class="t-muted">${size}</span>
              <span class="t-muted">${ms}</span>
              <span style="font-size:9px;color:var(--sev-${sev});font-weight:700">${flags.length ? "[" + flags.join("][") + "]" : ""}</span>
            </div>`).join("")}
        </div>
      </section>
      <div class="row muted small" style="justify-content:center;gap:18px">
        <a href="#/project/${id}/api-map">api endpoints</a>
        <a href="#/project/${id}/ssl-map">ssl pinning map</a>
      </div>
    </div>`;
}

function view_project_report(ctx) {
    // Jump to main Report screen with context.
    location.hash = "#/report?project=" + encodeURIComponent(ctx.params.id || "");
    return view_report(ctx);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 22 — Report Generator
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_report() {
    return h`
    <div class="main">
      ${sectionHeader("R", "22 // FINDING + REPORT", "REPORT GENERATOR")}
      <div class="row" style="align-items:flex-start;gap:16px">
        <section class="panel" style="width:320px;flex:none">
          <div class="panel-head">// TEMPLATE</div>
          <div class="panel-body col" style="gap:8px">
            <div class="row" style="padding:10px;background:var(--bg-accent-panel);border:1px solid var(--border-accent);border-radius:2px"><span style="color:var(--acid)">●</span><span class="t-mono" style="color:var(--acid);font-weight:700">TECHNICAL</span></div>
            <div class="row" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px"><span class="muted">○</span><span class="t-mono">EXECUTIVE</span></div>
            <div class="row" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px"><span class="muted">○</span><span class="t-mono">OWASP MATRIX</span></div>
            <div class="row" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px"><span class="muted">○</span><span class="t-mono">DIFF (v4.11 → v4.12)</span></div>
            <div style="height:1px;background:var(--border);margin:8px 0"></div>
            <div class="panel-head" style="background:transparent;border:0;padding:0">// INCLUDE</div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span style="color:var(--acid);flex:1">Mitigation Playbook</span><span class="small" style="color:var(--magenta)">mandatory</span></div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span>Evidence snippets</span></div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span>Frida scripts used</span></div>
            <div class="row"><span style="color:var(--acid);font-weight:700">[x]</span><span>Traffic captures (sanitized)</span></div>
            <div style="height:1px;background:var(--border);margin:8px 0"></div>
            <div class="panel-head" style="background:transparent;border:0;padding:0">// EXPORT</div>
            <div class="row" style="gap:8px"><button class="btn primary">[ PDF ]</button><button class="btn">[ HTML ]</button></div>
            <div class="row" style="gap:8px"><button class="btn">[ .MD ]</button><button class="btn">[ JSON ]</button></div>
          </div>
        </section>
        <section class="panel grow">
          <div class="panel-head">// PREVIEW · technical_report.pdf · 37 pages</div>
          <div class="panel-body col" style="gap:12px;background:#050505">
            <div style="font-size:20px;color:var(--cyan);font-weight:700;letter-spacing:2px">MEDUSA NEXUS // TECHNICAL ASSESSMENT</div>
            <div class="muted small">target: com.target.banking v4.12.0 · SHA-256 86fa…d23c · 2026-04-24</div>
            <div class="gradient-underline"></div>
            <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--magenta)">§ 01 · EXECUTIVE SUMMARY</div>
            <div>Risk 72.4/100. Three critical findings block release: hardcoded key, SQLi in provider, permissive WebView.</div>
            <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--acid)">§ 02 · MITIGATION PLAYBOOK — mandatory section</div>
            <div class="mitigation">
              <div class="row" style="align-items:flex-start;gap:10px">${chip("crit")}<div><b>FND-0042 · Hardcoded AES key</b><br>→ Move to Android Keystore, switch to AES/GCM, rotate DEKs, invalidate in-flight ciphertext.</div></div>
              <div class="row" style="align-items:flex-start;gap:10px">${chip("crit")}<div><b>FND-0043 · SQLi in ContentProvider</b><br>→ Parameterized queries only. Drop android:exported=true. Add signature-level permission.</div></div>
              <div class="row" style="align-items:flex-start;gap:10px">${chip("crit")}<div><b>FND-0044 · WebView with JS interface</b><br>→ Remove @JavascriptInterface. If unavoidable, sandbox on dedicated WebView with @RequiresApi(17).</div></div>
              <div class="row" style="align-items:flex-start;gap:10px">${chip("high")}<div><b>FND-0045 · Legacy TrustManager pinning</b><br>→ Switch to OkHttp CertificatePinner + Network Security Config. Pin leaf + intermediate.</div></div>
            </div>
            <div class="muted small">§ 03 · FINDINGS DETAIL (37 findings, grouped by category, each ships with evidence + mitigation)</div>
            <div class="muted small">§ 04 · OWASP MASVS COMPLIANCE MATRIX · § 05 · EVIDENCE PACKAGE · § 06 · REPRO STEPS</div>
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
    const recipes = [
        ["SSL", "medusa", "universal_ssl_bypass", "TrustManager + OkHttp CertificatePinner + network-security-config.", "frida≥16 · android≥8"],
        ["ROOT", "medusa", "rootbeer_neuter", "Forces every RootBeer.is* + check* to return false. Gentle yet firm.", "rootbeer ≥ 0.0.7"],
        ["CRYPTO", "auto", "cipher_key_leak", "Logs SecretKeySpec ctor args + Cipher.doFinal in/out. Bring popcorn.", "auto-generated from findings"],
        ["PATCH", "stheno", "inject_frida_gadget", "Stheno patches the APK with frida-gadget. No root? No problem.", "non-rooted · re-sign required"],
        ["IPC", "medusa", "intent_monitor", "Dumps every Intent sent or received with extras, URIs, components.", "verbose · pair with [+] filter"],
        ["STORAGE", "medusa", "shared_prefs_watcher", "Taps SharedPreferences.Editor — hands you every put/get.", "android all"],
    ];
    return h`
    <div class="main">
      ${sectionHeader("R", "25 // AUTOMATION", "RECIPES LIBRARY")}
      <section class="row">
        <span class="chip low">ALL · 58</span>
        <span class="chip info">SSL · 12</span>
        <span class="chip info">ROOT · 9</span>
        <span class="chip info">CRYPTO · 14</span>
        <span class="chip info">IPC · 8</span>
        <span class="spacer"></span>
        <div class="input" style="width:280px"><span class="prompt">&gt;</span><input placeholder="search recipes…"><span class="cursor">_</span></div>
      </section>
      <section class="recipes-grid">
        ${recipes.map(([cat, origin, name, desc, compat]) => `
          <div class="recipe-card">
            <div class="cat-row"><span class="cat">${cat}</span><span class="grow"></span><span class="origin">${origin}</span></div>
            <div class="name">${name}</div>
            <div class="desc">${desc}</div>
            <div class="foot">
              <span class="compat">${compat}</span>
              <button class="btn primary" style="padding:4px 10px">[ LOAD ]</button>
            </div>
          </div>`).join("")}
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
        <br>setup helpers: <code>scripts/setup.sh --mobsf</code> · <code>--burp-rest-api</code> · <code>--device</code>.
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
    const id = ctx.params.fid || ctx.params.id || "FND-0042";
    return h`
    <div class="main">
      <div class="row muted small"><a href="#/projects">← back</a><span>· 21 · Finding Detail</span></div>
      <div class="finding" style="max-width:900px">
        <div class="head">
          <span class="tag">${id}</span>
          ${chip("crit")}
          <span class="tag" style="color:var(--magenta)">CWE-798</span>
          <span class="tag" style="color:var(--magenta)">OWASP M10</span>
          <span class="grow"></span>
          <span class="badge connected"><span class="dot">●</span>CONFIRMED</span>
        </div>
        <div class="title" style="font-size:20px">Hardcoded AES key in KeyManager.loadKey()</div>
        <div class="meta">The key you used to encrypt is also in .rodata. Attackers read both.</div>
        <div style="height:1px;background:var(--border);margin:8px 0"></div>
        <div class="block-label">// EVIDENCE</div>
        <pre class="code"><span class="ln">42</span>  public static SecretKeySpec loadKey() {
<span class="ln">43</span>      <span class="crit">byte[] key = "MedusaSays\u0000\u0000".getBytes();</span>
<span class="ln">44</span>      return new SecretKeySpec(key, "AES");
<span class="ln">45</span>  }
<span class="comment">// Ghidra cross-ref: libcrypto.so .rodata 0x1A2F contains the same 12 bytes.</span></pre>
        <div class="block-label">// AUTO-HOOK (frida)</div>
        <pre class="code">Java.perform(function () {
  var KM = Java.use('com.target.crypto.KeyManager');
  KM.loadKey.implementation = function () {
    var k = this.loadKey();
    console.log('[NEXUS] key=' + hex(k.getEncoded()));
    return k;
  };
});</pre>
        <div class="row"><div class="block-label mitigation-label">// MITIGATION</div><span class="muted small">— code-level, not vibes</span></div>
        <div class="mitigation">
          <div><b>01</b> Delete the hardcoded constant. Generate the key at first run and store it in Android Keystore via <code>KeyGenParameterSpec</code> (StrongBox-backed where available). The key never leaves TEE.</div>
          <div><b>02</b> If the key must be shared with a backend, use envelope encryption: fetch a DEK over mTLS, wrap it with a Keystore-held KEK. Rotate DEKs per session.</div>
          <div><b>03</b> Replace AES/CBC with AES/GCM (authenticated). Generate a fresh random IV per message and prepend it to ciphertext. Never static.</div>
          <div><b>04</b> Invalidate in-flight ciphertext encrypted under the leaked key. Rotate backend-side. Add detection for the old marker bytes and reject.</div>
        </div>
        <div class="row">
          <button class="btn primary">[ RUN HOOK ]</button>
          <button class="btn">[ COPY REMEDIATION ]</button>
          <span class="grow"></span>
          <button class="btn danger">[ DISMISS ]</button>
        </div>
      </div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN — Devices (multi-device ADB manager)
 * ═══════════════════════════════════════════════════════════════════════════ */

const DEVICE_CONNECT_FLAVORS = [
    { key: "adb_server",      label: "ADB + ffmpeg",        impl: "server-side",   load: "medium", value: "high",   default: true },
    { key: "webusb_yaadb",    label: "WebUSB / ya-webadb",  impl: "browser-direct", load: "medium", value: "high",   default: false },
    { key: "webrtc_signaling",label: "WebRTC + helper app", impl: "phone-side app", load: "low",    value: "medium", default: false },
];

// Currently active connection flavor (drives the device-list source).
let _activeFlavor = "adb_server";

function view_devices() {
    return h`
    <div class="main">
      ${sectionHeader("D", "04 // INTAKE", "DEVICES")}
      <div class="devices-bar">
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <span class="muted small uppercase">connect via:</span>
          ${DEVICE_CONNECT_FLAVORS.map((f) => `
            <button type="button" class="chip ${_activeFlavor === f.key ? "low" : "info"}" data-flavor="${f.key}" title="${f.impl} · load=${f.load} · value=${f.value}" style="cursor:pointer;border-style:solid">
              ${_activeFlavor === f.key ? "● " : "○ "}${f.label}
            </button>`).join("")}
        </div>
        <span class="spacer"></span>
        <form id="connect-form" class="row" style="gap:8px;flex-wrap:nowrap">
          <div class="input" style="width:200px">
            <span class="prompt">tcp&gt;</span>
            <input id="connect-host" placeholder="192.168.1.42" autocomplete="off">
          </div>
          <div class="input" style="width:90px">
            <input id="connect-port" placeholder="5555" value="5555" autocomplete="off">
          </div>
          <button class="btn primary" type="submit">[ CONNECT ]</button>
        </form>
        <button class="btn" id="devices-refresh">[ REFRESH ]</button>
      </div>
      <div class="muted small" id="connect-status" style="min-height:16px"></div>
      <section class="panel">
        <div class="panel-head">
          <span>// CONNECTED DEVICES</span>
          <span class="spacer"></span>
          <span class="muted" id="devices-count">scanning…</span>
        </div>
        <div class="panel-body" id="devices-grid-host">
          <div class="empty-state">scanning…</div>
        </div>
      </section>
      <section class="panel" id="device-detail-panel" style="display:none">
        <div class="panel-head">
          <span id="device-detail-title">// DEVICE DETAIL</span>
          <span class="spacer"></span>
          <button class="btn" id="device-detail-close">[ CLOSE ]</button>
        </div>
        <div class="panel-body" id="device-detail-host"></div>
      </section>
    </div>`;
}

let _devicesPollTimer = null;
let _mirrorTimer = null;
let _activeSerial = null;

async function mount_devices() {
    await refreshDevices();
    clearInterval(_devicesPollTimer);
    _devicesPollTimer = setInterval(() => {
        if (location.hash.startsWith("#/devices")) refreshDevices();
        else { clearInterval(_devicesPollTimer); clearInterval(_mirrorTimer); }
    }, 4000);

    const form = $("#connect-form");
    if (form) form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const host = $("#connect-host").value.trim();
        const port = $("#connect-port").value.trim() || "5555";
        if (!host) return;
        const status = $("#connect-status");
        status.innerHTML = `<span style="color:var(--acid)">↑ adb connect ${host}:${port}…</span>`;
        try {
            const fd = new FormData();
            fd.append("host", host);
            fd.append("port", port);
            const r = await fetch("/v1/devices/connect", { method: "POST", body: fd });
            const j = await r.json();
            const ok = !j.output.toLowerCase().includes("failed") && !j.output.toLowerCase().includes("cannot");
            status.innerHTML = `<span style="color:var(--${ok ? "acid" : "sev-crit"})">${j.output}</span>`;
            await refreshDevices();
        } catch (e) {
            status.innerHTML = `<span style="color:var(--sev-crit)">${e.message}</span>`;
        }
    });

    const refreshBtn = $("#devices-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", refreshDevices);

    const closeBtn = $("#device-detail-close");
    if (closeBtn) closeBtn.addEventListener("click", () => closeDeviceDetail());

    // ── Connection-flavor chip click handlers ─────────────────────────────
    $$("[data-flavor]").forEach((chip) => chip.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const flavor = chip.dataset.flavor;
        if (flavor === _activeFlavor) return;

        if (flavor === "adb_server") {
            _activeFlavor = "adb_server";
            redrawFlavorChips();
            setConnectStatus("flavor: ADB + ffmpeg (server-side)", "var(--acid)");
            await refreshDevices();
            return;
        }

        if (flavor === "webusb_yaadb") {
            await activateWebUSB();
            return;
        }

        if (flavor === "webrtc_signaling") {
            showWebRTCInfo();
            return;
        }
    }));
}

function redrawFlavorChips() {
    $$("[data-flavor]").forEach((c) => {
        const k = c.dataset.flavor;
        const active = k === _activeFlavor;
        c.classList.toggle("low", active);
        c.classList.toggle("info", !active);
        const flavor = DEVICE_CONNECT_FLAVORS.find((f) => f.key === k);
        c.innerHTML = (active ? "● " : "○ ") + (flavor ? flavor.label : k);
    });
}

function setConnectStatus(text, color) {
    const status = $("#connect-status");
    if (status) {
        status.innerHTML = `<span style="color:${color || "var(--muted)"}">${text}</span>`;
    }
}

// ── WebUSB / ya-webadb path ─────────────────────────────────────────────
async function activateWebUSB() {
    if (!("usb" in navigator)) {
        setConnectStatus(
            "✕ this browser doesn't expose <code>navigator.usb</code> — try Chrome/Edge over HTTPS or localhost",
            "var(--sev-crit)",
        );
        return;
    }
    setConnectStatus("↑ requesting USB device — pick the phone in the browser prompt", "var(--acid)");
    try {
        // ADB USB interface signature on Android.
        const usbDev = await navigator.usb.requestDevice({
            filters: [
                { classCode: 0xFF, subclassCode: 0x42, protocolCode: 0x01 }, // ADB
                { classCode: 0xFF, subclassCode: 0x42, protocolCode: 0x03 }, // ADB v2
            ],
        });
        _activeFlavor = "webusb_yaadb";
        redrawFlavorChips();
        renderWebUSBPanel(usbDev);
    } catch (e) {
        // User cancelled the chooser, or no matching device.
        setConnectStatus(`✕ ${e.name === "NotFoundError" ? "no ADB-class USB device picked" : e.message}`, "var(--sev-high)");
    }
}

function renderWebUSBPanel(usbDev) {
    const host = $("#devices-grid-host");
    if (!host) return;
    const product = usbDev.productName || "(unknown)";
    const vendor = usbDev.manufacturerName || "(unknown)";
    const vid = usbDev.vendorId.toString(16).padStart(4, "0");
    const pid = usbDev.productId.toString(16).padStart(4, "0");
    host.innerHTML = `
      <div class="empty-state">
        <div style="font-size:18px;color:var(--acid);letter-spacing:3px;margin-bottom:14px">WEBUSB DEVICE PICKED</div>
        <div class="t-mono" style="text-align:left;display:inline-block">
          <div>vendor:    <span style="color:var(--cyan)">${vendor}</span> (0x${vid})</div>
          <div>product:   <span style="color:var(--cyan)">${product}</span> (0x${pid})</div>
          <div>serial:    <span style="color:var(--cyan)">${usbDev.serialNumber || "(none)"}</span></div>
        </div>
        <div class="muted small" style="margin-top:18px;max-width:560px;margin-left:auto;margin-right:auto">
          We have the USB handle. Driving ADB over WebUSB needs the
          <a href="https://github.com/yume-chan/ya-webadb" target="_blank" style="color:var(--magenta)">ya-webadb</a>
          library bundled into the SPA — that's tagged <b>iter 2</b>. For now we hand the handle back so you
          can confirm the path works; commands still flow through server-side ADB.
        </div>
        <div style="margin-top:14px"><button class="btn" id="webusb-back">[ ← BACK TO ADB SERVER ]</button></div>
      </div>`;
    const back = $("#webusb-back");
    if (back) back.addEventListener("click", async () => {
        _activeFlavor = "adb_server";
        redrawFlavorChips();
        await refreshDevices();
    });
    setConnectStatus(
        `✓ WebUSB picked: ${product} (0x${vid}/0x${pid}) — bundle ya-webadb to enable command flow`,
        "var(--acid)",
    );
}

// ── WebRTC signaling info ───────────────────────────────────────────────
function showWebRTCInfo() {
    const host = $("#devices-grid-host");
    if (!host) return;
    _activeFlavor = "webrtc_signaling";
    redrawFlavorChips();
    host.innerHTML = `
      <div class="empty-state">
        <div style="font-size:18px;color:var(--magenta);letter-spacing:3px;margin-bottom:14px">WEBRTC + HELPER APP</div>
        <div class="t-mono" style="text-align:left;display:inline-block;line-height:1.7">
          <div>1. companion app on the device (APK to be built) opens a WebRTC peer.</div>
          <div>2. nexus signals it via <code>ws://nexus:8765/v1/devices/webrtc/signal</code>.</div>
          <div>3. data channel ferries adb commands; video track ferries the screen.</div>
        </div>
        <div class="muted small" style="margin-top:18px;max-width:560px;margin-left:auto;margin-right:auto">
          Lowest server load (only signaling), works through NAT, but <b>requires a phone-side app</b> we
          haven't built yet. <span style="color:var(--magenta)">iter 2.</span>
        </div>
        <div style="margin-top:14px"><button class="btn" id="webrtc-back">[ ← BACK TO ADB SERVER ]</button></div>
      </div>`;
    const back = $("#webrtc-back");
    if (back) back.addEventListener("click", async () => {
        _activeFlavor = "adb_server";
        redrawFlavorChips();
        await refreshDevices();
    });
    setConnectStatus("flavor: WebRTC + helper app (iter 2 — informational only)", "var(--magenta)");
}

async function refreshDevices() {
    const host = $("#devices-grid-host");
    if (!host) return;
    const devices = await getJSON("/v1/devices").catch(() => []);
    $("#devices-count").textContent = `${devices.length} attached`;
    const navCount = $("#nav-devices-count");
    if (navCount) navCount.textContent = devices.length ? String(devices.length) : "";

    if (!devices.length) {
        host.innerHTML = `
          <div class="empty-state">
            <div style="font-size:18px;color:var(--magenta);letter-spacing:3px">NO DEVICES</div>
            <div class="muted small" style="margin-top:8px">plug a USB device with debugging on, or use <b>tcp&gt;</b> above to <code>adb connect &lt;host&gt;</code></div>
          </div>`;
        return;
    }

    host.innerHTML = `<div class="devices-grid">${devices.map(deviceCardHtml).join("")}</div>`;
    $$("[data-serial]").forEach((card) => {
        card.addEventListener("click", () => openDeviceDetail(card.dataset.serial, devices.find((d) => d.serial === card.dataset.serial)));
    });
}

function deviceCardHtml(d) {
    const ok = d.state === "device";
    const stateColor = ok ? "var(--acid)" : (d.state === "unauthorized" ? "var(--sev-high)" : "var(--sev-crit)");
    return `
    <div class="device-card ${d.serial === _activeSerial ? "active" : ""}" data-serial="${d.serial}">
      <div class="head">
        <span class="t-mono" style="font-weight:700;flex:1">${d.model || d.product || d.serial}</span>
        <span class="badge" style="color:${stateColor};border-color:${stateColor}">${d.state.toUpperCase()}</span>
      </div>
      <div class="muted small t-mono">${d.serial}</div>
      ${ok ? `
      <div class="grid">
        <span class="key">ANDROID</span><span class="val">${d.android_release || "?"} (SDK ${d.android_sdk || "?"})</span>
        <span class="key">ABI</span><span class="val">${d.abi || "?"}</span>
        <span class="key">SCREEN</span><span class="val">${d.screen_width || "?"}×${d.screen_height || "?"}</span>
        <span class="key">DEBUG</span><span class="val" style="color:var(--${d.debuggable === "1" ? "sev-high" : "muted"})">${d.debuggable === "1" ? "yes" : "no"}</span>
        <span class="key">FRIDA</span><span class="val" style="color:var(--${d.frida_server_running ? "acid" : d.frida_server_staged ? "sev-high" : "muted"})">${d.frida_server_running ? "running" : d.frida_server_staged ? "staged" : "—"}</span>
        <span class="key">BRAND</span><span class="val">${d.brand || d.manufacturer || "?"}</span>
      </div>` : ""}
    </div>`;
}

function openDeviceDetail(serial, d) {
    _activeSerial = serial;
    document.querySelectorAll(".device-card").forEach((c) => c.classList.toggle("active", c.dataset.serial === serial));
    const panel = $("#device-detail-panel");
    const host = $("#device-detail-host");
    const title = $("#device-detail-title");
    if (!panel || !host) return;
    panel.style.display = "";
    title.textContent = `// DEVICE :: ${d?.model || serial}`;

    const ok = d?.state === "device";
    if (!ok) {
        host.innerHTML = `
          <div class="empty-state">
            <div style="color:var(--sev-crit);font-size:18px">${d?.state?.toUpperCase() || "OFFLINE"}</div>
            <div class="muted small">authorize USB debugging on the device, or <code>adb kill-server && adb start-server</code></div>
          </div>`;
        return;
    }

    const w = d.screen_width || 1080;
    const h = d.screen_height || 2400;
    host.innerHTML = `
      <div class="device-detail">
        <div class="device-mirror" id="mirror">
          <div class="mirror-stage">
            <img id="mirror-img" alt="screen mirror" data-w="${w}" data-h="${h}" />
            <img id="mirror-img-b" alt="" aria-hidden="true" />
          </div>
          <div class="mirror-foot">
            <span>MIRROR · ${w}×${h}</span>
            <span>·</span>
            <span>mjpeg primary · poll fallback</span>
            <span class="spacer"></span>
            <span id="mirror-status" style="color:var(--acid)">connecting…</span>
          </div>
        </div>
        <div class="col">
          <section class="panel">
            <div class="panel-head">// QUICK ACTIONS</div>
            <div class="panel-body col">
              <div class="row" style="flex-wrap:wrap;gap:8px">
                <button class="btn primary" data-action="frida">[ START FRIDA ]</button>
                <button class="btn" data-action="tcpip">[ ADB OVER TCP ]</button>
                <button class="btn" data-action="reboot">[ REBOOT ]</button>
                <button class="btn" data-action="reboot-bootloader">[ → BOOTLOADER ]</button>
                <button class="btn" data-action="reboot-recovery">[ → RECOVERY ]</button>
                <button class="btn danger" data-action="disconnect">[ DISCONNECT ]</button>
              </div>
              <div class="col" style="gap:6px">
                <div class="muted small" style="letter-spacing:2px">// INSTALL FROM A SAVED PROJECT</div>
                <div class="row" style="gap:8px;align-items:center">
                  <select id="install-from-project" class="input" style="flex:1;padding:6px 10px"><option>loading projects…</option></select>
                  <button class="btn primary" id="install-from-project-btn">[ INSTALL ]</button>
                </div>
                <div class="muted small" style="margin-top:6px;letter-spacing:2px">// OR UPLOAD A FRESH APK</div>
                <div class="row" style="gap:8px;align-items:center">
                  <input type="file" id="install-file" accept=".apk" style="display:none">
                  <button class="btn" onclick="document.getElementById('install-file').click()">[ ↑ UPLOAD NEW APK ]</button>
                  <span id="install-status" class="muted small grow"></span>
                </div>
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-head">// KEY EVENTS · adb shell input keyevent</div>
            <div class="panel-body">
              <div class="key-grid">
                <button class="btn" data-key="3">HOME</button>
                <button class="btn" data-key="4">BACK</button>
                <button class="btn" data-key="187">RECENTS</button>
                <button class="btn" data-key="26">POWER</button>
                <button class="btn" data-key="24">VOL+</button>
                <button class="btn" data-key="25">VOL-</button>
                <button class="btn" data-key="82">MENU</button>
                <button class="btn" data-key="66">ENTER</button>
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-head">// SHELL</div>
            <div class="panel-body col">
              <form id="shell-form" class="row" style="gap:8px">
                <div class="input grow">
                  <span class="prompt">$</span>
                  <input id="shell-input" placeholder="getprop ro.build.fingerprint" autocomplete="off">
                  <span class="cursor">_</span>
                </div>
                <button class="btn primary" type="submit">[ RUN ]</button>
              </form>
              <pre id="shell-out" class="code" style="max-height:240px"></pre>
            </div>
          </section>
        </div>
      </div>`;

    bindMirror(serial, w, h);
    bindActions(serial);
    bindKeys(serial);
    bindShell(serial);
    bindInstall(serial);
}

function bindMirror(serial, w, h) {
    const mirror = $("#mirror");
    const imgA = $("#mirror-img");          // primary
    const imgB = $("#mirror-img-b");        // backbuffer (polling fallback)
    if (!mirror || !imgA) return;
    const status = $("#mirror-status");
    const fps = 6;

    // ── 1. PRIMARY: MJPEG stream — browser renders multipart natively ────────
    // No JS polling, no <img> swap → no flicker, single TCP connection.
    let usingMjpeg = true;
    let pollTimer = null;
    let inFlight = false;
    let fails = 0;
    let active = 0;

    function setStatus(text, color) {
        if (!status) return;
        status.textContent = text;
        status.style.color = color || "var(--acid)";
    }

    imgA.style.opacity = "1";
    imgA.src = `/v1/devices/${encodeURIComponent(serial)}/screen.mjpeg?fps=${fps}&_=${Date.now()}`;
    setStatus(`live · mjpeg @ ${fps}fps`);
    hideMirrorError(mirror);

    // If no frame painted in 4s, assume mjpeg failed → fall back.
    const mjpegStallTimer = setTimeout(() => {
        if (imgA.naturalWidth === 0) imgA.dispatchEvent(new Event("error"));
    }, 4000);
    imgA.addEventListener("load", () => clearTimeout(mjpegStallTimer), { once: true });
    imgA.addEventListener("error", () => {
        if (!usingMjpeg) return;
        clearTimeout(mjpegStallTimer);
        setStatus("mjpeg unavailable → polling", "var(--sev-high)");
        startPolling();
    }, { once: true });

    // ── 2. FALLBACK: double-buffered PNG polling ─────────────────────────────
    async function pollOnce() {
        if (inFlight) return;            // skip overlapping ticks
        inFlight = true;
        try {
            const url = `/v1/devices/${encodeURIComponent(serial)}/screencap.png?t=${Date.now()}`;
            const r = await fetch(url, { cache: "no-store" });
            if (!r.ok) {
                fails++;
                if (fails > 2) {
                    setStatus("stalled · polling", "var(--sev-crit)");
                    showMirrorError(mirror, await safeJSON(r));
                }
                return;
            }
            const blob = await r.blob();
            const buffers = [imgA, imgB];
            const next = buffers[1 - active];
            if (!next) {
                // Backbuffer not present → just swap on the primary (might flicker).
                const obj0 = URL.createObjectURL(blob);
                const old0 = imgA.dataset.lastUrl;
                imgA.src = obj0;
                if (old0) URL.revokeObjectURL(old0);
                imgA.dataset.lastUrl = obj0;
            } else {
                const oldUrl = next.dataset.lastUrl;
                const obj = URL.createObjectURL(blob);
                next.src = obj;
                try { await next.decode(); } catch { /* swap anyway */ }
                buffers[active].style.opacity = "0";
                next.style.opacity = "1";
                next.dataset.lastUrl = obj;
                if (oldUrl) URL.revokeObjectURL(oldUrl);
                active = 1 - active;
            }
            fails = 0;
            const path = r.headers.get("X-MNexus-Path") || "?";
            setStatus(`live · poll · ${path}`);
            hideMirrorError(mirror);
        } catch (e) {
            fails++;
            if (fails > 2) {
                setStatus("stalled · polling", "var(--sev-crit)");
                showMirrorError(mirror, { error: "network", detail: e.message });
            }
        } finally {
            inFlight = false;
        }
    }

    function startPolling() {
        usingMjpeg = false;
        pollOnce();
        clearInterval(pollTimer);
        pollTimer = setInterval(() => {
            if (!location.hash.startsWith("#/devices")) { clearInterval(pollTimer); return; }
            if (_activeSerial !== serial) { clearInterval(pollTimer); return; }
            pollOnce();
        }, 800);
        _mirrorTimer = pollTimer;
    }

    // ── 3. tap-to-click ──────────────────────────────────────────────────────
    function tapHandler(ev) {
        const target = ev.currentTarget;
        const rect = target.getBoundingClientRect();
        const xRatio = (ev.clientX - rect.left) / rect.width;
        const yRatio = (ev.clientY - rect.top) / rect.height;
        const x = Math.round(xRatio * w);
        const y = Math.round(yRatio * h);
        const fd = new FormData(); fd.append("x", x); fd.append("y", y);
        fetch(`/v1/devices/${encodeURIComponent(serial)}/tap`, { method: "POST", body: fd });
    }
    imgA.addEventListener("click", tapHandler);
    if (imgB) imgB.addEventListener("click", tapHandler);
}

async function safeJSON(response) {
    try { return await response.json(); } catch { return { error: `HTTP ${response.status}`, detail: response.statusText }; }
}

function showMirrorError(mirror, payload) {
    if (!mirror) return;
    let banner = mirror.querySelector(".mirror-error");
    if (!banner) {
        banner = document.createElement("div");
        banner.className = "mirror-error";
        banner.style.cssText = "padding:14px;background:#1a0008;border-top:1px solid var(--border-crit);color:var(--sev-crit);font-size:11px;line-height:1.55;display:flex;flex-direction:column;gap:6px";
        mirror.appendChild(banner);
    }
    const detail = payload?.detail || payload || {};
    const lines = [];
    if (typeof detail === "string") lines.push(detail);
    else {
        if (detail.error) lines.push(`<b>${detail.error}</b>`);
        if (detail.exec_out) lines.push(`exec-out: ${detail.exec_out}`);
        if (detail.temp_file) lines.push(`temp-file: ${detail.temp_file}`);
        if (detail.hint) lines.push(`<span style="color:var(--magenta)">→ ${detail.hint}</span>`);
    }
    banner.innerHTML = `
      <div>screencap stalled — diagnostics:</div>
      <div style="font-family:var(--mono)">${lines.join("<br>")}</div>
      <div><a href="/v1/devices/${encodeURIComponent(_activeSerial)}/screencap-debug" target="_blank" style="color:var(--cyan)">[ open /screencap-debug ]</a></div>`;
}

function hideMirrorError(mirror) {
    const banner = mirror?.querySelector(".mirror-error");
    if (banner) banner.remove();
}

function bindActions(serial) {
    $$("[data-action]").forEach((btn) => btn.addEventListener("click", async () => {
        const a = btn.dataset.action;
        const orig = btn.textContent;
        btn.textContent = "[ … ]";
        try {
            if (a === "frida") {
                const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/frida-server`, { method: "POST" });
                const j = await r.json();
                btn.textContent = j.running ? `[ FRIDA pid=${j.pid} ]` : "[ FAILED ]";
                btn.style.color = j.running ? "var(--acid)" : "var(--sev-crit)";
            } else if (a === "tcpip") {
                const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/tcpip`, { method: "POST", body: new FormData() });
                const j = await r.json();
                btn.textContent = `[ TCP/IP :${j.port} ]`;
            } else if (a === "reboot" || a === "reboot-bootloader" || a === "reboot-recovery") {
                const fd = new FormData();
                if (a === "reboot-bootloader") fd.append("mode", "bootloader");
                if (a === "reboot-recovery") fd.append("mode", "recovery");
                await fetch(`/v1/devices/${encodeURIComponent(serial)}/reboot`, { method: "POST", body: fd });
                btn.textContent = "[ REBOOTING ]"; btn.style.color = "var(--sev-high)";
            } else if (a === "disconnect") {
                await fetch(`/v1/devices/${encodeURIComponent(serial)}/disconnect`, { method: "POST" });
                closeDeviceDetail(); refreshDevices();
            }
        } catch (e) {
            btn.textContent = "[ ERROR ]"; btn.style.color = "var(--sev-crit)";
            console.error(e);
        }
        setTimeout(() => { if (btn.textContent.includes("…") || btn.textContent === "[ ERROR ]") btn.textContent = orig; }, 2500);
    }));
}

function bindKeys(serial) {
    $$("[data-key]").forEach((btn) => btn.addEventListener("click", async () => {
        const fd = new FormData(); fd.append("keycode", btn.dataset.key);
        btn.style.background = "var(--bg-accent-panel)";
        await fetch(`/v1/devices/${encodeURIComponent(serial)}/key`, { method: "POST", body: fd });
        setTimeout(() => { btn.style.background = ""; }, 200);
    }));
}

function bindShell(serial) {
    const form = $("#shell-form"); if (!form) return;
    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const cmd = $("#shell-input").value.trim(); if (!cmd) return;
        const out = $("#shell-out");
        out.textContent += `$ ${cmd}\n`;
        const fd = new FormData(); fd.append("cmd", cmd);
        try {
            const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/shell`, { method: "POST", body: fd });
            const j = await r.json();
            out.textContent += (j.output || "(no output)") + "\n";
        } catch (e) {
            out.textContent += `<error: ${e.message}>\n`;
        }
        out.scrollTop = out.scrollHeight;
        $("#shell-input").value = "";
    });
}

async function bindInstall(serial) {
    const status = $("#install-status");
    const setStatus = (text, color) => { if (status) { status.textContent = text; status.style.color = color || ""; } };

    // ── 1. Populate the saved-projects dropdown from /v1/projects ──
    const select = $("#install-from-project");
    if (select) {
        const projects = await getJSON("/v1/projects").catch(() => []);
        if (!projects.length) {
            select.innerHTML = `<option value="">— no saved projects yet (upload one at /#/scan) —</option>`;
            select.disabled = true;
        } else {
            select.disabled = false;
            select.innerHTML = `<option value="">— pick a saved project —</option>` +
                projects.map((p) => {
                    const label = `${p.package_name || p.name || p.id}` +
                        (p.version_name ? ` v${p.version_name}` : "") +
                        ` · ${p.id}`;
                    return `<option value="${p.id}">${label}</option>`;
                }).join("");
        }
    }

    // ── 2. Install-from-project button ──
    const installBtn = $("#install-from-project-btn");
    if (installBtn) installBtn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const projectId = select?.value;
        if (!projectId) { setStatus("pick a project from the dropdown first", "var(--sev-high)"); return; }
        setStatus(`pushing ${projectId} via adb install -r…`, "var(--acid)");
        installBtn.disabled = true;
        try {
            const fd = new FormData(); fd.append("project_id", projectId);
            const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/install-project`, { method: "POST", body: fd });
            const j = await r.json().catch(() => ({}));
            if (!r.ok) {
                const detail = j.detail || j;
                setStatus(`✕ ${typeof detail === "string" ? detail : (detail.error || "install failed")}`, "var(--sev-crit)");
                return;
            }
            setStatus(
                j.success
                    ? `✓ installed ${j.package} v${j.version} (${j.apk})`
                    : `✕ ${(j.output || "").split("\n").slice(-2).join(" ").trim() || "adb refused"}`,
                j.success ? "var(--acid)" : "var(--sev-crit)",
            );
        } catch (e) {
            setStatus(`✕ ${e.message}`, "var(--sev-crit)");
        } finally {
            installBtn.disabled = false;
        }
    });

    // ── 3. Fresh-file upload (existing path, kept as a secondary option) ──
    const input = $("#install-file");
    if (input) input.addEventListener("change", async () => {
        const f = input.files?.[0]; if (!f) return;
        setStatus(`installing ${f.name} (${fmtBytes(f.size)})…`, "var(--acid)");
        const fd = new FormData(); fd.append("file", f);
        try {
            const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/install`, { method: "POST", body: fd });
            const j = await r.json();
            setStatus(
                j.success ? "✓ installed" : `✕ ${(j.output || "").split("\n").slice(-2).join(" ")}`,
                j.success ? "var(--acid)" : "var(--sev-crit)",
            );
        } catch (e) {
            setStatus(`✕ ${e.message}`, "var(--sev-crit)");
        }
    });
}

function closeDeviceDetail() {
    _activeSerial = null;
    clearInterval(_mirrorTimer);
    const panel = $("#device-detail-panel");
    if (panel) panel.style.display = "none";
    document.querySelectorAll(".device-card").forEach((c) => c.classList.remove("active"));
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  mount hooks for every wired screen
 * ═══════════════════════════════════════════════════════════════════════════ */

async function mount_project_overview(ctx) {
    const id = ctx.params.id;
    let project;
    try {
        project = await getJSON(`/v1/projects/${encodeURIComponent(id)}`);
    } catch (e) {
        const view = $("#view main, .main");
        if (view) view.innerHTML += `<div class="empty-state"><div style="color:var(--sev-crit);font-size:18px">project ${id} not found — <a href="#/projects">back to list</a></div></div>`;
        return;
    }
    const surface = project.attack_surface || {};
    const counts = project.findings_by_severity || surface.findings_by_severity || {};
    const score = project.risk_score || 0;

    // Replace the whole main pane with real data. Keep the tab bar.
    const main = $(".main");
    if (!main) return;

    const severityRows = [
        ["CRIT", "sev-crit", counts.critical || 0],
        ["HIGH", "sev-high", counts.high || 0],
        ["MED",  "sev-med",  counts.medium || 0],
        ["LOW",  "sev-low",  counts.low || 0],
        ["INFO", "muted",    counts.info || 0],
    ];

    const findingsList = (surface.findings || []).slice(0, 8).map((f) => `
        <a href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" class="row" style="padding:8px 12px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;text-decoration:none;color:inherit">
            ${chip((f.severity || "info").toLowerCase())}
            <span class="grow">${f.title}</span>
            <span class="t-muted">[${f.source_engine || "?"}]</span>
        </a>`).join("") || `<div class="empty-state">no findings yet — every static engine returned []. Wire real detection in iteration 2.</div>`;

    main.innerHTML = h`
      <div class="muted small uppercase">🔱 NEXUS / ${id} / overview · ${project.package_name || "—"} v${project.version_name || "?"}</div>
      ${projectTabs(id, "overview")}
      <section class="row" style="align-items:flex-start;gap:24px">
        <div class="col" style="width:280px">
          <div class="risk-gauge" style="--deg: ${Math.round((score / 100) * 360)}deg">
            <div class="arc"></div>
            <div class="label">
              <div class="value">${score.toFixed(1)}</div>
              <div class="caption">RISK / 100</div>
            </div>
          </div>
          <section class="panel">
            <div class="panel-head">// SEVERITY</div>
            <div class="panel-body col" style="gap:4px">
              ${severityRows.map(([label, color, n]) => `
                <div class="row">
                  <span style="color:var(--${color});width:40px">${label}</span>
                  <span class="t-mono" style="color:var(--${color})">${bar(n, 16)}</span>
                  <span class="grow" style="text-align:right">${String(n).padStart(2, "0")}</span>
                </div>`).join("")}
            </div>
          </section>
        </div>
        <div class="col grow">
          <section class="panel">
            <div class="panel-head"><span>// FINDINGS TIMELINE</span><span class="spacer"></span><span class="muted">${(surface.findings || []).length} total</span></div>
            <div class="panel-body col" style="gap:8px">${findingsList}</div>
          </section>
          <section class="panel">
            <div class="panel-head">// ATTACK SURFACE</div>
            <div class="panel-body row" style="gap:24px">
              <div class="col grow"><span class="muted small uppercase">COMPONENTS</span><span class="t-mono">${(surface.exported_components || []).length} exported</span></div>
              <div class="col grow"><span class="muted small uppercase">DEEP LINKS</span><span class="t-mono">${(surface.deeplinks || []).length}</span></div>
              <div class="col grow"><span class="muted small uppercase">NATIVE LIBS</span><span class="t-mono">${(surface.native_libraries || []).length}</span></div>
              <div class="col grow"><span class="muted small uppercase">SSL PINNING</span><span class="t-mono">${surface.ssl_pinning_detected ? "detected · " + (surface.ssl_pinning_library || "?") : "none"}</span></div>
            </div>
          </section>
        </div>
      </section>`;
}

function bar(n, max) {
    const fill = Math.min(Math.round((n / Math.max(max, 1)) * 16), 16);
    return "█".repeat(fill) + "░".repeat(16 - fill);
}

async function mount_project_static(ctx) {
    const id = ctx.params.id;
    let findings = [];
    try {
        findings = await getJSON(`/v1/projects/${encodeURIComponent(id)}/findings`);
    } catch (e) { /* empty */ }

    const panel = $$(".panel")[2];  // the findings panel is the 3rd in the Static layout
    if (!panel) return;
    const body = panel.querySelector(".panel-body");
    if (!body) return;
    if (!findings.length) {
        body.innerHTML = `<div class="empty-state">no findings yet — static engines are still stubs. JADX/MobSF/Ghidra run on upload but currently emit []. <a href="#/scan">Ingest an APK</a> and check back once detection rules land.</div>`;
        return;
    }
    body.innerHTML = findings.slice(0, 10).map((f) => `
        <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
          <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine || "?"}]</span></div>
          <div class="title">${f.title}</div>
          <div class="meta">${f.location || "?"} · ${f.cwe_id || ""} ${f.owasp_mobile || ""}</div>
        </a>`).join("");
}

async function mount_project_dynamic(ctx) {
    const id = ctx.params.id;
    // Auto-hooks first; fall back to recipes.
    let hooks = [];
    if (id) {
        try { hooks = await getJSON(`/v1/projects/${encodeURIComponent(id)}/hooks`); }
        catch (e) { /* empty */ }
    }
    if (!hooks.length) {
        try {
            const recipes = await getJSON("/v1/recipes");
            hooks = recipes.map((r) => ({ name: r.name, description: r.description, source_finding_id: null }));
        } catch (e) { /* empty */ }
    }

    const panels = $$(".panel");
    const hooksPanel = panels[0];
    if (hooksPanel) {
        const body = hooksPanel.querySelector(".panel-body");
        if (body) {
            const checked = new Set(hooks.slice(0, Math.min(3, hooks.length)).map((h) => h.name));
            body.innerHTML = `<div class="muted small">Auto-hooks generated from this project's surface. Untick at your own risk.</div>`
                + hooks.map((h) => {
                    const on = checked.has(h.name);
                    return `
                    <label class="row" data-hook="${h.name}" style="padding:6px 10px;background:${on ? "var(--bg-accent-panel)" : "var(--bg-panel)"};border:1px solid ${on ? "var(--border-accent)" : "var(--border)"};border-radius:2px;cursor:pointer">
                      <input type="checkbox" ${on ? "checked" : ""} style="accent-color:var(--acid)">
                      <span class="t-mono" style="color:${on ? "var(--acid)" : "var(--muted)"};flex:1">${h.name}</span>
                      <span class="muted small">${h.source_finding_id ? "auto" : "recipe"}</span>
                    </label>`;
                }).join("")
                + `<div class="row" style="margin-top:10px;gap:8px">
                     <button class="btn primary" id="dyn-start">[ START SESSION ]</button>
                     <button class="btn" id="dyn-stop">[ STOP ]</button>
                     <a class="btn" href="#/recipes">[ + RECIPES ]</a>
                   </div>`;
        }
    }

    let activeSession = null;
    const consolePanel = panels[1];
    const consoleEl = consolePanel?.querySelector(".panel-body.console");
    const renderLog = (lines) => {
        if (!consoleEl) return;
        consoleEl.innerHTML = lines.map((l) => `<div><span class="${classifyTraceClass(l.channel)}">${escapeHtml(l.line)}</span></div>`).join("")
            || `<span class="muted">no events</span>`;
    };

    const startBtn = $("#dyn-start");
    const stopBtn = $("#dyn-stop");
    if (startBtn && id) {
        startBtn.addEventListener("click", async () => {
            const selected = $$('label[data-hook] input[type="checkbox"]')
                .map((c, i) => c.checked ? $$('label[data-hook]')[i].dataset.hook : null)
                .filter(Boolean);
            startBtn.textContent = "[ STARTING… ]";
            const fd = new FormData(); fd.append("hooks", selected.join(","));
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/dynamic/start`, { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) { startBtn.textContent = "[ FAILED ]"; startBtn.style.color = "var(--sev-crit)"; return; }
            activeSession = j.session_id;
            startBtn.textContent = `[ ATTACHED · ${activeSession} ]`;
            startBtn.style.color = "var(--acid)";
            renderLog(j.log);
        });
    }
    if (stopBtn && id) {
        stopBtn.addEventListener("click", async () => {
            if (!activeSession) return;
            const fd = new FormData(); fd.append("session_id", activeSession);
            const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/dynamic/stop`, { method: "POST", body: fd });
            const j = await r.json();
            if (r.ok) { stopBtn.textContent = "[ DETACHED ]"; renderLog(j.log); }
        });
    }
}

async function mount_project_network(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/traffic`).catch(() => null);
    if (!data) return;
    if (!data.captured.length) return; // keep the demo rows from the view
    const panel = $$(".panel")[0];
    const body = panel?.querySelector(".panel-body.tight");
    if (!body) return;
    body.innerHTML = `
      <div class="table-hdr" style="grid-template-columns: 50px 180px 1fr 70px 80px 60px 90px">
        <span>M</span><span>HOST</span><span>PATH</span><span>STATUS</span><span>SIZE</span><span>MS</span><span>FLAGS</span>
      </div>` + data.captured.map((row) => {
        const m = row.method || "GET";
        const sev = row.severity || "info";
        return `
          <a class="table-row" href="#/project/${encodeURIComponent(id)}/api-map" style="grid-template-columns: 50px 180px 1fr 70px 80px 60px 90px;text-decoration:none;color:inherit">
            <span class="t-mono" style="color:${m === "POST" ? "var(--acid)" : "var(--cyan)"};font-weight:700">${m}</span>
            <span class="t-mono" style="color:var(--cyan)">${row.host || "?"}</span>
            <span class="t-mono" style="color:var(--cyan)">${row.path || "/"}</span>
            <span class="t-mono" style="color:var(--${(row.status || 0) < 300 ? "acid" : (row.status || 0) < 500 ? "sev-high" : "sev-crit"});font-weight:700">${row.status || "—"}</span>
            <span class="t-muted">${fmtBytes(row.size || 0)}</span>
            <span class="t-muted">${row.ms || "—"}</span>
            <span style="font-size:9px;color:var(--sev-${sev});font-weight:700">${(row.flags || []).map((f) => "[" + f + "]").join("")}</span>
          </a>`;
    }).join("");
}

async function mount_device_pull() {
    const info = await getJSON("/v1/device/info").catch(() => ({connected: false, reason: "network error"}));
    const pkgs = info.connected ? await getJSON("/v1/device/packages").catch(() => []) : [];
    const badgeRoot = $(".row .badge");
    if (badgeRoot) {
        badgeRoot.innerHTML = info.connected
            ? `<span class="dot">●</span>${info.model || "device"} · android ${info.android_release || "?"}`
            : `<span class="dot">●</span>NO DEVICE`;
        badgeRoot.classList.toggle("connected", info.connected);
    }

    const panel = $(".panel");
    if (!panel) return;
    panel.querySelector(".panel-head").innerHTML = `// PACKAGES · ${pkgs.length} ${info.connected ? "· " + info.abi : ""}`;
    const body = panel.querySelector(".panel-body");

    if (!info.connected) {
        body.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit);font-size:20px;letter-spacing:3px">NO DEVICE CONNECTED</div><div class="muted">${info.reason || ""}</div><div class="muted small" style="margin-top:12px">plug a device, authorize USB debugging, then reload this screen.</div></div>`;
        return;
    }
    if (!pkgs.length) {
        body.innerHTML = `<div class="empty-state">no packages matched.</div>`;
        return;
    }
    body.innerHTML = `
        <div class="table-hdr" style="grid-template-columns: 1fr 120px">
            <span>PACKAGE</span><span></span>
        </div>` +
        pkgs.slice(0, 50).map(({ package: pkg }) => `
            <div class="table-row" style="grid-template-columns: 1fr 120px">
                <span class="t-mono">${pkg}</span>
                <span style="text-align:right"><button class="btn primary" data-pull="${pkg}" style="padding:4px 10px">[ PULL ]</button></span>
            </div>`).join("");

    $$("[data-pull]").forEach((btn) => btn.addEventListener("click", async () => {
        const pkg = btn.dataset.pull;
        btn.textContent = "[ PULLING… ]";
        btn.disabled = true;
        try {
            const fd = new FormData(); fd.append("package", pkg);
            const r = await fetch("/v1/device/pull", { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            btn.textContent = `[ PULLED ${j.count} ]`;
            btn.style.color = "var(--acid)";
        } catch (e) {
            btn.textContent = `[ FAILED ]`;
            btn.style.color = "var(--sev-crit)";
        }
    }));
}

async function mount_device_bridge() {
    fillDeviceStatusStrip();
    const info = await getJSON("/v1/device/info/full").catch(() => ({connected: false, reason: "network error"}));
    const badge = $("#bridge-badge");
    if (badge) {
        const ok = !!info.connected;
        badge.classList.toggle("connected", ok);
        badge.classList.toggle("scanning", !ok);
        badge.innerHTML = `<span class="dot">●</span>${ok ? "CONNECTED" : "NO DEVICE"}`;
    }

    const devicePanel = $("#bridge-info");
    if (!info.connected) {
        if (devicePanel) devicePanel.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit);font-size:18px">NO DEVICE</div><div class="muted small">${info.reason || ""}</div></div>`;
        const empty = '<div class="muted small">— device offline —</div>';
        if ($("#bridge-battery")) $("#bridge-battery").innerHTML = empty;
        if ($("#bridge-memory")) $("#bridge-memory").innerHTML = empty;
        if ($("#bridge-storage")) $("#bridge-storage").innerHTML = empty;
    } else if (devicePanel) {
        const row = (label, val, color) => `<div class="row"><span class="muted small" style="width:160px">${label}</span><span class="t-mono"${color ? ` style="color:${color}"` : ""}>${val || "—"}</span></div>`;
        const debuggable = info.debuggable === "1";
        devicePanel.innerHTML = [
            row("DEVICE", info.device),
            row("PRODUCT", info.product),
            row("MODEL", `${info.manufacturer || ""} ${info.model || ""}`.trim()),
            row("BRAND", info.brand),
            row("SERIAL NO", info.serial_no),
            row("PLATFORM", info.platform || info.hardware),
            row("ABI", info.abi),
            row("ABI LIST", info.abi_list),
            row("ANDROID", info.android),
            row("API LEVEL", info.api_level),
            row("FINGERPRINT", info.fingerprint),
            row("SECURITY PATCH", info.security_patch, "var(--cyan)"),
            row("BUILD DATE", info.build_date),
            row("BUILD ID", info.build_id),
            row("RESOLUTION", info.resolution),
            row("DISPLAY DENSITY", info.display_density ? `${info.display_density} dpi` : ""),
            row("DEBUGGABLE", debuggable ? "yes" : "no", debuggable ? "var(--sev-high)" : "var(--acid)"),
        ].join("");

        // Battery
        const b = info.battery || {};
        const batRow = (k, v, c) => v == null ? "" : `<div class="row"><span class="muted small" style="width:140px">${k}</span><span class="t-mono"${c ? ` style="color:${c}"` : ""}>${v}</span></div>`;
        const lvl = parseInt(b.level || "0", 10);
        const lvlColor = lvl >= 50 ? "var(--acid)" : lvl >= 20 ? "var(--sev-high)" : "var(--sev-crit)";
        $("#bridge-battery").innerHTML = (Object.keys(b).length === 0)
            ? `<div class="muted small">battery info unavailable</div>`
            : [
                batRow("LEVEL", b.level ? `${b.level}%` : null, lvlColor),
                batRow("STATUS", b.status),
                batRow("HEALTH", b.health),
                batRow("VOLTAGE", b.voltage ? `${b.voltage} mV` : null),
                batRow("TEMPERATURE", b.temperature ? `${(parseInt(b.temperature, 10) / 10).toFixed(1)} °C` : null),
                batRow("AC", b.ac_powered),
                batRow("USB", b.usb_powered),
                batRow("WIRELESS", b.wireless_powered),
                batRow("TECHNOLOGY", b.technology),
            ].join("");

        // Memory
        const mem = info.memory || {};
        $("#bridge-memory").innerHTML = Object.keys(mem).length
            ? Object.entries(mem).map(([k, v]) => `<div class="row"><span class="muted small" style="width:140px">${k}</span><span class="t-mono">${v}</span></div>`).join("")
            : `<div class="muted small">/proc/meminfo unreadable</div>`;

        // Storage
        const st = info.storage || [];
        $("#bridge-storage").innerHTML = st.length
            ? `<div class="table-hdr" style="grid-template-columns: 1fr 80px 80px 80px 60px 1fr"><span>FS</span><span>SIZE</span><span>USED</span><span>FREE</span><span>%</span><span>MOUNT</span></div>`
              + st.map((r) => `<div class="table-row" style="grid-template-columns: 1fr 80px 80px 80px 60px 1fr"><span class="t-mono">${r.filesystem}</span><span class="t-mono">${r.size}</span><span class="t-mono">${r.used}</span><span class="t-mono">${r.available}</span><span class="t-mono" style="color:${parseInt(r.use_pct, 10) > 90 ? "var(--sev-crit)" : "var(--cyan)"}">${r.use_pct}</span><span class="t-mono">${r.mounted_on}</span></div>`).join("")
            : `<div class="muted small">df unavailable</div>`;
    }

    // Wire action buttons.
    $$(".btn").forEach((btn) => {
        const label = btn.textContent.trim().toUpperCase();
        if (label.includes("START FRIDA")) {
            btn.addEventListener("click", async () => {
                btn.textContent = "[ STARTING… ]";
                try {
                    const r = await fetch("/v1/device/frida/start", { method: "POST" });
                    const j = await r.json();
                    if (!r.ok) throw new Error(j.detail || r.statusText);
                    btn.textContent = j.running ? `[ RUNNING pid=${j.pid} ]` : "[ FAILED TO START ]";
                    btn.style.color = j.running ? "var(--acid)" : "var(--sev-crit)";
                } catch (e) {
                    btn.textContent = "[ ERROR ]";
                    btn.style.color = "var(--sev-crit)";
                }
            });
        } else if (label.includes("PUSH SCRIPTS")) {
            btn.addEventListener("click", () => { btn.textContent = "[ NOT WIRED — see /v1/recipes ]"; btn.style.color = "var(--sev-high)"; });
        } else if (label.includes("PATCH WITH STHENO")) {
            btn.addEventListener("click", () => { btn.textContent = "[ STHENO BINDING PENDING ]"; btn.style.color = "var(--sev-high)"; });
        } else if (label.includes("FORCE REBOOT")) {
            btn.addEventListener("click", () => {
                if (!confirm("really reboot the connected device?")) return;
                btn.textContent = "[ NOT WIRED — adb reboot disabled ]"; btn.style.color = "var(--sev-high)";
            });
        }
    });
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  ADB CONTROL PANEL — ADBugger-style command surface
 *
 *  Shared state across this whole route family:
 *    window.NEXUS_ADB = {
 *      serial:  string | null    — currently selected device
 *      package: string | null    — currently selected app package
 *      devices: array            — last fetched /v1/devices result
 *    }
 *  Persisted in sessionStorage so it survives screen switches.
 * ═══════════════════════════════════════════════════════════════════════════ */

window.NEXUS_ADB = window.NEXUS_ADB || (function () {
    let stored = {};
    try { stored = JSON.parse(sessionStorage.getItem("nexus.adb") || "{}"); } catch (e) {}
    return { serial: stored.serial || null, package: stored.package || null, devices: [] };
})();

function adbStateSave() {
    try { sessionStorage.setItem("nexus.adb", JSON.stringify({ serial: NEXUS_ADB.serial, package: NEXUS_ADB.package })); } catch (e) {}
}

async function adbRefreshDevices() {
    NEXUS_ADB.devices = await getJSON("/v1/devices").catch(() => []);
    if (!NEXUS_ADB.serial && NEXUS_ADB.devices.length) {
        const first = NEXUS_ADB.devices.find((d) => d.state === "device");
        if (first) NEXUS_ADB.serial = first.serial;
    }
    if (NEXUS_ADB.serial && !NEXUS_ADB.devices.some((d) => d.serial === NEXUS_ADB.serial)) {
        NEXUS_ADB.serial = null;
    }
    adbStateSave();
    return NEXUS_ADB.devices;
}

async function adbRefreshPackages() {
    if (NEXUS_ADB.package) return;
    const projects = await getJSON("/v1/projects").catch(() => []);
    if (projects.length && projects[0].package_name) {
        NEXUS_ADB.package = projects[0].package_name;
        adbStateSave();
    }
}

function deviceSelectorBar() {
    const devices = NEXUS_ADB.devices || [];
    const opts = devices.length
        ? devices.map((d) => {
            const label = d.state === "device"
                ? `${d.serial}${d.model ? " · " + d.model : ""}${d.android_release ? " · A" + d.android_release : ""}`
                : `${d.serial} · ${d.state}`;
            return `<option value="${d.serial}" ${d.serial === NEXUS_ADB.serial ? "selected" : ""}>${label}</option>`;
        }).join("")
        : `<option value="">— no devices —</option>`;
    return `
      <section class="row" style="gap:10px;align-items:center;padding:10px 12px;background:var(--bg-panel);border:1px solid var(--border-accent);border-radius:2px;margin-bottom:14px">
        <span class="muted small uppercase">device</span>
        <select id="adb-serial" class="input" style="min-width:280px">${opts}</select>
        <button class="btn" id="adb-refresh">[ ⟳ ]</button>
        <span style="width:1px;height:24px;background:var(--border)"></span>
        <span class="muted small uppercase">package</span>
        <select id="adb-package-preset" class="input" style="min-width:200px">
          <option value="">— pick / type below —</option>
        </select>
        <input id="adb-package" class="input" style="min-width:240px" value="${NEXUS_ADB.package || ""}" placeholder="com.target.banking">
        <span class="grow"></span>
        <span class="muted small">log in panel →</span>
      </section>`;
}

function bindDeviceSelector() {
    $("#adb-serial")?.addEventListener("change", (e) => { NEXUS_ADB.serial = e.target.value || null; adbStateSave(); });
    $("#adb-package")?.addEventListener("input", (e) => { NEXUS_ADB.package = e.target.value.trim() || null; adbStateSave(); });
    $("#adb-package-preset")?.addEventListener("change", async (e) => {
        const pid = e.target.value;
        if (!pid) return;
        const proj = await getJSON(`/v1/projects/${encodeURIComponent(pid)}`).catch(() => null);
        if (proj && proj.package_name) {
            $("#adb-package").value = proj.package_name;
            NEXUS_ADB.package = proj.package_name;
            adbStateSave();
        }
    });
    $("#adb-refresh")?.addEventListener("click", async () => {
        await adbRefreshDevices();
        const sel = $("#adb-serial");
        if (sel) {
            const devices = NEXUS_ADB.devices || [];
            sel.innerHTML = (devices.length
                ? devices.map((d) => `<option value="${d.serial}" ${d.serial === NEXUS_ADB.serial ? "selected" : ""}>${d.serial}${d.model ? " · " + d.model : ""}</option>`).join("")
                : `<option value="">— no devices —</option>`);
        }
    });
    // Populate the package preset once.
    getJSON("/v1/projects").then((projects) => {
        const sel = $("#adb-package-preset");
        if (!sel || !projects?.length) return;
        sel.innerHTML = `<option value="">— pick / type below —</option>` + projects.map((p) =>
            `<option value="${p.id}">${p.package_name || p.id} · v${p.version_name || "?"}</option>`).join("");
    }).catch(() => {});
}

/* SCREEN — ADB Control Panel (entry route #/adb) */
function view_adb() {
    return h`
    <div class="main">
      ${sectionHeader("A", "ADB // CONTROL PANEL", "ANDROID DEBUG BRIDGE")}
      <div id="adb-bar"></div>

      <div class="row" style="align-items:flex-start;gap:14px">
        <div class="col grow" style="min-width:0">

          <section class="panel">
            <div class="panel-head">// SERVER</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <button class="btn" data-adb='{"method":"POST","url":"/v1/adb/server/start"}'>[ start-server ]</button>
              <button class="btn danger" data-adb='{"method":"POST","url":"/v1/adb/server/kill"}'>[ kill-server ]</button>
              <button class="btn" data-adb='{"method":"POST","url":"/v1/adb/server/root"}'>[ root ]</button>
              <button class="btn" data-adb='{"method":"POST","url":"/v1/adb/server/unroot"}'>[ unroot ]</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// REBOOT</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <button class="btn" data-adb-reboot="">[ reboot ]</button>
              <button class="btn" data-adb-reboot="recovery">[ recovery ]</button>
              <button class="btn" data-adb-reboot="bootloader">[ bootloader ]</button>
              <button class="btn" data-adb-reboot="fastboot">[ fastboot ]</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// APP — uses selected package</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <button class="btn primary" data-adb-app="start">[ START ]</button>
              <button class="btn" data-adb-app="stop">[ FORCE STOP ]</button>
              <button class="btn" data-adb-app="clear">[ CLEAR DATA ]</button>
              <button class="btn danger" data-adb-app="uninstall">[ UNINSTALL ]</button>
              <button class="btn" data-adb-app="uninstall-keep">[ UNINSTALL · KEEP DATA ]</button>
              <label class="row" style="gap:6px;cursor:pointer"><input type="file" id="apk-install" accept=".apk" style="display:none"><span class="btn primary">[ + INSTALL APK ]</span></label>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// ACTIVITY MANAGER</div>
            <div class="panel-body col" style="gap:8px">
              <div class="row" style="gap:8px;flex-wrap:wrap">
                <button class="btn" data-adb-home>[ HOME ]</button>
                <button class="btn" data-adb-key="3">[ KEY: HOME ]</button>
                <button class="btn" data-adb-key="4">[ KEY: BACK ]</button>
                <button class="btn" data-adb-key="82">[ KEY: MENU ]</button>
                <button class="btn" data-adb-key="84">[ KEY: SEARCH ]</button>
                <button class="btn" data-adb-key="26">[ KEY: POWER ]</button>
              </div>
              <div class="row" style="gap:8px">
                <input id="adb-url" class="input grow" placeholder="https://example.com (open as VIEW intent)" style="min-width:0">
                <button class="btn primary" id="adb-url-go">[ OPEN URL ]</button>
              </div>
              <div class="row" style="gap:8px">
                <input id="adb-tel" class="input" placeholder="+1234567890" style="width:200px">
                <button class="btn" id="adb-tel-call">[ CALL ]</button>
                <button class="btn" id="adb-tel-sms">[ SEND SMS ]</button>
                <input id="adb-sms-body" class="input grow" placeholder="message body…" style="min-width:0">
              </div>
              <div class="row" style="gap:8px">
                <input id="adb-action" class="input" placeholder="action (e.g. android.intent.action.VIEW)" style="width:300px">
                <input id="adb-data" class="input" placeholder="data" style="width:200px">
                <select id="adb-mode" class="input" style="width:130px"><option>start</option><option>broadcast</option><option>startservice</option></select>
                <button class="btn primary" id="adb-intent-go">[ FIRE INTENT ]</button>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// PERMISSIONS — uses selected package</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <input id="adb-perm" class="input" placeholder="android.permission.CAMERA" style="width:280px">
              <button class="btn" data-adb-perm="grant">[ GRANT ]</button>
              <button class="btn" data-adb-perm="revoke">[ REVOKE ]</button>
              <button class="btn" data-adb-perm="reset">[ RESET ALL ]</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// DISPLAY (wm)</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <input id="adb-wm-size" class="input" placeholder="1080x2400" style="width:160px">
              <button class="btn" id="adb-wm-size-go">[ SET SIZE ]</button>
              <button class="btn" id="adb-wm-size-reset">[ RESET ]</button>
              <span style="width:1px;height:24px;background:var(--border)"></span>
              <input id="adb-wm-density" class="input" placeholder="320" style="width:100px">
              <button class="btn" id="adb-wm-density-go">[ SET DENSITY ]</button>
              <button class="btn" id="adb-wm-density-reset">[ RESET ]</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// INPUT</div>
            <div class="panel-body col" style="gap:8px">
              <div class="row" style="gap:8px">
                <input id="adb-text" class="input grow" placeholder='"hello world"' style="min-width:0">
                <button class="btn primary" id="adb-text-go">[ TYPE ]</button>
              </div>
              <div class="row" style="gap:8px;flex-wrap:wrap">
                <input id="adb-tap-x" class="input" placeholder="x" style="width:80px">
                <input id="adb-tap-y" class="input" placeholder="y" style="width:80px">
                <button class="btn" id="adb-tap-go">[ TAP ]</button>
                <span style="width:1px;height:24px;background:var(--border)"></span>
                <input id="adb-swipe-x1" class="input" placeholder="x1" style="width:60px">
                <input id="adb-swipe-y1" class="input" placeholder="y1" style="width:60px">
                <input id="adb-swipe-x2" class="input" placeholder="x2" style="width:60px">
                <input id="adb-swipe-y2" class="input" placeholder="y2" style="width:60px">
                <input id="adb-swipe-ms" class="input" placeholder="ms" style="width:80px" value="300">
                <button class="btn" id="adb-swipe-go">[ SWIPE ]</button>
              </div>
              <div id="adb-keycodes" class="row" style="gap:6px;flex-wrap:wrap;padding:8px;background:var(--bg);border:1px dashed var(--border);border-radius:2px"></div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// MONKEY · stress test</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <input id="adb-monkey-events" class="input" placeholder="events" style="width:120px" value="500">
              <input id="adb-monkey-seed" class="input" placeholder="seed" style="width:100px" value="42">
              <button class="btn primary" id="adb-monkey-go">[ RUN MONKEY ]</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// SCREEN RECORDING</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <input id="adb-rec-secs" class="input" placeholder="seconds (max 180)" style="width:160px" value="30">
              <button class="btn primary" id="adb-rec-start">[ START RECORDING ]</button>
              <button class="btn" id="adb-rec-pull">[ PULL LATEST ]</button>
              <span class="muted small" id="adb-rec-status">—</span>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// SHARED PREFERENCES (debug-build receivers)</div>
            <div class="panel-body col" style="gap:8px">
              <div class="row" style="gap:8px;flex-wrap:wrap">
                <select id="adb-sp-op" class="input" style="width:110px"><option>PUT</option><option>REMOVE</option><option>CLEAR</option></select>
                <input id="adb-sp-name" class="input" placeholder="prefs name (optional)" style="width:160px">
                <input id="adb-sp-key" class="input" placeholder="key" style="width:160px">
                <select id="adb-sp-type" class="input" style="width:110px"><option>string</option><option>boolean</option><option>int</option><option>long</option><option>float</option></select>
                <input id="adb-sp-value" class="input grow" placeholder='value' style="min-width:0">
                <button class="btn primary" id="adb-sp-go">[ BROADCAST ]</button>
              </div>
              <div class="muted small">Receivers must be registered as <code>&lt;package&gt;.sp.{PUT,REMOVE,CLEAR}</code> in the debug build.</div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// PACKAGES — list + filter</div>
            <div class="panel-body col" style="gap:8px">
              <div class="row" style="gap:8px">
                <select id="adb-pkg-scope" class="input" style="width:160px">
                  <option value="all">all</option>
                  <option value="3rd" selected>3rd party</option>
                  <option value="system">system</option>
                  <option value="uninstalled">uninstalled</option>
                  <option value="with-paths">with paths</option>
                </select>
                <input id="adb-pkg-filter" class="input grow" placeholder="grep filter (optional)">
                <button class="btn primary" id="adb-pkg-list">[ LIST ]</button>
              </div>
              <div id="adb-pkg-results" class="panel-body tight" style="background:var(--bg);max-height:280px;overflow:auto"></div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">// DUMPSYS</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              ${["battery", "wifi", "window", "package", "activity", "cpuinfo", "meminfo"].map((t) => `<button class="btn" data-adb-dumpsys="${t}">[ ${t} ]</button>`).join("")}
            </div>
            <pre class="code" id="adb-dumpsys-out" style="max-height:240px;overflow:auto;display:none;margin:0"></pre>
          </section>

          <section class="panel">
            <div class="panel-head">// LOGCAT</div>
            <div class="panel-body row" style="gap:8px;flex-wrap:wrap">
              <select id="adb-lc-level" class="input" style="width:80px"><option>V</option><option selected>I</option><option>W</option><option>E</option><option>F</option></select>
              <input id="adb-lc-filter" class="input grow" placeholder="grep" style="min-width:200px">
              <input id="adb-lc-lines" class="input" style="width:80px" value="200">
              <button class="btn primary" id="adb-lc-fetch">[ FETCH ]</button>
              <button class="btn danger" id="adb-lc-clear">[ logcat -c ]</button>
            </div>
            <pre class="code" id="adb-lc-out" style="max-height:300px;overflow:auto;display:none;margin:0"></pre>
          </section>

        </div>

        <!-- COMMAND LOG (sticky right pane) -->
        <section class="panel" style="width:460px;flex:none;position:sticky;top:12px">
          <div class="panel-head"><span>// COMMAND LOG · live</span><span class="spacer"></span><button class="btn" id="adb-log-clear">[ CLEAR ]</button><label class="row" style="gap:4px;margin-left:8px"><input type="checkbox" id="adb-log-auto" checked style="accent-color:var(--acid)"><span class="muted small">auto-poll · 2s</span></label></div>
          <div class="panel-body" id="adb-log-body" style="max-height:80vh;overflow:auto;font-size:11px;line-height:1.45"></div>
        </section>
      </div>
    </div>`;
}

async function mount_adb() {
    await adbRefreshDevices();
    await adbRefreshPackages();
    $("#adb-bar").innerHTML = deviceSelectorBar();
    bindDeviceSelector();
    renderKeycodeButtons();

    // ─── helpers ─────────────────────────────────────────────────────────
    const requireSerial = () => {
        if (!NEXUS_ADB.serial) { alert("select a device first"); return null; }
        return NEXUS_ADB.serial;
    };
    const requirePackage = () => {
        const pkg = ($("#adb-package")?.value || NEXUS_ADB.package || "").trim();
        if (!pkg) { alert("set a package first (top bar or project import)"); return null; }
        return pkg;
    };
    const post = async (url, formData = {}) => {
        const fd = new FormData();
        Object.entries(formData).forEach(([k, v]) => fd.append(k, v));
        const r = await fetch(url, { method: "POST", body: fd });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || r.statusText);
        return j;
    };
    const flash = (btn, ok = true, msg) => {
        const orig = btn.textContent;
        btn.textContent = msg || (ok ? "[ ✓ ]" : "[ ✕ ]");
        btn.style.color = ok ? "var(--acid)" : "var(--sev-crit)";
        setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 1300);
    };

    // ─── server / generic POST ──────────────────────────────────────────
    $$('[data-adb]').forEach((btn) => btn.addEventListener("click", async () => {
        try {
            const cfg = JSON.parse(btn.dataset.adb);
            await post(cfg.url, cfg.form || {});
            flash(btn, true);
        } catch (e) { flash(btn, false); console.error(e); }
    }));

    // ─── reboot ─────────────────────────────────────────────────────────
    $$('[data-adb-reboot]').forEach((btn) => btn.addEventListener("click", async () => {
        const s = requireSerial(); if (!s) return;
        const mode = btn.dataset.adbReboot || "";
        if (!confirm(`reboot ${s}${mode ? " into " + mode : ""}?`)) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/reboot`, { mode }); flash(btn); } catch (e) { flash(btn, false); }
    }));

    // ─── app actions ────────────────────────────────────────────────────
    $$('[data-adb-app]').forEach((btn) => btn.addEventListener("click", async () => {
        const s = requireSerial(); if (!s) return;
        const pkg = requirePackage(); if (!pkg) return;
        const op = btn.dataset.adbApp;
        try {
            if (op === "start") await post(`/v1/devices/${encodeURIComponent(s)}/start`, { package: pkg });
            else if (op === "stop") await post(`/v1/devices/${encodeURIComponent(s)}/stop`, { package: pkg });
            else if (op === "clear") await post(`/v1/devices/${encodeURIComponent(s)}/clear`, { package: pkg });
            else if (op === "uninstall") await post(`/v1/devices/${encodeURIComponent(s)}/uninstall`, { package: pkg });
            else if (op === "uninstall-keep") await post(`/v1/devices/${encodeURIComponent(s)}/uninstall`, { package: pkg, keep_data: "yes" });
            flash(btn, true);
        } catch (e) { flash(btn, false); console.error(e); }
    }));

    $("#apk-install").addEventListener("change", async (e) => {
        const s = requireSerial(); if (!s) return;
        const f = e.target.files?.[0]; if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        const btn = e.target.parentElement.querySelector("span.btn");
        btn.textContent = `[ INSTALLING ${f.name}… ]`;
        const r = await fetch(`/v1/devices/${encodeURIComponent(s)}/install`, { method: "POST", body: fd });
        const j = await r.json().catch(() => ({}));
        btn.textContent = r.ok && j.success ? "[ ✓ INSTALLED ]" : "[ ✕ FAILED ]";
        btn.style.color = r.ok && j.success ? "var(--acid)" : "var(--sev-crit)";
        setTimeout(() => { btn.textContent = "[ + INSTALL APK ]"; btn.style.color = ""; }, 1800);
    });

    // ─── activity manager ──────────────────────────────────────────────
    $('[data-adb-home]').addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/home`); flash(e.target); } catch { flash(e.target, false); }
    });
    $$('[data-adb-key]').forEach((btn) => btn.addEventListener("click", async () => {
        const s = requireSerial(); if (!s) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/key`, { keycode: btn.dataset.adbKey }); flash(btn); } catch { flash(btn, false); }
    }));
    $("#adb-url-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const url = $("#adb-url").value.trim();
        if (!url) { alert("enter a URL"); return; }
        try { await post(`/v1/devices/${encodeURIComponent(s)}/url`, { url }); flash(e.target); } catch { flash(e.target, false); }
    });
    $("#adb-tel-call").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const tel = $("#adb-tel").value.trim();
        if (!tel) return;
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/intent`, {
                action: "android.intent.action.CALL", data: `tel:${tel}`, mode: "start",
            });
            flash(e.target);
        } catch { flash(e.target, false); }
    });
    $("#adb-tel-sms").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const tel = $("#adb-tel").value.trim();
        const body = $("#adb-sms-body").value.trim();
        if (!tel) return;
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/intent`, {
                action: "android.intent.action.SENDTO", data: `sms:${tel}`,
                extras: body ? `sms_body=${body}` : "", mode: "start",
            });
            flash(e.target);
        } catch { flash(e.target, false); }
    });
    $("#adb-intent-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const action = $("#adb-action").value.trim();
        if (!action) return;
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/intent`, {
                action, data: $("#adb-data").value.trim(), mode: $("#adb-mode").value,
            });
            flash(e.target);
        } catch { flash(e.target, false); }
    });

    // ─── permissions ────────────────────────────────────────────────────
    $$('[data-adb-perm]').forEach((btn) => btn.addEventListener("click", async () => {
        const s = requireSerial(); if (!s) return;
        const pkg = requirePackage(); if (!pkg) return;
        const op = btn.dataset.adbPerm;
        const perm = $("#adb-perm").value.trim();
        if (op !== "reset" && !perm) { alert("enter a permission"); return; }
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/permissions/${op}`, { package: pkg, permission: perm });
            flash(btn);
        } catch { flash(btn, false); }
    }));

    // ─── display ────────────────────────────────────────────────────────
    const wm = async (btn, op, value = "") => {
        const s = requireSerial(); if (!s) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/wm`, { op, value }); flash(btn); } catch { flash(btn, false); }
    };
    $("#adb-wm-size-go").addEventListener("click", (e) => wm(e.target, "size", $("#adb-wm-size").value.trim()));
    $("#adb-wm-size-reset").addEventListener("click", (e) => wm(e.target, "size-reset"));
    $("#adb-wm-density-go").addEventListener("click", (e) => wm(e.target, "density", $("#adb-wm-density").value.trim()));
    $("#adb-wm-density-reset").addEventListener("click", (e) => wm(e.target, "density-reset"));

    // ─── input ──────────────────────────────────────────────────────────
    $("#adb-text-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const t = $("#adb-text").value;
        if (!t) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/text`, { text: t }); flash(e.target); } catch { flash(e.target, false); }
    });
    $("#adb-tap-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/tap`, { x: $("#adb-tap-x").value, y: $("#adb-tap-y").value }); flash(e.target); } catch { flash(e.target, false); }
    });
    $("#adb-swipe-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/swipe`, {
                x1: $("#adb-swipe-x1").value, y1: $("#adb-swipe-y1").value,
                x2: $("#adb-swipe-x2").value, y2: $("#adb-swipe-y2").value,
                ms: $("#adb-swipe-ms").value || 300,
            });
            flash(e.target);
        } catch { flash(e.target, false); }
    });

    // ─── monkey ────────────────────────────────────────────────────────
    $("#adb-monkey-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const pkg = requirePackage(); if (!pkg) return;
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/monkey`, {
                package: pkg, events: $("#adb-monkey-events").value || 500, seed: $("#adb-monkey-seed").value || 42,
            });
            flash(e.target);
        } catch { flash(e.target, false); }
    });

    // ─── recording ─────────────────────────────────────────────────────
    $("#adb-rec-start").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const secs = $("#adb-rec-secs").value || 30;
        try {
            const j = await post(`/v1/devices/${encodeURIComponent(s)}/screenrecord/start`, { seconds: secs });
            $("#adb-rec-status").textContent = `recording → ${j.remote} (pid ${j.pid}, max ${j.seconds}s)`;
            $("#adb-rec-status").style.color = "var(--acid)";
            flash(e.target);
        } catch (err) { flash(e.target, false); $("#adb-rec-status").textContent = err.message; }
    });
    $("#adb-rec-pull").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        try {
            const j = await post(`/v1/devices/${encodeURIComponent(s)}/screenrecord/pull`);
            $("#adb-rec-status").textContent = `pulled → ${j.local} (${fmtBytes(j.size_bytes || 0)})`;
            $("#adb-rec-status").style.color = "var(--acid)";
            flash(e.target);
        } catch (err) { flash(e.target, false); $("#adb-rec-status").textContent = err.message; }
    });

    // ─── shared prefs ───────────────────────────────────────────────────
    $("#adb-sp-go").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const pkg = requirePackage(); if (!pkg) return;
        try {
            await post(`/v1/devices/${encodeURIComponent(s)}/sharedprefs`, {
                package: pkg, op: $("#adb-sp-op").value,
                name: $("#adb-sp-name").value, key: $("#adb-sp-key").value,
                value: $("#adb-sp-value").value, type: $("#adb-sp-type").value,
            });
            flash(e.target);
        } catch { flash(e.target, false); }
    });

    // ─── packages ──────────────────────────────────────────────────────
    $("#adb-pkg-list").addEventListener("click", async () => {
        const s = requireSerial(); if (!s) return;
        const scope = $("#adb-pkg-scope").value;
        const filter = $("#adb-pkg-filter").value.trim();
        const out = $("#adb-pkg-results");
        out.innerHTML = "loading…";
        try {
            const url = `/v1/devices/${encodeURIComponent(s)}/packages?scope=${encodeURIComponent(scope)}` + (filter ? `&filter=${encodeURIComponent(filter)}` : "");
            const rows = await getJSON(url);
            if (!rows.length) { out.innerHTML = `<div class="muted small" style="padding:8px">no matches</div>`; return; }
            out.innerHTML = rows.slice(0, 200).map((r) => `
              <div class="table-row" style="grid-template-columns: 1fr 90px 90px 90px;padding:4px 8px">
                <span class="t-mono small">${r.package}</span>
                <button class="btn" data-pick="${r.package}" style="padding:2px 8px;font-size:10px">[ PICK ]</button>
                <button class="btn" data-clear-pkg="${r.package}" style="padding:2px 8px;font-size:10px">[ CLEAR ]</button>
                <button class="btn danger" data-uninstall-pkg="${r.package}" style="padding:2px 8px;font-size:10px">[ × ]</button>
              </div>`).join("");
            out.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener("click", () => {
                $("#adb-package").value = b.dataset.pick;
                NEXUS_ADB.package = b.dataset.pick;
                adbStateSave();
                b.textContent = "[ PICKED ]"; b.style.color = "var(--acid)";
            }));
            out.querySelectorAll('[data-clear-pkg]').forEach((b) => b.addEventListener("click", async () => {
                if (!confirm(`pm clear ${b.dataset.clearPkg}?`)) return;
                try { await post(`/v1/devices/${encodeURIComponent(s)}/clear`, { package: b.dataset.clearPkg }); flash(b); } catch { flash(b, false); }
            }));
            out.querySelectorAll('[data-uninstall-pkg]').forEach((b) => b.addEventListener("click", async () => {
                if (!confirm(`uninstall ${b.dataset.uninstallPkg}?`)) return;
                try { await post(`/v1/devices/${encodeURIComponent(s)}/uninstall`, { package: b.dataset.uninstallPkg }); flash(b); } catch { flash(b, false); }
            }));
        } catch (err) { out.innerHTML = `<div class="muted small" style="padding:8px;color:var(--sev-crit)">${escapeHtml(err.message)}</div>`; }
    });

    // ─── dumpsys ───────────────────────────────────────────────────────
    $$('[data-adb-dumpsys]').forEach((btn) => btn.addEventListener("click", async () => {
        const s = requireSerial(); if (!s) return;
        const topic = btn.dataset.adbDumpsys;
        const out = $("#adb-dumpsys-out");
        out.style.display = "";
        out.textContent = "loading…";
        try {
            const j = await getJSON(`/v1/devices/${encodeURIComponent(s)}/dumpsys/${topic}`);
            out.textContent = j.output;
            flash(btn);
        } catch (err) { out.textContent = err.message; flash(btn, false); }
    }));

    // ─── logcat ────────────────────────────────────────────────────────
    $("#adb-lc-fetch").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        const out = $("#adb-lc-out");
        out.style.display = "";
        out.textContent = "loading…";
        try {
            const url = `/v1/devices/${encodeURIComponent(s)}/logcat?lines=${$("#adb-lc-lines").value || 200}&level=${$("#adb-lc-level").value}&filter=${encodeURIComponent($("#adb-lc-filter").value)}`;
            const j = await getJSON(url);
            out.textContent = (j.lines || []).join("\n") || "(no entries)";
            flash(e.target);
        } catch (err) { out.textContent = err.message; flash(e.target, false); }
    });
    $("#adb-lc-clear").addEventListener("click", async (e) => {
        const s = requireSerial(); if (!s) return;
        if (!confirm("clear device logcat buffer?")) return;
        try { await post(`/v1/devices/${encodeURIComponent(s)}/logcat/clear`); flash(e.target); } catch { flash(e.target, false); }
    });

    // ─── command log polling ──────────────────────────────────────────
    let logTimer = null;
    const renderLog = (rows) => {
        const body = $("#adb-log-body");
        if (!rows.length) { body.innerHTML = `<div class="muted small" style="padding:12px">no commands yet — every adb call we make shows up here</div>`; return; }
        body.innerHTML = rows.slice().reverse().map((e) => {
            const ok = e.exit === 0 || e.exit === "running";
            const time = (e.ts || "").split("T")[1]?.slice(0, 8) || "";
            return `
              <div style="padding:6px 10px;border-bottom:1px dashed var(--border)">
                <div class="row" style="gap:8px">
                  <span class="t-mono small" style="color:${ok ? "var(--acid)" : "var(--sev-crit)"};font-weight:700">${ok ? "✓" : "✕"}</span>
                  <span class="t-mono small" style="color:var(--magenta)">${time}</span>
                  <span class="t-mono small" style="color:var(--cyan)">${escapeHtml(e.serial || "—")}</span>
                  <span class="grow"></span>
                  <span class="muted small">${escapeHtml(e.note || "")}</span>
                </div>
                <div class="t-mono" style="margin-top:2px;font-size:11px">${escapeHtml(e.command)}</div>
                ${e.output ? `<pre class="t-muted" style="margin:4px 0 0;font-size:10px;white-space:pre-wrap;max-height:90px;overflow:auto">${escapeHtml((e.output || "").slice(0, 1200))}</pre>` : ""}
              </div>`;
        }).join("");
    };
    const pollLog = async () => {
        try { const j = await getJSON("/v1/adb/log?limit=80"); renderLog(j.log || []); } catch (e) {}
    };
    pollLog();
    const setAuto = (on) => {
        if (logTimer) { clearInterval(logTimer); logTimer = null; }
        if (on) logTimer = setInterval(pollLog, 2000);
    };
    setAuto(true);
    $("#adb-log-auto").addEventListener("change", (e) => setAuto(e.target.checked));
    $("#adb-log-clear").addEventListener("click", async () => {
        await fetch("/v1/adb/log/clear", { method: "POST" });
        pollLog();
    });
}

function renderKeycodeButtons() {
    const el = $("#adb-keycodes");
    if (!el) return;
    const codes = [
        [3, "HOME"], [4, "BACK"], [82, "MENU"], [84, "SEARCH"], [66, "ENTER"], [67, "DEL"],
        [26, "POWER"], [24, "VOL+"], [25, "VOL-"], [27, "CAMERA"], [220, "BRIGHT-"], [221, "BRIGHT+"],
        [85, "PLAY/PAUSE"], [87, "NEXT"], [88, "PREV"], [277, "CUT"], [278, "COPY"], [279, "PASTE"],
    ];
    el.innerHTML = codes.map(([code, name]) => `<button class="btn small" data-adb-key="${code}" style="padding:2px 8px;font-size:10px">[ ${code} · ${name} ]</button>`).join("");
}

/* SCREEN 06b — Interactive Shell */
function view_device_shell() {
    return h`
    <div class="main">
      ${sectionHeader("S", "06 // INTAKE", "INTERACTIVE SHELL")}
      ${deviceTabs("shell")}
      <section class="panel">
        <div class="panel-head"><span>// adb shell — read-only blocklist enforced server-side</span><span class="spacer"></span><button class="btn" id="sh-clear">[ CLEAR ]</button></div>
        <div class="panel-body console" id="sh-out" style="min-height:340px;font-size:12px"></div>
        <div class="panel-body" style="border-top:1px solid var(--border)">
          <div class="input grow">
            <span class="prompt">$</span>
            <input id="sh-in" placeholder="getprop ro.build.fingerprint   ·   ip a   ·   pm list packages -3" autocomplete="off">
            <span class="cursor">_</span>
          </div>
        </div>
      </section>
      <div class="muted small">examples: <code>getprop</code> · <code>ip a</code> · <code>pm list packages -3</code> · <code>cat /proc/cpuinfo</code> · <code>dumpsys SurfaceFlinger | head</code></div>
    </div>`;
}

function mount_device_shell() {
    fillDeviceStatusStrip();
    const out = $("#sh-out");
    const inp = $("#sh-in");
    const writeLine = (text, klass = "") => {
        const div = document.createElement("div");
        if (klass) div.innerHTML = `<span class="${klass}">${escapeHtml(text)}</span>`;
        else div.textContent = text;
        out.appendChild(div);
        out.scrollTop = out.scrollHeight;
    };
    writeLine("[NEXUS] interactive adb shell · refused: rm/dd/pm install/reboot/su/...", "nexus");
    let history = []; let cursor = -1;
    inp.addEventListener("keydown", async (e) => {
        if (e.key === "ArrowUp") {
            if (history.length && cursor < history.length - 1) { cursor++; inp.value = history[history.length - 1 - cursor]; }
            e.preventDefault();
        } else if (e.key === "ArrowDown") {
            if (cursor > 0) { cursor--; inp.value = history[history.length - 1 - cursor]; }
            else { cursor = -1; inp.value = ""; }
            e.preventDefault();
        } else if (e.key === "Enter") {
            const cmd = inp.value.trim();
            if (!cmd) return;
            history.push(cmd); cursor = -1; inp.value = "";
            writeLine(`$ ${cmd}`, "nexus");
            const fd = new FormData(); fd.append("cmd", cmd);
            try {
                const r = await fetch("/v1/device/shell", { method: "POST", body: fd });
                const j = await r.json();
                if (!r.ok) writeLine(`error: ${j.detail || r.statusText}`, "crit");
                else (j.output || "(no output)").split("\n").forEach((line) => writeLine(line));
            } catch (err) { writeLine(`fetch failed: ${err.message}`, "crit"); }
        }
    });
    $("#sh-clear").addEventListener("click", () => { out.innerHTML = ""; });
    inp.focus();
}

/* SCREEN 06c — File Manager */
function view_device_files() {
    return h`
    <div class="main">
      ${sectionHeader("F", "06 // INTAKE", "FILE MANAGER")}
      ${deviceTabs("files")}
      <section class="row">
        <button class="btn" id="fm-up">[ ↑ UP ]</button>
        <div class="input grow"><span class="prompt">~</span><input id="fm-path" value="/sdcard"><span class="cursor">_</span></div>
        <button class="btn primary" id="fm-go">[ LIST ]</button>
        <label class="btn" style="cursor:pointer">[ + UPLOAD ]<input type="file" id="fm-upload" style="display:none"></label>
      </section>
      <section class="panel">
        <div class="panel-head"><span class="t-mono" id="fm-current">/sdcard</span><span class="spacer"></span><span class="muted" id="fm-count">—</span></div>
        <div class="panel-body tight" id="fm-list">loading…</div>
      </section>
      <section class="panel" id="fm-msg" style="display:none">
        <div class="panel-head">// MESSAGE</div>
        <div class="panel-body" id="fm-msg-body"></div>
      </section>
    </div>`;
}

function mount_device_files() {
    fillDeviceStatusStrip();
    const list = $("#fm-list");
    const pathInp = $("#fm-path");
    const current = $("#fm-current");
    const count = $("#fm-count");
    const msg = $("#fm-msg");
    const msgBody = $("#fm-msg-body");
    const showMsg = (text, color = "var(--cyan)") => {
        msg.style.display = "";
        msgBody.innerHTML = `<span class="t-mono" style="color:${color}">${escapeHtml(text)}</span>`;
    };

    const load = async (path) => {
        pathInp.value = path;
        current.textContent = path;
        list.innerHTML = "loading…";
        try {
            const data = await getJSON(`/v1/device/files?path=${encodeURIComponent(path)}`);
            const entries = data.entries || [];
            count.textContent = `${entries.length} entries`;
            if (!entries.length) {
                list.innerHTML = `<div class="empty-state">empty / unreadable</div>`;
                return;
            }
            list.innerHTML = `
              <div class="table-hdr" style="grid-template-columns: 50px 1fr 100px 100px 160px 120px">
                <span></span><span>NAME</span><span>SIZE</span><span>OWNER</span><span>MODIFIED</span><span></span>
              </div>` + entries.map((e) => {
                const isDir = e.kind === "dir";
                const icon = isDir ? "📁" : e.kind === "link" ? "🔗" : "📄";
                return `
                <div class="table-row" style="grid-template-columns: 50px 1fr 100px 100px 160px 120px">
                  <span>${icon}</span>
                  <span class="t-mono" data-name="${e.name}" style="cursor:pointer;color:${isDir ? "var(--cyan)" : "var(--muted-text, #ccc)"}">${e.name}</span>
                  <span class="t-muted">${e.size || "—"}</span>
                  <span class="t-muted">${e.owner || "—"}</span>
                  <span class="t-muted">${e.ts || "—"}</span>
                  <span style="text-align:right;display:flex;gap:4px;justify-content:flex-end">
                    ${isDir ? "" : `<button class="btn" data-get="${e.name}" style="padding:2px 8px;font-size:10px">[ GET ]</button>`}
                    ${isDir || e.name === "." || e.name === ".." ? "" : `<button class="btn danger" data-del="${e.name}" style="padding:2px 8px;font-size:10px">[ × ]</button>`}
                  </span>
                </div>`;
            }).join("");
            // Click row → enter directory
            $$('[data-name]').forEach((el) => el.addEventListener("click", () => {
                const name = el.dataset.name;
                if (name === "." || name === "..") {
                    if (name === "..") load(parentDir(path));
                    return;
                }
                const row = el.closest(".table-row");
                if (row && row.querySelector("span")?.textContent === "📁") load(joinPath(path, name));
            }));
            // Get button
            $$('[data-get]').forEach((b) => b.addEventListener("click", (ev) => {
                ev.stopPropagation();
                const name = b.dataset.get;
                const url = `/v1/device/file?path=${encodeURIComponent(joinPath(path, name))}`;
                window.open(url, "_blank");
            }));
            // Delete button
            $$('[data-del]').forEach((b) => b.addEventListener("click", async (ev) => {
                ev.stopPropagation();
                const name = b.dataset.del;
                const fullPath = joinPath(path, name);
                if (!confirm(`Delete ${fullPath}?`)) return;
                const fd = new FormData(); fd.append("path", fullPath); fd.append("confirm", "yes");
                const r = await fetch("/v1/device/file/delete", { method: "POST", body: fd });
                if (r.ok) { showMsg(`✓ deleted ${fullPath}`, "var(--acid)"); load(path); }
                else { const j = await r.json().catch(() => ({})); showMsg(`✕ ${j.detail || r.statusText}`, "var(--sev-crit)"); }
            }));
        } catch (err) {
            list.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit)">listing failed: ${escapeHtml(err.message)}</div></div>`;
        }
    };

    $("#fm-go").addEventListener("click", () => load(pathInp.value || "/sdcard"));
    $("#fm-up").addEventListener("click", () => load(parentDir(pathInp.value || "/")));
    pathInp.addEventListener("keydown", (e) => { if (e.key === "Enter") load(pathInp.value || "/sdcard"); });
    $("#fm-upload").addEventListener("change", async (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        const fd = new FormData(); fd.append("file", f); fd.append("dest", pathInp.value || "/sdcard/Download");
        showMsg(`↑ pushing ${f.name} (${fmtBytes(f.size)})…`);
        const r = await fetch("/v1/device/file/upload", { method: "POST", body: fd });
        if (r.ok) { const j = await r.json(); showMsg(`✓ pushed → ${j.remote}`, "var(--acid)"); load(pathInp.value || "/sdcard"); }
        else { const j = await r.json().catch(() => ({})); showMsg(`✕ ${j.detail || r.statusText}`, "var(--sev-crit)"); }
    });
    load("/sdcard");
}

function parentDir(path) {
    if (!path || path === "/") return "/";
    const trimmed = path.replace(/\/+$/, "");
    const idx = trimmed.lastIndexOf("/");
    return idx <= 0 ? "/" : trimmed.slice(0, idx);
}

function joinPath(base, name) {
    if (name.startsWith("/")) return name;
    return (base.endsWith("/") ? base : base + "/") + name;
}

/* SCREEN 06d — Screen Capture */
function view_device_screen() {
    return h`
    <div class="main">
      ${sectionHeader("S", "06 // INTAKE", "SCREEN CAPTURE")}
      ${deviceTabs("screen")}
      <section class="row">
        <button class="btn primary" id="cap-shot">[ CAPTURE ]</button>
        <button class="btn" id="cap-save" disabled>[ SAVE PNG ]</button>
        <span class="muted small" id="cap-meta">no capture yet</span>
      </section>
      <section class="panel">
        <div class="panel-head">// LIVE FRAME</div>
        <div class="panel-body" id="cap-body" style="display:flex;align-items:center;justify-content:center;min-height:380px;background:#050505">
          <div class="muted">click [ CAPTURE ] to grab the device screen</div>
        </div>
      </section>
    </div>`;
}

function mount_device_screen() {
    fillDeviceStatusStrip();
    let lastDataUrl = null;
    let lastPath = null;
    $("#cap-shot").addEventListener("click", async () => {
        const btn = $("#cap-shot");
        btn.textContent = "[ CAPTURING… ]";
        try {
            const r = await fetch("/v1/device/screenshot", { method: "POST" });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);
            lastDataUrl = j.data_url; lastPath = j.path;
            $("#cap-body").innerHTML = `<img src="${j.data_url}" style="max-width:100%;max-height:560px;border:1px solid var(--border-accent)" alt="device screenshot">`;
            $("#cap-meta").textContent = `${fmtBytes(j.size_bytes)} · saved to ${j.path}`;
            $("#cap-save").disabled = false;
            btn.textContent = "[ CAPTURE ]";
            btn.style.color = "var(--acid)";
        } catch (err) {
            $("#cap-body").innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit)">${escapeHtml(err.message)}</div></div>`;
            btn.textContent = "[ CAPTURE ]";
            btn.style.color = "var(--sev-crit)";
        }
    });
    $("#cap-save").addEventListener("click", () => {
        if (!lastDataUrl) return;
        const a = document.createElement("a");
        a.href = lastDataUrl;
        a.download = (lastPath || "screen.png").split("/").pop();
        a.click();
    });
}

/* SCREEN 06e — Logcat */
function view_device_logcat() {
    return h`
    <div class="main">
      ${sectionHeader("L", "06 // INTAKE", "LOGCAT")}
      ${deviceTabs("logcat")}
      <section class="row">
        <select id="lc-level" class="input" style="width:80px"><option>V</option><option selected>I</option><option>W</option><option>E</option><option>F</option></select>
        <div class="input grow"><span class="prompt">⌕</span><input id="lc-filter" placeholder="grep filter (e.g. com.target.banking, FATAL, AndroidRuntime)"><span class="cursor">_</span></div>
        <select id="lc-lines" class="input" style="width:80px"><option>100</option><option selected>200</option><option>500</option><option>1000</option></select>
        <button class="btn primary" id="lc-fetch">[ FETCH ]</button>
        <label class="row"><input type="checkbox" id="lc-auto" style="accent-color:var(--acid)"> <span class="muted small">auto-poll · 3s</span></label>
      </section>
      <section class="panel">
        <div class="panel-head"><span>// STREAM</span><span class="spacer"></span><span class="muted" id="lc-count">—</span></div>
        <div class="panel-body console" id="lc-out" style="min-height:420px;font-size:11px;line-height:1.4">no entries yet — [ FETCH ]</div>
      </section>
    </div>`;
}

function mount_device_logcat() {
    fillDeviceStatusStrip();
    let timer = null;
    const fetchOnce = async () => {
        const level = $("#lc-level").value;
        const filter = $("#lc-filter").value.trim();
        const lines = $("#lc-lines").value;
        const out = $("#lc-out");
        out.innerHTML = "loading…";
        try {
            const data = await getJSON(`/v1/device/logcat?lines=${encodeURIComponent(lines)}&level=${level}&filter=${encodeURIComponent(filter)}`);
            $("#lc-count").textContent = `${(data.lines || []).length} lines`;
            if (!data.lines.length) { out.innerHTML = `<div class="muted small">no entries</div>`; return; }
            out.innerHTML = data.lines.map((l) => {
                const cls = /\sE\s/.test(l) || /FATAL/.test(l) ? "crit"
                    : /\sW\s/.test(l) ? "intent"
                    : /\sI\s/.test(l) ? "nexus"
                    : "muted";
                return `<div><span class="${cls}">${escapeHtml(l)}</span></div>`;
            }).join("");
            out.scrollTop = out.scrollHeight;
        } catch (err) {
            out.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit)">${escapeHtml(err.message)}</div></div>`;
        }
    };
    $("#lc-fetch").addEventListener("click", fetchOnce);
    $("#lc-auto").addEventListener("change", (e) => {
        if (timer) { clearInterval(timer); timer = null; }
        if (e.target.checked) timer = setInterval(fetchOnce, 3000);
    });
    fetchOnce();
}

async function mount_recipes() {
    let recipes = [];
    try { recipes = await getJSON("/v1/recipes"); } catch (e) { /* stay on sample */ }
    if (!recipes.length) return;
    const grid = $(".recipes-grid");
    if (!grid) return;
    grid.innerHTML = recipes.map((r) => `
        <div class="recipe-card">
          <div class="cat-row"><span class="cat">${r.category}</span><span class="grow"></span><span class="origin">${r.origin}</span></div>
          <div class="name">${r.name}</div>
          <div class="desc">${r.description}</div>
          <div class="foot">
            <span class="compat">${r.compatibility}</span>
            <button class="btn" data-preview="${r.name}" style="padding:4px 10px">[ PREVIEW ]</button>
            <button class="btn primary" data-load="${r.name}" style="padding:4px 10px">[ LOAD ]</button>
          </div>
        </div>`).join("");

    // Preview button → open modal-ish overlay with the script.
    $$("[data-preview]").forEach((btn) => btn.addEventListener("click", async () => {
        const name = btn.dataset.preview;
        btn.textContent = "[ … ]";
        try {
            const j = await getJSON(`/v1/recipes/${encodeURIComponent(name)}/script`);
            showScriptOverlay(name, j.script);
            btn.textContent = "[ PREVIEW ]";
        } catch (e) {
            btn.textContent = "[ N/A ]";
            btn.style.color = "var(--sev-high)";
        }
    }));

    $$("[data-load]").forEach((btn) => btn.addEventListener("click", async () => {
        const name = btn.dataset.load;
        btn.textContent = "[ …]";
        try {
            const j = await getJSON(`/v1/recipes/${encodeURIComponent(name)}/script`);
            btn.textContent = `[ LOADED · ${j.script.length}B ]`;
            btn.style.color = "var(--acid)";
        } catch (e) {
            btn.textContent = "[ N/A ]";
            btn.style.color = "var(--sev-high)";
        }
    }));
}

function showScriptOverlay(name, script) {
    const existing = $("#script-overlay");
    if (existing) existing.remove();
    const overlay = document.createElement("div");
    overlay.id = "script-overlay";
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:9999;display:flex;align-items:center;justify-content:center;padding:40px";
    overlay.innerHTML = `
      <div style="max-width:900px;width:100%;max-height:80vh;background:var(--bg);border:1px solid var(--border-accent);display:flex;flex-direction:column">
        <div class="panel-head" style="border-bottom:1px solid var(--border-accent)">
          <span class="t-mono" style="color:var(--acid)">// ${name}.js</span>
          <span class="spacer"></span>
          <span class="muted small">${script.length} bytes</span>
          <button class="btn" id="overlay-close" style="margin-left:12px">[ CLOSE ]</button>
        </div>
        <pre class="code" style="overflow:auto;flex:1;margin:0;border:0">${escapeHtml(script)}</pre>
      </div>`;
    document.body.appendChild(overlay);
    $("#overlay-close").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
}

async function mount_settings() {
    const s = await getJSON("/v1/settings").catch(() => null);
    if (!s) return;
    const main = $(".main");
    if (!main) return;
    // Re-render the panels with real values.
    const pathsPanel = $$(".panel")[0]?.querySelector(".panel-body");
    if (pathsPanel) {
        pathsPanel.innerHTML = Object.entries(s.paths).map(([k, v]) =>
            `<div class="row"><span class="muted small" style="width:140px">${k.toUpperCase()}</span><code>${v || "(unset)"}</code></div>`
        ).join("");
    }
    const servicesPanel = $$(".panel")[1]?.querySelector(".panel-body");
    if (servicesPanel) {
        servicesPanel.innerHTML = `
          <div class="row"><span class="muted small" style="width:140px">MOBSF</span><code>${s.services.mobsf_url}</code><span class="chip ${s.services.mobsf_has_api_key ? "low" : "high"}">${s.services.mobsf_has_api_key ? "KEY SET" : "NO KEY"}</span></div>
          <div class="row"><span class="muted small" style="width:140px">BURP</span><code>${s.services.burp_url}</code><span class="chip ${s.services.burp_has_api_key ? "low" : "high"}">${s.services.burp_has_api_key ? "KEY SET" : "NO KEY"}</span></div>
          <div class="row"><span class="muted small" style="width:140px">WORKSPACE</span><code>${s.workspace}</code></div>
          <div class="row"><span class="muted small" style="width:140px">DB</span><code>${s.db_path}</code></div>`;
    }
}

async function mount_finding_detail(ctx) {
    const fid = ctx.params.fid || ctx.params.id;
    let finding = null;
    try {
        finding = await getJSON(`/v1/findings/${encodeURIComponent(fid)}`);
        const title = $(".finding .title");
        const meta = $(".finding .meta");
        const code = $$(".finding .code")[0];
        const hookCode = $$(".finding .code")[1];
        const mit = $(".finding .mitigation");
        if (title) title.textContent = finding.title;
        if (meta) meta.textContent = `${finding.location || ""} · ${finding.cwe_id || ""} ${finding.owasp_mobile || ""} · engine: ${finding.source_engine}`;
        if (code) code.textContent = finding.evidence || "(no evidence)";
        if (hookCode && finding.suggested_hook) hookCode.textContent = finding.suggested_hook;
        if (mit && finding.remediation) {
            mit.innerHTML = finding.remediation.split("\n").map((line, i) => `<div><b>${String(i + 1).padStart(2, "0")}</b> ${escapeHtml(line)}</div>`).join("");
        }
        // Confirmed badge
        const confirmedBadge = $(".finding .badge");
        if (confirmedBadge) {
            confirmedBadge.classList.toggle("connected", !!finding.confirmed);
            confirmedBadge.classList.toggle("scanning", !finding.confirmed);
            confirmedBadge.innerHTML = `<span class="dot">●</span>${finding.confirmed ? "CONFIRMED" : "STATIC ONLY"}`;
        }
    } catch (e) { /* fall back to demo content */ }

    // Wire action buttons regardless of whether we got real data.
    const buttons = $$(".finding .btn");
    buttons.forEach((btn) => {
        const t = btn.textContent.trim().toUpperCase();
        if (t.includes("RUN HOOK")) {
            btn.addEventListener("click", () => {
                const hookCode = $$(".finding .code")[1];
                if (!hookCode || !hookCode.textContent.trim()) { btn.textContent = "[ NO HOOK ]"; return; }
                btn.textContent = "[ HOOK PUSHED ]";
                btn.style.color = "var(--acid)";
            });
        } else if (t.includes("COPY REMEDIATION")) {
            btn.addEventListener("click", async () => {
                const text = $(".finding .mitigation")?.innerText || "";
                try { await navigator.clipboard.writeText(text); btn.textContent = "[ COPIED ✓ ]"; btn.style.color = "var(--acid)"; }
                catch (e) { btn.textContent = "[ CLIPBOARD BLOCKED ]"; btn.style.color = "var(--sev-high)"; }
            });
        } else if (t.includes("DISMISS")) {
            btn.addEventListener("click", async () => {
                const r = await fetch(`/v1/findings/${encodeURIComponent(fid)}/dismiss`, { method: "POST" });
                if (r.ok) { btn.textContent = "[ DISMISSED ]"; btn.style.color = "var(--muted)"; }
                else { btn.textContent = "[ FAILED ]"; }
            });
        }
    });
}

async function mount_report(ctx) {
    // Determine the target project: query string, then ctx, then first project.
    const projects = await getJSON("/v1/projects").catch(() => []);
    const queryProj = (ctx.hash || "").split("?")[1]?.split("project=")[1];
    let targetId = (queryProj && decodeURIComponent(queryProj))
        || ctx.params.id
        || projects[0]?.id;
    if (!targetId && !projects.length) {
        const main = $(".main");
        if (main) main.insertAdjacentHTML("afterbegin", `<div class="empty-state" style="margin-bottom:8px;color:var(--sev-high)">no projects yet — <a href="#/scan">ingest one</a></div>`);
    }

    // Template selector — make all rows clickable.
    const tmplRows = $$(".panel:first-of-type .panel-body .row");
    let activeTemplate = "technical";
    tmplRows.forEach((row) => {
        const txt = row.textContent.trim().toLowerCase();
        const tmpl = txt.includes("executive") ? "executive"
            : txt.includes("owasp") ? "owasp-matrix"
            : txt.includes("diff") ? "diff"
            : txt.includes("technical") ? "technical" : null;
        if (!tmpl) return;
        row.style.cursor = "pointer";
        row.addEventListener("click", () => {
            activeTemplate = tmpl;
            tmplRows.forEach((r) => {
                const t = r.textContent.trim().toLowerCase();
                const isMine = t.includes(activeTemplate.replace("-matrix", " matrix")) || (activeTemplate === "technical" && t.includes("technical"));
                r.style.background = isMine ? "var(--bg-accent-panel)" : "var(--bg-panel)";
                r.style.borderColor = isMine ? "var(--border-accent)" : "var(--border)";
            });
        });
    });

    $$(".btn.primary, .btn").forEach((btn) => {
        const t = btn.textContent.trim();
        const m = t.match(/^\[ (PDF|HTML|\.MD|JSON) \]$/);
        if (!m) return;
        btn.addEventListener("click", async () => {
            if (!targetId) { alert("no project selected — scan one first."); return; }
            const fmt = { "PDF": "pdf", "HTML": "html", ".MD": "markdown", "JSON": "json" }[m[1]];
            const fd = new FormData();
            fd.append("template", activeTemplate);
            fd.append("fmt", fmt);
            btn.textContent = "[ … ]";
            const r = await fetch(`/v1/projects/${encodeURIComponent(targetId)}/report`, { method: "POST", body: fd });
            if (!r.ok) {
                const detail = await r.text();
                btn.textContent = `[ ${m[1]} ✕ ]`; btn.style.color = "var(--sev-crit)";
                alert(`report failed (${r.status}): ${detail.slice(0, 240)}`);
                return;
            }
            const blob = await r.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url; a.download = `${targetId}.${fmt === "markdown" ? "md" : fmt}`;
            a.click();
            URL.revokeObjectURL(url);
            btn.textContent = `[ ${m[1]} ✓ ]`; btn.style.color = "var(--acid)";
            setTimeout(() => { btn.textContent = `[ ${m[1]} ]`; btn.style.color = ""; }, 1800);
        });
    });
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Project sub-screens (09 / 10 / 11 / 13 / 15 / 16 / 17 / 18 / 19 / 20)
 *  Every view is now backed by a real endpoint. Views render the chrome,
 *  mounts fetch + populate.
 * ═══════════════════════════════════════════════════════════════════════════ */

function projectChrome(id, label) {
    const parent = ({
        secrets: "static", components: "static", native: "static",
        tracer: "dynamic",
        "api-map": "network", "ssl-map": "network",
        surface: "static", dataflow: "static", "attack-tree": "static", owasp: "static",
    })[label] || "static";
    return h`
      <div class="muted small uppercase">🔱 NEXUS / ${id} / ${label}</div>
      ${projectTabs(id, parent)}`;
}

/* SCREEN 09 — Secrets + Crypto Audit */
function view_project_secrets(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "secrets")}
      ${sectionHeader("S", "09 // STATIC", "SECRETS + CRYPTO AUDIT")}
      <section class="panel">
        <div class="panel-head"><span>// CRYPTO OPERATIONS</span><span class="spacer"></span><span class="muted" id="secrets-count">loading…</span></div>
        <div class="panel-body tight" id="secrets-table">loading…</div>
      </section>
      <section class="panel">
        <div class="panel-head">// ALGORITHM HEATMAP</div>
        <div class="panel-body" id="secrets-heatmap">loading…</div>
      </section>
      <section class="panel">
        <div class="panel-head">// FINDINGS — CRYPTO + STORAGE</div>
        <div class="panel-body col" style="gap:8px" id="secrets-findings">loading…</div>
      </section>
    </div>`;
}

async function mount_project_secrets(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/secrets`).catch(() => null);
    if (!data) return;
    const ops = data.crypto_operations || [];
    const findings = data.findings || [];
    $("#secrets-count").textContent = `${ops.length} ops · ${findings.length} findings`;

    const tbl = $("#secrets-table");
    if (!ops.length) {
        tbl.innerHTML = `<div class="empty-state">no crypto operations indexed yet — JADX/Ghidra still emit []. <a href="#/project/${id}/static">back to static</a></div>`;
    } else {
        tbl.innerHTML = `
          <div class="table-hdr" style="grid-template-columns: 1fr 220px 140px 100px">
            <span>LOCATION</span><span>ALGORITHM</span><span>KEY SOURCE</span><span>IV</span>
          </div>` + ops.map((op) => {
            const weak = (data.weak_algorithms || []).includes(op.algorithm);
            return `
            <div class="table-row" style="grid-template-columns: 1fr 220px 140px 100px">
              <span class="t-mono">${op.location || "—"}</span>
              <span class="t-mono" style="color:${weak ? "var(--sev-crit)" : "var(--cyan)"};font-weight:${weak ? 700 : 400}">${op.algorithm || "?"}</span>
              <span class="t-mono">${op.key_source || "?"}</span>
              <span class="t-mono">${op.iv_source || "—"}</span>
            </div>`;
        }).join("");
    }

    const heat = $("#secrets-heatmap");
    const heatmap = data.heatmap || {};
    const algos = Object.keys(heatmap).sort();
    if (!algos.length) {
        heat.innerHTML = `<div class="empty-state">heatmap empty — needs at least one indexed crypto op</div>`;
    } else {
        const files = Array.from(new Set(algos.flatMap((a) => Object.keys(heatmap[a])))).sort();
        const head = `<div class="table-hdr" style="grid-template-columns: 200px ${files.map(() => "60px").join(" ")}">`
            + `<span>ALGO</span>${files.map((f) => `<span class="t-mono small" style="overflow:hidden;text-overflow:ellipsis">${f}</span>`).join("")}</div>`;
        const rows = algos.map((a) => {
            const weak = (data.weak_algorithms || []).includes(a);
            return `<div class="table-row" style="grid-template-columns: 200px ${files.map(() => "60px").join(" ")}">`
                + `<span class="t-mono" style="color:${weak ? "var(--sev-crit)" : "var(--cyan)"}">${a}</span>`
                + files.map((f) => {
                    const n = heatmap[a][f] || 0;
                    if (!n) return `<span class="t-muted">·</span>`;
                    const color = weak ? "var(--sev-crit)" : "var(--cyan)";
                    return `<span class="t-mono" style="color:${color};font-weight:700">${n}</span>`;
                }).join("")
                + `</div>`;
        }).join("");
        heat.innerHTML = head + rows;
    }

    const fEl = $("#secrets-findings");
    if (!findings.length) {
        fEl.innerHTML = `<div class="empty-state">no crypto/storage findings yet</div>`;
    } else {
        fEl.innerHTML = findings.map((f) => `
          <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
            <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine || "?"}]</span></div>
            <div class="title">${f.title}</div>
            <div class="meta">${f.location || "—"} · ${f.cwe_id || ""} ${f.owasp_mobile || ""}</div>
          </a>`).join("");
    }
}

/* SCREEN 10 — Components + Deep Links */
function view_project_components(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "components")}
      ${sectionHeader("C", "10 // STATIC", "COMPONENTS + DEEP LINKS")}
      <section class="row" id="components-tabs"></section>
      <section class="panel">
        <div class="panel-head"><span>// EXPORTED COMPONENTS</span><span class="spacer"></span><span class="muted" id="components-count">loading…</span></div>
        <div class="panel-body tight" id="components-table">loading…</div>
      </section>
      <section class="panel">
        <div class="panel-head">// DEEP LINKS</div>
        <div class="panel-body col" style="gap:6px" id="components-deeplinks">loading…</div>
      </section>
      <section class="panel">
        <div class="panel-head">// PERMISSIONS DECLARED</div>
        <div class="panel-body" id="components-permissions">loading…</div>
      </section>
    </div>`;
}

async function mount_project_components(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/components`).catch(() => null);
    if (!data) return;

    const byType = data.by_type || {};
    $("#components-tabs").innerHTML = ["activity", "service", "receiver", "provider"].map((t) =>
        `<span class="chip ${t === "provider" ? "high" : "info"}">${t.toUpperCase()} · ${byType[t] || 0}</span>`
    ).join(" ");

    $("#components-count").textContent = `${(data.components || []).length} · ${data.unprotected_count || 0} unprotected`;

    const tbl = $("#components-table");
    if (!data.components.length) {
        tbl.innerHTML = `<div class="empty-state">no exported components indexed — apktool engine still stub</div>`;
    } else {
        tbl.innerHTML = `
          <div class="table-hdr" style="grid-template-columns: 90px 1fr 140px 120px 90px">
            <span>TYPE</span><span>NAME</span><span>PERMISSION</span><span>FILTERS</span><span></span>
          </div>` + data.components.map((c) => `
            <div class="table-row" style="grid-template-columns: 90px 1fr 140px 120px 90px">
              <span class="t-mono small uppercase">${c.component_type}</span>
              <span class="t-mono" style="color:${c.unprotected ? "var(--sev-high)" : "var(--cyan)"}">${c.name}</span>
              <span class="t-muted">${c.permission || "—"}</span>
              <span class="t-muted">${(c.intent_filters || []).length} filter(s)</span>
              <span style="text-align:right">${c.unprotected ? '<span class="chip high">EXPOSED</span>' : '<span class="chip low">PROTECTED</span>'}</span>
            </div>`).join("");
    }

    const dl = $("#components-deeplinks");
    if (!data.deeplinks || !data.deeplinks.length) {
        dl.innerHTML = `<div class="empty-state">no deep links discovered</div>`;
    } else {
        dl.innerHTML = data.deeplinks.map((l) => `<div class="row"><code class="t-mono" style="color:var(--magenta)">${l}</code><span class="grow"></span><button class="btn" data-test-deeplink="${l}" style="padding:4px 10px">[ TEST ]</button></div>`).join("");
        $$("[data-test-deeplink]").forEach((b) => b.addEventListener("click", () => {
            b.textContent = `[ am start -a VIEW -d ${b.dataset.testDeeplink} ]`;
            b.style.color = "var(--acid)";
        }));
    }

    const perms = $("#components-permissions");
    if (!data.permissions || !data.permissions.length) {
        perms.innerHTML = `<div class="empty-state">no permissions declared</div>`;
    } else {
        perms.innerHTML = data.permissions.map((p) => `<span class="chip info" style="margin:2px">${p}</span>`).join("");
    }
}

/* SCREEN 11 — Native (Ghidra) */
function view_project_native(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "native")}
      ${sectionHeader("N", "11 // STATIC", "NATIVE · GHIDRA")}
      <section class="panel">
        <div class="panel-head"><span>// SHARED OBJECTS</span><span class="spacer"></span><span class="muted" id="native-summary">loading…</span></div>
        <div class="panel-body tight" id="native-table">loading…</div>
      </section>
      <section class="panel">
        <div class="panel-head">// NATIVE FINDINGS</div>
        <div class="panel-body col" style="gap:8px" id="native-findings">loading…</div>
      </section>
    </div>`;
}

async function mount_project_native(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/native`).catch(() => null);
    if (!data) return;
    const libs = data.native_libraries || [];
    $("#native-summary").textContent = `${libs.length} · abis: ${(data.abis || []).join(", ") || "—"}`;
    const tbl = $("#native-table");
    if (!libs.length) {
        tbl.innerHTML = `<div class="empty-state">no native libraries — Ghidra engine still stub. drop an APK with .so files to populate.</div>`;
    } else {
        tbl.innerHTML = `
          <div class="table-hdr" style="grid-template-columns: 1fr 120px 100px 1fr 1fr">
            <span>PATH</span><span>ARCH</span><span>SIZE</span><span>JNI</span><span>CRYPTO</span>
          </div>` + libs.map((l) => `
            <div class="table-row" style="grid-template-columns: 1fr 120px 100px 1fr 1fr">
              <span class="t-mono">${l.path}</span>
              <span class="t-mono">${l.arch}</span>
              <span class="t-muted">${fmtBytes(l.size_bytes || 0)}</span>
              <span class="t-mono">${(l.jni_functions || []).slice(0, 3).join(", ") || "—"}</span>
              <span class="t-mono" style="color:${(l.crypto_primitives_detected || []).length ? "var(--sev-high)" : ""}">${(l.crypto_primitives_detected || []).join(", ") || "—"}</span>
            </div>`).join("");
    }
    const fEl = $("#native-findings");
    if (!data.findings.length) {
        fEl.innerHTML = `<div class="empty-state">no native findings</div>`;
    } else {
        fEl.innerHTML = data.findings.map((f) => `
          <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
            <div class="head">${chip(f.severity)}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
            <div class="title">${f.title}</div>
            <div class="meta">${f.location || "—"} · ${f.cwe_id || ""}</div>
          </a>`).join("");
    }
}

/* SCREEN 13 — Live Method Tracer */
function view_project_tracer(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "tracer")}
      ${sectionHeader("T", "13 // DYNAMIC", "LIVE METHOD TRACER")}
      <section class="row">
        <div class="input grow"><span class="prompt">&gt;</span><input id="tracer-filter" placeholder="com.target.* — class or method substring"><span class="cursor">_</span></div>
        <button class="btn primary" id="tracer-poll">[ POLL ]</button>
      </section>
      <section class="panel">
        <div class="panel-head"><span>// TRACE EVENTS</span><span class="spacer"></span><span class="muted small">poll once · ws stream pending</span></div>
        <div class="panel-body console" id="tracer-stream">awaiting events…</div>
      </section>
    </div>`;
}

async function mount_project_tracer(ctx) {
    const id = ctx.params.id;
    const stream = $("#tracer-stream");
    const poll = async () => {
        const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/dynamic/events`).catch(() => null);
        if (!data) { stream.textContent = "(no data)"; return; }
        const filter = ($("#tracer-filter")?.value || "").trim().toLowerCase();
        const lines = (data.log || [])
            .filter((l) => !filter || (l.line || "").toLowerCase().includes(filter))
            .map((l) => `<div><span class="${classifyTraceClass(l.channel)}">${escapeHtml(l.line)}</span></div>`)
            .join("") || `<div class="muted small">no matching events</div>`;
        stream.innerHTML = lines;
    };
    $("#tracer-poll").addEventListener("click", poll);
    poll();
}

function classifyTraceClass(ch) {
    return {nexus: "nexus", crypto: "crypto", intent: "intent", meta: "meta", crit: "crit"}[ch] || "muted";
}

function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

/* SCREEN 15 — API Endpoint Map */
function view_project_api_map(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "api-map")}
      ${sectionHeader("A", "15 // NETWORK", "API ENDPOINT MAP")}
      <section class="panel">
        <div class="panel-head"><span>// HOSTS · PATHS · METHODS</span><span class="spacer"></span><span class="muted" id="apimap-count">loading…</span></div>
        <div class="panel-body" id="apimap-tree">loading…</div>
      </section>
      <section class="panel">
        <div class="panel-head">// FLAGGED — NETWORK FINDINGS</div>
        <div class="panel-body col" style="gap:8px" id="apimap-flagged">loading…</div>
      </section>
    </div>`;
}

async function mount_project_api_map(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/api-map`).catch(() => null);
    if (!data) return;
    const tree = data.tree || {};
    const hosts = Object.keys(tree).sort();
    $("#apimap-count").textContent = `${hosts.length} hosts · ${(data.endpoints || []).length} endpoints`;

    const treeEl = $("#apimap-tree");
    if (!hosts.length) {
        treeEl.innerHTML = `<div class="empty-state">no endpoints discovered yet — static engines + Burp emit []. ingest an APK with network code to populate.</div>`;
    } else {
        treeEl.innerHTML = hosts.map((host) => {
            const paths = Object.keys(tree[host]).sort();
            return `
              <div style="margin-bottom:10px">
                <div class="t-mono" style="color:var(--cyan);font-weight:700">▾ ${host}</div>
                ${paths.map((p) => `
                  <div class="t-mono" style="padding-left:18px">
                    <span class="muted small" style="margin-right:8px">${tree[host][p].map((m) => `<span class="chip ${m === "POST" ? "high" : "info"}" style="font-size:9px">${m}</span>`).join(" ")}</span>
                    ${p}
                  </div>`).join("")}
              </div>`;
        }).join("");
    }

    const fl = $("#apimap-flagged");
    if (!data.flagged.length) {
        fl.innerHTML = `<div class="empty-state">no network findings flagged</div>`;
    } else {
        fl.innerHTML = data.flagged.map((f) => `
          <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
            <div class="head">${chip(f.severity)}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
            <div class="title">${f.title}</div>
            <div class="meta">${f.location || "—"}</div>
          </a>`).join("");
    }
}

/* SCREEN 16 — SSL Pinning Map */
function view_project_ssl_map(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "ssl-map")}
      ${sectionHeader("S", "16 // NETWORK", "SSL PINNING MAP")}
      <section class="panel">
        <div class="panel-head"><span>// PINNING STATUS</span><span class="spacer"></span><span class="muted" id="ssl-summary">loading…</span></div>
        <div class="panel-body tight" id="ssl-table">loading…</div>
      </section>
    </div>`;
}

async function mount_project_ssl_map(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/ssl-map`).catch(() => null);
    if (!data) return;
    $("#ssl-summary").textContent = data.pinning_detected ? `pinning detected · ${data.library}` : "no pinning detected";
    const tbl = $("#ssl-table");
    if (!data.rows.length) {
        tbl.innerHTML = `<div class="empty-state">no hosts indexed — needs api_endpoints + ssl_pinning_detected on the AttackSurface.</div>`;
        return;
    }
    tbl.innerHTML = `
      <div class="table-hdr" style="grid-template-columns: 1fr 160px 100px 220px 120px">
        <span>HOST</span><span>LIBRARY</span><span>PINNED</span><span>BYPASS RECIPE</span><span></span>
      </div>` + data.rows.map((r) => `
        <div class="table-row" style="grid-template-columns: 1fr 160px 100px 220px 120px">
          <span class="t-mono">${r.host}</span>
          <span class="t-muted">${r.library}</span>
          <span class="t-mono" style="color:${r.pinned ? "var(--sev-high)" : "var(--acid)"}">${r.pinned ? "yes" : "no"}</span>
          <span class="t-mono" style="color:var(--magenta)">${r.bypass_recipe || "—"}</span>
          <span style="text-align:right">${r.bypass_recipe ? `<a class="btn primary" href="#/recipes" style="padding:4px 10px">[ BYPASS ]</a>` : ""}</span>
        </div>`).join("");
}

/* SCREEN 17 — Attack Surface Graph */
function view_project_surface(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "surface")}
      ${sectionHeader("G", "17 // VISUALIZER", "ATTACK SURFACE GRAPH")}
      <section class="panel">
        <div class="panel-head"><span>// GRAPH</span><span class="spacer"></span><span class="muted" id="surface-summary">loading…</span></div>
        <div class="panel-body" id="surface-canvas" style="min-height:420px;display:flex;align-items:center;justify-content:center">
          <svg id="surface-svg" viewBox="-400 -260 800 520" style="width:100%;height:480px"></svg>
        </div>
      </section>
    </div>`;
}

async function mount_project_surface(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/surface`).catch(() => null);
    if (!data) return;
    $("#surface-summary").textContent = `${(data.nodes || []).length} nodes · ${(data.edges || []).length} edges`;
    const svg = $("#surface-svg");
    if (!svg) return;
    if (!data.nodes.length) {
        svg.outerHTML = `<div class="empty-state">no surface data yet</div>`;
        return;
    }
    const center = data.nodes[0];
    const others = data.nodes.slice(1);
    const R = 200;
    const positions = new Map();
    positions.set(center.id, [0, 0]);
    others.forEach((n, i) => {
        const t = (i / Math.max(others.length, 1)) * 2 * Math.PI;
        positions.set(n.id, [Math.cos(t) * R, Math.sin(t) * R]);
    });
    const sevColor = (s) => ({crit: "#FF3860", high: "#FF9500", med: "#F1C40F", info: "#22DE80"}[s] || "#888");
    const edgeSvg = data.edges.map((e) => {
        const [x1, y1] = positions.get(e.from) || [0, 0];
        const [x2, y2] = positions.get(e.to) || [0, 0];
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#444" stroke-width="1" />`;
    }).join("");
    const nodeSvg = data.nodes.map((n) => {
        const [x, y] = positions.get(n.id) || [0, 0];
        const r = n.kind === "app" ? 16 : 8;
        const ring = n.unprotected ? `<circle cx="${x}" cy="${y}" r="${r + 4}" fill="none" stroke="#FF3860" stroke-dasharray="3,2" />` : "";
        return `${ring}<circle cx="${x}" cy="${y}" r="${r}" fill="${sevColor(n.severity)}" opacity="0.85"/>`
            + `<text x="${x + r + 4}" y="${y + 4}" font-size="10" font-family="Courier Prime, monospace" fill="#aaa">${(n.label || "").slice(0, 24)}</text>`;
    }).join("");
    svg.innerHTML = edgeSvg + nodeSvg;
}

/* SCREEN 18 — Data Flow Diagram */
function view_project_dataflow(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "dataflow")}
      ${sectionHeader("F", "18 // VISUALIZER", "DATA FLOW DIAGRAM")}
      <section class="panel">
        <div class="panel-head"><span>// FLOWS</span><span class="spacer"></span><span class="muted" id="df-summary">loading…</span></div>
        <div class="panel-body" id="df-body">loading…</div>
      </section>
    </div>`;
}

async function mount_project_dataflow(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/dataflow`).catch(() => null);
    if (!data) return;
    $("#df-summary").textContent = `${data.flows.length} flow(s)`;
    const body = $("#df-body");
    if (!data.flows.length) {
        body.innerHTML = `<div class="empty-state">no flows derived yet — needs categorized findings</div>`;
        return;
    }
    body.innerHTML = `
      <div class="row" style="align-items:flex-start;gap:24px">
        <div class="col grow">
          <div class="panel-head" style="background:transparent;padding:0;border:0">// SOURCES</div>
          ${data.sources.map((s) => `<div class="t-mono" style="padding:4px 8px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;margin:4px 0">${s}</div>`).join("")}
        </div>
        <div class="col grow">
          <div class="panel-head" style="background:transparent;padding:0;border:0">// FLOWS</div>
          ${data.flows.map((f) => `
            <a class="row" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.finding_id)}" style="padding:6px 10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;margin:4px 0;text-decoration:none">
              <span class="t-mono">${f.source}</span>
              <span style="color:var(--magenta)">→</span>
              <span class="t-mono">${f.sink}</span>
              <span class="grow"></span>
              ${chip(f.severity)}
            </a>`).join("")}
        </div>
        <div class="col grow">
          <div class="panel-head" style="background:transparent;padding:0;border:0">// SINKS</div>
          ${data.sinks.map((s) => `<div class="t-mono" style="padding:4px 8px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;margin:4px 0">${s}</div>`).join("")}
        </div>
      </div>`;
}

/* SCREEN 19 — Attack Tree */
function view_project_attack_tree(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "attack-tree")}
      ${sectionHeader("T", "19 // VISUALIZER", "ATTACK TREE")}
      <section class="panel">
        <div class="panel-head"><span>// CHAINS</span><span class="spacer"></span><span class="muted" id="at-summary">loading…</span></div>
        <div class="panel-body col" style="gap:14px" id="at-body">loading…</div>
      </section>
    </div>`;
}

async function mount_project_attack_tree(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/attack-tree`).catch(() => null);
    if (!data) return;
    $("#at-summary").textContent = `${data.trees.length} chain(s)`;
    const body = $("#at-body");
    if (!data.trees.length) {
        body.innerHTML = `<div class="empty-state">no high/critical findings to chain — wait for static engines to fire.</div>`;
        return;
    }
    body.innerHTML = data.trees.map((t) => `
      <div style="border:1px solid var(--border);border-radius:2px;padding:12px">
        <div class="row" style="margin-bottom:8px">
          ${chip(t.severity)}
          <a class="t-mono" style="color:var(--cyan);font-weight:700;text-decoration:none" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(t.finding_id)}">${t.finding_id} · ${t.title}</a>
          <span class="grow"></span>
          <span class="muted small">CVSS ≈ ${t.cvss_estimate}</span>
        </div>
        <div class="row" style="gap:8px;align-items:stretch">
          ${t.nodes.map((n) => `
            <div class="col grow" style="padding:10px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px">
              <div class="kicker" style="color:var(--magenta)">${String(n.step).padStart(2,"0")} · ${n.label}</div>
              <div class="t-muted small" style="margin-top:6px">${n.detail}</div>
            </div>`).join('<div style="align-self:center;color:var(--magenta);font-size:18px">→</div>')}
        </div>
      </div>`).join("");
}

/* SCREEN 20 — OWASP MASVS Matrix */
function view_project_owasp(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "owasp")}
      ${sectionHeader("M", "20 // VISUALIZER", "OWASP MASVS MATRIX")}
      <section class="panel">
        <div class="panel-head"><span>// COMPLIANCE</span><span class="spacer"></span><span class="muted" id="owasp-summary">loading…</span></div>
        <div class="panel-body" id="owasp-grid">loading…</div>
      </section>
    </div>`;
}

async function mount_project_owasp(ctx) {
    const id = ctx.params.id;
    const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/owasp`).catch(() => null);
    if (!data) return;
    const failing = data.summary.failing_controls || 0;
    const total = data.summary.total_controls || 0;
    $("#owasp-summary").textContent = `${failing}/${total} controls failing`;
    const cell = (ids) => {
        if (!ids.length) return `<span class="chip low" style="width:60px;display:inline-block;text-align:center">PASS</span>`;
        return `<span class="chip crit" style="width:60px;display:inline-block;text-align:center">${ids.length} ✕</span>`;
    };
    const grid = data.domains.map((d) => `
      <div class="table-row" style="grid-template-columns: 220px 90px 90px 90px 1fr">
        <span class="t-mono">${d}</span>
        <span>${cell(data.matrix[d].L1)}</span>
        <span>${cell(data.matrix[d].L2)}</span>
        <span>${cell(data.matrix[d].R)}</span>
        <span class="t-muted">${[...data.matrix[d].L1, ...data.matrix[d].L2, ...data.matrix[d].R].slice(0, 6).join(" · ") || "all clear"}</span>
      </div>`).join("");
    $("#owasp-grid").innerHTML = `
      <div class="table-hdr" style="grid-template-columns: 220px 90px 90px 90px 1fr">
        <span>DOMAIN</span><span>L1</span><span>L2</span><span>RESILIENCE</span><span>FAILING IDS</span>
      </div>${grid}`;
}

/* SCREEN 23 — Diff Report */
function view_report_diff() {
    return h`
    <div class="main">
      ${sectionHeader("D", "23 // REPORT", "DIFF REPORT")}
      <section class="row">
        <div class="input grow"><span class="prompt">A</span><select id="diff-a"><option value="">— project A —</option></select></div>
        <div class="input grow"><span class="prompt">B</span><select id="diff-b"><option value="">— project B —</option></select></div>
        <button class="btn primary" id="diff-run">[ COMPUTE DIFF ]</button>
      </section>
      <section class="panel">
        <div class="panel-head">// DIFF</div>
        <div class="panel-body" id="diff-out"><div class="muted">pick two projects then [ COMPUTE DIFF ]</div></div>
      </section>
    </div>`;
}

async function mount_report_diff() {
    const projects = await getJSON("/v1/projects").catch(() => []);
    const opts = projects.map((p) => `<option value="${p.id}">${p.package_name || p.id} · v${p.version_name || "?"}</option>`).join("");
    $("#diff-a").innerHTML = `<option value="">— project A —</option>${opts}`;
    $("#diff-b").innerHTML = `<option value="">— project B —</option>${opts}`;
    $("#diff-run").addEventListener("click", async () => {
        const a = $("#diff-a").value; const b = $("#diff-b").value;
        if (!a || !b) { $("#diff-out").innerHTML = `<div class="empty-state">pick both A and B</div>`; return; }
        const [pa, pb] = await Promise.all([
            getJSON(`/v1/projects/${encodeURIComponent(a)}/findings`),
            getJSON(`/v1/projects/${encodeURIComponent(b)}/findings`),
        ]);
        const ids = (arr) => new Set(arr.map((f) => f.id));
        const A = ids(pa); const B = ids(pb);
        const fixed = pa.filter((f) => !B.has(f.id));
        const newOnes = pb.filter((f) => !A.has(f.id));
        const unchanged = pa.filter((f) => B.has(f.id));
        const block = (title, color, list) => `
          <section class="panel" style="margin-top:8px">
            <div class="panel-head" style="color:${color}">// ${title} · ${list.length}</div>
            <div class="panel-body col" style="gap:6px">${list.length ? list.map((f) => `<div class="row">${chip(f.severity)}<span class="grow">${f.title}</span><span class="muted small">${f.id}</span></div>`).join("") : '<div class="muted small">—</div>'}</div>
          </section>`;
        $("#diff-out").innerHTML = block("FIXED", "var(--acid)", fixed) + block("NEW", "var(--sev-crit)", newOnes) + block("UNCHANGED", "var(--cyan)", unchanged);
    });
}

/* SCREEN 24 — Pipeline Editor */
function view_pipeline() {
    return h`
    <div class="main">
      ${sectionHeader("P", "24 // AUTOMATION", "PIPELINE EDITOR")}
      <section class="row" style="align-items:flex-start;gap:12px">
        <section class="panel" style="width:300px;flex:none">
          <div class="panel-head">// PIPELINES</div>
          <div class="panel-body col" style="gap:6px" id="pl-list">loading…</div>
        </section>
        <section class="panel grow">
          <div class="panel-head"><span>// YAML</span><span class="spacer"></span><button class="btn" id="pl-validate">[ VALIDATE ]</button><button class="btn primary" id="pl-run">[ RUN ]</button></div>
          <pre class="code" id="pl-yaml" style="min-height:340px">select a pipeline →</pre>
        </section>
      </section>
      <section class="panel">
        <div class="panel-head">// STAGE GRAPH</div>
        <div class="panel-body" id="pl-stages">loading…</div>
      </section>
    </div>`;
}

async function mount_pipeline() {
    const pipelines = await getJSON("/v1/pipelines").catch(() => []);
    const list = $("#pl-list");
    let active = pipelines[0]?.name || null;
    const renderList = () => list.innerHTML = pipelines.map((p) => `
        <a href="#" data-pl="${p.name}" class="row" style="padding:8px 10px;background:${p.name === active ? "var(--bg-accent-panel)" : "var(--bg-panel)"};border:1px solid ${p.name === active ? "var(--border-accent)" : "var(--border)"};border-radius:2px;text-decoration:none;color:inherit">
          <span class="t-mono" style="color:${p.name === active ? "var(--acid)" : "var(--cyan)"};font-weight:700">${p.name}</span>
          <span class="grow"></span>
          <span class="muted small">${(p.title || "").slice(0, 24)}</span>
        </a>`).join("");
    const showActive = () => {
        const p = pipelines.find((p) => p.name === active);
        if (!p) return;
        $("#pl-yaml").textContent = p.yaml || "(empty)";
        const stages = (p.yaml.match(/- name: ([^\n]+)/g) || []).map((s) => s.replace("- name: ", ""));
        const inline = (p.yaml.match(/-\s*\{\s*engine:\s*(\w+)/g) || []).map((s) => s.match(/engine:\s*(\w+)/)[1]);
        const all = stages.length ? stages : inline;
        $("#pl-stages").innerHTML = all.length
            ? `<div class="row" style="gap:6px;align-items:center;flex-wrap:wrap">${all.map((s, i) => `<div style="padding:8px 14px;background:var(--bg-panel);border:1px solid var(--border);border-radius:2px"><span class="t-mono" style="color:var(--magenta)">${String(i + 1).padStart(2, "0")}</span> <span class="t-mono">${s}</span></div>${i < all.length - 1 ? '<span style="color:var(--magenta)">→</span>' : ""}`).join("")}</div>`
            : `<div class="muted">no stages parsed</div>`;
    };
    renderList(); showActive();
    list.addEventListener("click", (e) => {
        const a = e.target.closest("[data-pl]");
        if (!a) return; e.preventDefault();
        active = a.dataset.pl;
        renderList(); showActive();
    });
    $("#pl-validate").addEventListener("click", () => {
        $("#pl-validate").textContent = "[ ✓ STRUCTURE OK ]";
        $("#pl-validate").style.color = "var(--acid)";
    });
    $("#pl-run").addEventListener("click", async () => {
        const projects = await getJSON("/v1/projects").catch(() => []);
        if (!projects.length || !active) { alert("need a project + a selected pipeline"); return; }
        const fd = new FormData(); fd.append("project_id", projects[0].id);
        const r = await fetch(`/v1/pipelines/${encodeURIComponent(active)}/run`, { method: "POST", body: fd });
        const j = await r.json().catch(() => ({}));
        $("#pl-run").textContent = r.ok ? `[ ${(j.status || "OK").toUpperCase()} ]` : "[ FAILED ]";
        $("#pl-run").style.color = r.ok ? "var(--acid)" : "var(--sev-crit)";
    });
}

/* SCREEN 28 — Terminal Console */
function view_terminal() {
    return h`
    <div class="main">
      ${sectionHeader("T", "28 // SYSTEM", "TERMINAL CONSOLE")}
      <section class="panel">
        <div class="panel-head"><span>// nexus :: shell</span><span class="spacer"></span><button class="btn" id="term-clear">[ CLEAR ]</button></div>
        <div class="panel-body console" id="term-out" style="min-height:320px"></div>
        <div class="panel-body" style="border-top:1px solid var(--border)">
          <div class="input grow">
            <span class="prompt">nexus&gt;</span>
            <input id="term-in" placeholder="type 'help' for commands" autocomplete="off">
            <span class="cursor">_</span>
          </div>
        </div>
      </section>
      <div class="muted small">runs read-only commands against the local API. nothing destructive.</div>
    </div>`;
}

function mount_terminal() {
    const out = $("#term-out");
    const inp = $("#term-in");
    const writeLine = (text, klass = "") => {
        const div = document.createElement("div");
        if (klass) div.innerHTML = `<span class="${klass}">${escapeHtml(text)}</span>`;
        else div.textContent = text;
        out.appendChild(div);
        out.scrollTop = out.scrollHeight;
    };
    writeLine("[NEXUS] terminal armed · type `help` for commands", "nexus");
    const COMMANDS = {
        help: () => { writeLine("commands: doctor · device · settings · projects · health · clear · about"); },
        clear: () => { out.innerHTML = ""; },
        doctor: async () => { const j = await getJSON("/v1/doctor").catch(() => []); j.forEach((r) => writeLine(`${r.installed ? "● OK  " : "● MISS"}  ${(r.name || "?").padEnd(10)} ${r.version || ""}`, r.installed ? "" : "crit")); },
        device: async () => { const j = await getJSON("/v1/device/info").catch(() => null); writeLine(JSON.stringify(j, null, 2)); },
        settings: async () => { const j = await getJSON("/v1/settings").catch(() => null); writeLine(JSON.stringify(j, null, 2)); },
        projects: async () => { const j = await getJSON("/v1/projects").catch(() => []); j.forEach((p) => writeLine(`${p.id}  ${p.package_name}  v${p.version_name}  risk=${p.risk_score}`)); },
        health: async () => { const j = await getJSON("/v1/health").catch(() => null); writeLine(JSON.stringify(j)); },
        about: () => { writeLine("MEDUSA NEXUS v0.1.0-alpha · every head sees a different angle", "nexus"); },
    };
    inp.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        const cmd = inp.value.trim();
        if (!cmd) return;
        writeLine(`nexus> ${cmd}`, "meta");
        inp.value = "";
        const fn = COMMANDS[cmd.split(" ")[0]];
        if (!fn) writeLine(`unknown command: ${cmd}`, "crit");
        else { try { await fn(); } catch (err) { writeLine(`error: ${err.message}`, "crit"); } }
    });
    $("#term-clear").addEventListener("click", () => { out.innerHTML = ""; });
}

/* SCREEN 29 — Empty + Error States Catalog */
function view_states() {
    const cards = [
        ["404", "GHOST ROUTE", "var(--magenta)", "no view wired for this hash", "[ HOME ]", "#/dashboard"],
        ["503", "ENGINE OFFLINE", "var(--sev-crit)", "burp / mobsf not reachable on the configured URL", "[ DOCTOR ]", "#/tools"],
        ["☐", "NO PROJECTS YET", "var(--acid)", "go ingest something", "[ SCAN ]", "#/scan"],
        ["⚠", "NO DEVICE", "var(--sev-high)", "plug a phone, authorize USB debugging", "[ BRIDGE ]", "#/device/bridge"],
        ["✕", "PIPELINE FAILED", "var(--sev-crit)", "stage 04 returned non-zero — see toast", "[ EDITOR ]", "#/pipeline"],
        ["✓", "ALL CLEAR", "var(--acid)", "no critical, no high — sleep is permissible", "[ REPORT ]", "#/report"],
    ];
    return h`
    <div class="main">
      ${sectionHeader("E", "29 // STATES", "EMPTY + ERROR STATES")}
      <section class="row" style="flex-wrap:wrap;gap:12px">
        ${cards.map(([glyph, title, color, sub, btnText, btnHref]) => `
          <div style="width:280px;padding:18px;border:1px solid var(--border);border-radius:2px;background:var(--bg-panel)">
            <div style="font-size:48px;color:${color};letter-spacing:4px">${glyph}</div>
            <div style="font-size:18px;color:${color};letter-spacing:2px;margin-top:6px">${title}</div>
            <div class="muted small" style="margin:8px 0 12px">${sub}</div>
            <a class="btn primary" href="${btnHref}">${btnText}</a>
          </div>`).join("")}
      </section>
    </div>`;
}

/* SCREEN 30 — Toast Stack */
function view_toasts() {
    const items = [
        ["[+]", "var(--acid)", "scan finished", "com.target.banking · 4m 12s"],
        ["[!]", "var(--sev-high)", "frida disconnected", "device unplugged at 2026-04-25 09:14"],
        ["[×]", "var(--sev-crit)", "pipeline failed", "stage 04 (mobsf) → 502"],
        ["[i]", "var(--cyan)", "report ready", "PDF · 4.2 MB · ~/.mnexus/workspace/reports"],
        ["[+]", "var(--acid)", "device pulled", "com.target.legacy.auth · base + 0 splits"],
    ];
    return h`
    <div class="main">
      ${sectionHeader("T", "30 // STATES", "TOAST STACK")}
      <section class="panel">
        <div class="panel-head">// STREAM (catalog · auto-dismiss disabled here)</div>
        <div class="panel-body col" style="gap:8px">
          ${items.map(([glyph, color, title, sub]) => `
            <div class="row" style="padding:10px 14px;background:var(--bg-panel);border-left:3px solid ${color};border-radius:2px">
              <span class="t-mono" style="color:${color};font-weight:700">${glyph}</span>
              <div class="col">
                <span class="t-mono" style="color:${color};font-weight:700;letter-spacing:2px">${title.toUpperCase()}</span>
                <span class="muted small">${sub}</span>
              </div>
              <span class="grow"></span>
              <button class="btn" style="padding:2px 8px">[ DISMISS ]</button>
            </div>`).join("")}
        </div>
      </section>
      <div class="muted small">toasts in production come from /v1/events (server-sent — pending) and stack bottom-right.</div>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Route map + router
 * ═══════════════════════════════════════════════════════════════════════════ */
const ROUTES = [
    { path: "boot",                             view: view_boot },
    { path: "dashboard",                        view: view_dashboard,         mount: mount_dashboard },
    { path: "projects",                         view: view_projects,          mount: mount_projects },
    { path: "scan",                             view: view_scan,              mount: async (ctx) => { mount_scan(); await mount_scan_after_upload_wiring(); } },
    { path: "devices",                          view: view_devices,           mount: mount_devices },
    { path: "adb",                              view: view_devices,           mount: mount_devices },  // alias of /devices
    { path: "device/pull",                      view: view_device_pull,       mount: mount_device_pull },
    { path: "device/bridge",                    view: view_device_bridge,     mount: mount_device_bridge },
    { path: "device/shell",                     view: view_device_shell,      mount: mount_device_shell },
    { path: "device/files",                     view: view_device_files,      mount: mount_device_files },
    { path: "device/screen",                    view: view_device_screen,     mount: mount_device_screen },
    { path: "device/logcat",                    view: view_device_logcat,     mount: mount_device_logcat },
    { path: "adb",                              view: view_adb,               mount: mount_adb },
    { path: "dynamic",                          view: (ctx) => view_project_dynamic(ctx), mount: mount_project_dynamic },
    { path: "network",                          view: (ctx) => view_project_network(ctx) },
    { path: "report",                           view: view_report,            mount: mount_report },
    { path: "report/diff",                      view: view_report_diff,       mount: mount_report_diff },
    { path: "pipeline",                         view: view_pipeline,          mount: mount_pipeline },
    { path: "recipes",                          view: view_recipes,           mount: mount_recipes },
    { path: "tools",                            view: view_tools,             mount: mount_tools },
    { path: "settings",                         view: view_settings,          mount: mount_settings },
    { path: "about",                            view: view_about },
    { path: "terminal",                         view: view_terminal,          mount: mount_terminal },
    { path: "states",                           view: view_states },
    { path: "toasts",                           view: view_toasts },
    { path: "finding/:fid",                     view: view_finding_detail,    mount: mount_finding_detail },

    /* project scoped */
    { path: "project/:id/overview",             view: view_project_overview,  mount: mount_project_overview },
    { path: "project/:id/static",               view: view_project_static,    mount: mount_project_static },
    { path: "project/:id/static/secrets",       view: view_project_secrets,    mount: mount_project_secrets },
    { path: "project/:id/static/components",    view: view_project_components, mount: mount_project_components },
    { path: "project/:id/static/native",        view: view_project_native,     mount: mount_project_native },
    { path: "project/:id/dynamic",              view: view_project_dynamic,   mount: mount_project_dynamic },
    { path: "project/:id/tracer",               view: view_project_tracer,    mount: mount_project_tracer },
    { path: "project/:id/network",              view: view_project_network,   mount: mount_project_network },
    { path: "project/:id/api-map",              view: view_project_api_map,   mount: mount_project_api_map },
    { path: "project/:id/ssl-map",              view: view_project_ssl_map,   mount: mount_project_ssl_map },
    { path: "project/:id/surface",              view: view_project_surface,   mount: mount_project_surface },
    { path: "project/:id/dataflow",             view: view_project_dataflow,  mount: mount_project_dataflow },
    { path: "project/:id/attack-tree",          view: view_project_attack_tree, mount: mount_project_attack_tree },
    { path: "project/:id/owasp",                view: view_project_owasp,     mount: mount_project_owasp },
    { path: "project/:id/report",               view: view_project_report },
    { path: "project/:id/finding/:fid",         view: view_finding_detail,    mount: mount_finding_detail },
];

function matchRoute(hashPath) {
    for (const route of ROUTES) {
        const patternParts = route.path.split("/");
        const pathParts = hashPath.split("/");
        if (patternParts.length !== pathParts.length) continue;
        const params = {};
        let matched = true;
        for (let i = 0; i < patternParts.length; i++) {
            if (patternParts[i].startsWith(":")) {
                params[patternParts[i].slice(1)] = decodeURIComponent(pathParts[i]);
            } else if (patternParts[i] !== pathParts[i]) {
                matched = false;
                break;
            }
        }
        if (matched) return { route, params };
    }
    return null;
}

function setActiveSidebar(topLevel) {
    $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.route === topLevel));
}

async function renderRoute() {
    const raw = location.hash.replace(/^#\/?/, "") || "dashboard";
    const [pathPart] = raw.split("?");
    const hit = matchRoute(pathPart);
    const ctx = { params: hit?.params || {}, hash: raw };
    const view = $("#view");
    if (!view) return;
    if (!hit) {
        view.innerHTML = h`
        <div class="main">
          <div class="empty-state">
            <div style="font-size:48px;color:var(--magenta);letter-spacing:4px">404 // GHOST ROUTE</div>
            <div class="muted">no view wired for <code>#/${pathPart}</code></div>
            <div style="margin-top:16px"><a class="btn primary" href="#/dashboard">[ HOME ]</a></div>
          </div>
        </div>`;
        setActiveSidebar(null);
        return;
    }
    view.innerHTML = hit.route.view(ctx);
    // Update sidebar active based on top-level segment (sidebar only lists the 9 primaries).
    const topLevel = pathPart.split("/")[0];
    setActiveSidebar(topLevel);
    if (typeof hit.route.mount === "function") {
        try { await hit.route.mount(ctx); } catch (e) { console.error("mount failed:", e); }
    }
    document.title = `🔱 MEDUSA::NEXUS / ${pathPart}`;
}

/* ─── live clock ─── */
function tickClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const iso = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
    const t = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
    const el = $("#clock");
    if (el) el.textContent = `${iso} · ${t} UTC`;
}

/* ─── bootstrap ─── */
window.addEventListener("hashchange", renderRoute);
window.addEventListener("DOMContentLoaded", () => {
    if (!location.hash) location.replace("#/dashboard");
    renderRoute();
    tickClock();
    setInterval(tickClock, 1000);
});
