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
        <div class="sub">or paste a path · or pull from device</div>
        <div class="wink">SHA-256 gets computed. VirusTotal gets called. You just sit there.</div>
        <div class="actions">
          <button class="btn primary">[ BROWSE ]</button>
          <a class="btn" href="#/device/pull">[ PULL FROM DEVICE ]</a>
          <a class="btn" href="#/device/bridge">[ DEVICE BRIDGE ]</a>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">// RECENT IMPORTS · last 10</div>
        <div class="panel-body empty-state">
          nothing imported yet. run <code>mnexus scan ./target.apk --package com.target.app</code>
        </div>
      </section>
    </div>`;
}

function mount_scan() {
    const dz = $("#dz");
    if (!dz) return;
    ["dragenter", "dragover"].forEach((e) => dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.add("over"); }));
    ["dragleave", "drop"].forEach((e) => dz.addEventListener(e, () => dz.classList.remove("over")));
    dz.addEventListener("drop", (ev) => {
        ev.preventDefault();
        const f = ev.dataTransfer?.files?.[0];
        if (f) alert(`received ${f.name} — upload endpoint not wired yet (iteration 2).`);
    });
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
 *  SCREEN 06 — Device Bridge
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_device_bridge() {
    return h`
    <div class="main">
      ${sectionHeader("B", "06 // INTAKE", "DEVICE BRIDGE")}
      <section class="row" style="gap:16px">
        <section class="panel grow">
          <div class="panel-head">// DEVICE</div>
          <div class="panel-body col">
            <div class="row"><span class="muted small" style="width:120px">MODEL</span><span class="t-mono">Pixel 6</span></div>
            <div class="row"><span class="muted small" style="width:120px">ANDROID</span><span class="t-mono">14 (API 34)</span></div>
            <div class="row"><span class="muted small" style="width:120px">ABI</span><span class="t-mono">arm64-v8a</span></div>
            <div class="row"><span class="muted small" style="width:120px">ROOTED</span><span class="t-mono" style="color:var(--acid)">yes · RootBeer v0.0.9 bypass-able</span></div>
            <div class="row"><span class="muted small" style="width:120px">FRIDA-SERVER</span><span class="t-mono" style="color:var(--sev-high)">staged · not running</span></div>
          </div>
        </section>
        <section class="panel grow">
          <div class="panel-head">// ACTIONS</div>
          <div class="panel-body col">
            <button class="btn primary">[ START FRIDA-SERVER ]</button>
            <button class="btn">[ PUSH SCRIPTS ]</button>
            <button class="btn">[ PATCH WITH STHENO ]</button>
            <button class="btn danger">[ FORCE REBOOT ]</button>
          </div>
        </section>
      </section>
      <section class="panel">
        <div class="panel-head">// ADB CONSOLE</div>
        <div class="panel-body console">
<span class="nexus">$ adb shell getprop ro.build.version.release</span>
14
<span class="nexus">$ adb shell getprop ro.product.cpu.abi</span>
arm64-v8a
<span class="nexus">$ adb shell id</span>
uid=2000(shell) gid=2000(shell)
<span class="nexus">$ _</span>
        </div>
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
 *  Stub screens for everything else
 * ═══════════════════════════════════════════════════════════════════════════ */
const STUBS = {
    "project-secrets":    stubData("09", "S", "SECRETS + CRYPTO AUDIT", "Detected secrets + algorithm heatmap.", [
        "table: type · file · line · entropy · confidence · masked sample",
        "heatmap: algorithm × files — red on AES/ECB, DES, MD5, custom",
        "panel: IV reuse, hardcoded keys, insecure PRNG, constant salts",
    ]),
    "project-components": stubData("10", "C", "COMPONENTS + DEEP LINKS", "Manifest-declared surface + deep-link tester.", [
        "tabs: activities · services · receivers · providers · deeplinks",
        "per component: exported, permission, intent filters, handler class, [TEST WITH AM START]",
        "deeplink tester: compose URIs, spawn activity via adb, watch logcat for handler output",
    ]),
    "project-native":     stubData("11", "N", "NATIVE · GHIDRA", "Per .so: JNI · crypto · anti-tamper.", [
        "registered JNI methods + signatures",
        "crypto primitives detected (AES, RSA, custom)",
        "anti-tamper + root checks + debugger probes",
        "string cross-refs · export function → generate Frida stalker",
    ]),
    "project-tracer":     stubData("13", "T", "LIVE METHOD TRACER", "Pick a class/method, watch args/returns.", [
        "filter by package prefix · redact PII on demand",
        "jump to JADX source on stack frame click",
        "streaming via /v1/dynamic/ws (WebSocket, pending)",
    ]),
    "project-api-map":    stubData("15", "A", "API ENDPOINT MAP", "Tree view merged from static + dynamic.", [
        "host → path segments → methods",
        "flags: [AUTH-REQUIRED] [SENSITIVE-DATA] [UNVERIFIED]",
        "click → see every captured request/response",
    ]),
    "project-ssl-map":    stubData("16", "S", "SSL PINNING MAP", "Domains × libraries + targeted bypasses.", [
        "TrustManager · OkHttp · network-security-config · custom",
        "per row: [ BYPASS ] loads the exact Frida script",
    ]),
    "project-surface":    stubData("17", "G", "ATTACK SURFACE GRAPH", "Interactive force-directed graph.", [
        "nodes = components (A/S/R/P), edges = intent filters",
        "node color = severity, ring = exported/unprotected",
        "click → filter findings list",
    ]),
    "project-dataflow":   stubData("18", "F", "DATA FLOW DIAGRAM", "Input → processing → storage → network.", [
        "swimlane view with finding annotations inline",
        "sensitive-data taint highlighted in magenta",
    ]),
    "project-attack-tree":stubData("19", "T", "ATTACK TREE", "Per high-severity finding: prereqs → steps → impact.", [
        "collapsible nodes, CVSS per leaf",
        "[ simulate attack ] replays the chain via Frida + burp",
    ]),
    "project-owasp":      stubData("20", "M", "OWASP MASVS MATRIX", "Controls × levels + mitigation column.", [
        "grid: V1–V8 × L1/L2/R, green/red/orange cells",
        "side drawer per cell: failing findings with Mitigation",
    ]),
    "report-diff":        stubData("23", "D", "DIFF REPORT", "Side-by-side of two runs.", [
        "fixed · regressed · new · unchanged",
        "each fixed finding shows the mitigation the dev implemented",
    ]),
    "pipeline":           stubData("24", "P", "PIPELINE EDITOR", "YAML + stage graph.", [
        "Monaco YAML editor ← → stage graph",
        "drag engines into stages, parallel branches supported",
        "[ RUN ] [ SAVE ] [ VALIDATE ] · export YAML to CI",
    ]),
    "terminal":           stubData("28", "T", "TERMINAL CONSOLE", "Embedded xterm for mnexus + Frida REPL + adb shell.", [
        "splittable panes",
        "copy session as report evidence",
        "tab-complete for packages + engines",
    ]),
    "states":             stubData("29", "E", "EMPTY + ERROR STATES", "Catalog of friendly-angry states.", [
        "SIGNAL LOST · NO PROJECTS — GO FIND SOMETHING TO BREAK",
        "ENGINE OFFLINE · 404 // GHOST ROUTE",
        "each: large ASCII glyph + terse copy + action + fallback",
    ]),
    "toasts":             stubData("30", "T", "TOAST STACK", "Bottom-right terminal-style toasts.", [
        "[+] scan finished in 4m 12s",
        "[!] frida disconnected",
        "[×] pipeline failed at stage 04",
        "severity-colored border, monospace, auto-dismiss",
    ]),
};

function stubData(num, letter, title, detail, features) {
    return { id: `${num} // STUB`, kicker: `${num} // PENCIL FIDELITY`, title, hero: letter, detail, features };
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Route map + router
 * ═══════════════════════════════════════════════════════════════════════════ */
const ROUTES = [
    { path: "boot",                             view: view_boot },
    { path: "dashboard",                        view: view_dashboard,         mount: mount_dashboard },
    { path: "projects",                         view: view_projects,          mount: mount_projects },
    { path: "scan",                             view: view_scan,              mount: mount_scan },
    { path: "device/pull",                      view: view_device_pull },
    { path: "device/bridge",                    view: view_device_bridge },
    { path: "dynamic",                          view: (ctx) => view_project_dynamic(ctx) },
    { path: "network",                          view: (ctx) => view_project_network(ctx) },
    { path: "report",                           view: view_report },
    { path: "report/diff",                      view: (ctx) => stub(STUBS["report-diff"]) },
    { path: "pipeline",                         view: (ctx) => stub(STUBS["pipeline"]) },
    { path: "recipes",                          view: view_recipes },
    { path: "tools",                            view: view_tools,             mount: mount_tools },
    { path: "settings",                         view: view_settings },
    { path: "about",                            view: view_about },
    { path: "terminal",                         view: (ctx) => stub(STUBS["terminal"]) },
    { path: "states",                           view: (ctx) => stub(STUBS["states"]) },
    { path: "toasts",                           view: (ctx) => stub(STUBS["toasts"]) },
    { path: "finding/:fid",                     view: view_finding_detail },

    /* project scoped */
    { path: "project/:id/overview",             view: view_project_overview },
    { path: "project/:id/static",               view: view_project_static },
    { path: "project/:id/static/secrets",       view: (ctx) => stub(STUBS["project-secrets"]) },
    { path: "project/:id/static/components",    view: (ctx) => stub(STUBS["project-components"]) },
    { path: "project/:id/static/native",        view: (ctx) => stub(STUBS["project-native"]) },
    { path: "project/:id/dynamic",              view: view_project_dynamic },
    { path: "project/:id/tracer",               view: (ctx) => stub(STUBS["project-tracer"]) },
    { path: "project/:id/network",              view: view_project_network },
    { path: "project/:id/api-map",              view: (ctx) => stub(STUBS["project-api-map"]) },
    { path: "project/:id/ssl-map",              view: (ctx) => stub(STUBS["project-ssl-map"]) },
    { path: "project/:id/surface",              view: (ctx) => stub(STUBS["project-surface"]) },
    { path: "project/:id/dataflow",             view: (ctx) => stub(STUBS["project-dataflow"]) },
    { path: "project/:id/attack-tree",          view: (ctx) => stub(STUBS["project-attack-tree"]) },
    { path: "project/:id/owasp",                view: (ctx) => stub(STUBS["project-owasp"]) },
    { path: "project/:id/report",               view: view_project_report },
    { path: "project/:id/finding/:fid",         view: view_finding_detail },
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
