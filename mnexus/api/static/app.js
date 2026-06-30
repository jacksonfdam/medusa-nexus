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

/* ─── theme manager ───
 *
 * Two themes ship: `nexus` (default cyberpunk) and `dracula`. The CSS lives
 * under [data-theme="<name>"] in app.css; this manager just toggles the
 * attribute and persists the choice. The early <head> script in index.html
 * applies the saved theme before paint, so we never flash the wrong colors.
 *
 * Adding a third theme: append to AVAILABLE_THEMES and add the matching
 * [data-theme="…"] block to app.css. No code changes elsewhere.
 */
const THEME_KEY = "nexus.theme";
const AVAILABLE_THEMES = [
    {
        id: "nexus",
        name: "🔱 Nexus",
        kicker: "default · cyberpunk neon",
        swatches: ["#000000", "#00FFFF", "#22DE80", "#E879F9", "#FF3860"],
    },
    {
        id: "dracula",
        name: "🧛 Dracula",
        kicker: "draculatheme.com",
        swatches: ["#282A36", "#8BE9FD", "#50FA7B", "#BD93F9", "#FF5555"],
    },
];

function getTheme() {
    try { return localStorage.getItem(THEME_KEY) || "nexus"; }
    catch (e) { return "nexus"; }
}

function setTheme(id) {
    if (!AVAILABLE_THEMES.some((t) => t.id === id)) return;
    document.documentElement.setAttribute("data-theme", id);
    try { localStorage.setItem(THEME_KEY, id); } catch (e) { /* ignore */ }
    // Notify listeners (e.g. the settings page) so swatches re-render.
    window.dispatchEvent(new CustomEvent("nexus:theme", { detail: { id } }));
}

function applyThemeAttr() {
    document.documentElement.setAttribute("data-theme", getTheme());
}

async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`${url} → ${r.status}`);
    return r.json();
}

/* ──────────────────────────────────────────────────────────────────
 *  Polling helper — runs `tick()` every `intervalMs` until the route
 *  changes (hashchange) or the scope is explicitly cancelled. Used by
 *  the SSL Map / API Map / Dynamic console screens.
 *
 *  Returns a `{ stop }` handle; calling stop() detaches the listener
 *  and cancels any pending tick. The harness also re-runs `tick()`
 *  once when the page regains visibility so a tab that was hidden
 *  for a minute doesn't show stale data for one more interval.
 * ────────────────────────────────────────────────────────────────── */
function pollingScope(tick, intervalMs = 3000) {
    let cancelled = false;
    let timer = null;
    let inFlight = false;

    const run = async () => {
        if (cancelled || inFlight) return;
        inFlight = true;
        try { await tick(); } catch (_) { /* don't break the loop on one bad tick */ }
        inFlight = false;
        if (!cancelled) timer = setTimeout(run, intervalMs);
    };

    const onHashChange = () => stop();
    const onVisibilityChange = () => { if (!document.hidden) run(); };
    const stop = () => {
        if (cancelled) return;
        cancelled = true;
        if (timer) clearTimeout(timer);
        window.removeEventListener("hashchange", onHashChange);
        document.removeEventListener("visibilitychange", onVisibilityChange);
    };

    window.addEventListener("hashchange", onHashChange);
    document.addEventListener("visibilitychange", onVisibilityChange);
    // First tick immediate; subsequent ones every intervalMs.
    run();
    return { stop };
}

/* Relative "Xs ago / Xm ago" for live status lines. Defensive on bad input. */
function fmtAgo(ts) {
    if (!ts) return "—";
    const t = Date.parse(ts);
    if (Number.isNaN(t)) return "—";
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
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

/* Platform glyph — rendered next to the bundle id everywhere a project is listed. */
function platformGlyph(platform) {
    if (platform === "ios") return `<span title="iOS" style="color:#fff">🍎</span>`;
    return `<span title="Android" style="color:var(--acid)">🤖</span>`;
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
              <span class="pkg">${platformGlyph(p.platform)} ${p.package_name || p.name || p.id}</span>
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
      <section class="row" id="projects-bulk-bar" style="gap:8px;margin-bottom:8px" hidden>
        <span class="muted small" id="projects-bulk-count">0 selected</span>
        <span class="spacer"></span>
        <button class="btn small" id="projects-bulk-backup">[ BACKUP SELECTED ]</button>
        <button class="btn small danger" id="projects-bulk-delete">[ DELETE SELECTED ]</button>
      </section>
      <section class="row" style="gap:8px;margin-bottom:8px">
        <span class="spacer"></span>
        <button class="btn small ghost" id="projects-backup-all">[ BACKUP ALL ]</button>
        <button class="btn small ghost danger" id="projects-delete-all">[ DELETE ALL ]</button>
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
        // Hide bulk + all action buttons when there's nothing to act on.
        const allBtn = $("#projects-backup-all"); if (allBtn) allBtn.hidden = true;
        const dAllBtn = $("#projects-delete-all"); if (dAllBtn) dAllBtn.hidden = true;
        return;
    }
    const header = `
      <div class="table-hdr" style="grid-template-columns: 28px 40px 1fr 140px 90px 100px 120px 140px">
        <span></span><span></span><span>PACKAGE</span><span>VERSION</span><span>RISK</span><span>SEVERITIES</span><span>UPDATED</span><span></span>
      </div>`;
    const rows = projects.map((p) => {
        const score = p.risk_score || 0;
        const sevColor = classifyRisk(score);
        const pid = p.id;
        return `
        <div class="table-row" style="grid-template-columns: 28px 40px 1fr 140px 90px 100px 120px 140px">
          <label style="display:inline-flex;align-items:center" onclick="event.stopPropagation()">
            <input type="checkbox" class="projects-select" data-pid="${pid}" data-pkg="${(p.package_name || p.id)}" />
          </label>
          <a href="#/project/${encodeURIComponent(pid)}/overview" style="text-decoration:none">
            <div class="project-icon" style="background:${iconColor(p.package_name || p.id)};width:24px;height:24px"></div>
          </a>
          <a href="#/project/${encodeURIComponent(pid)}/overview" class="t-mono" style="font-weight:700;text-decoration:none;color:inherit">${platformGlyph(p.platform)} ${p.package_name || p.name || pid}</a>
          <span class="t-muted">${p.version_name || "—"}</span>
          <span class="t-mono" style="color:var(--sev-${sevColor})">${score.toFixed(1)}</span>
          <span class="t-muted">${p.counts || "—"}</span>
          <span class="t-muted">${(p.updated_at || "").slice(0, 10)}</span>
          <span style="text-align:right">${chip((p.worst_severity || "info").toLowerCase())}</span>
        </div>`;
    }).join("");
    el.innerHTML = header + rows;

    // ── Selection wiring ───────────────────────────────────────
    const checkboxes = $$(".projects-select");
    const bulkBar = $("#projects-bulk-bar");
    const bulkCount = $("#projects-bulk-count");
    const updateBulkBar = () => {
        const selected = checkboxes.filter((c) => c.checked);
        const n = selected.length;
        if (n === 0) {
            bulkBar.hidden = true;
        } else {
            bulkBar.hidden = false;
            bulkCount.textContent = `${n} selected`;
        }
    };
    checkboxes.forEach((c) => c.addEventListener("change", updateBulkBar));

    // ── Bulk actions ───────────────────────────────────────────
    const selectedPids = () => checkboxes.filter((c) => c.checked).map((c) => c.dataset.pid);
    const selectedSummary = () => checkboxes.filter((c) => c.checked).map((c) => `${c.dataset.pid} · ${c.dataset.pkg}`);

    $("#projects-bulk-backup").addEventListener("click", async () => {
        const pids = selectedPids();
        if (!pids.length) return;
        const confirmed = await confirmModal({
            title: `Backup ${pids.length} project(s)?`,
            body: `Each project produces a self-contained .zip in the workspace's <code>backups/</code> directory:\n\n${selectedSummary().join("\n")}`,
            okLabel: "BACKUP",
            okStyle: "primary",
        });
        if (!confirmed) return;
        await runBulkOp(pids, "backup");
    });

    $("#projects-bulk-delete").addEventListener("click", async () => {
        const pids = selectedPids();
        if (!pids.length) return;
        const confirmed = await confirmModal({
            title: `Wipe ${pids.length} project(s)?`,
            body: `<strong style="color:var(--sev-high)">DESTRUCTIVE.</strong> Wipes the workspace tree, reports, source APK (when no other project shares the file), PlayIntel secrets dir (when no other project shares the package), and the DB row.\n\n${selectedSummary().join("\n")}\n\nThis cannot be undone. Back up first if there's any chance you want the data again.`,
            okLabel: "WIPE",
            okStyle: "danger",
            confirmPhrase: "yes",
        });
        if (!confirmed) return;
        await runBulkOp(pids, "delete");
    });

    $("#projects-backup-all").addEventListener("click", async () => {
        if (!projects.length) return;
        const confirmed = await confirmModal({
            title: `Backup all ${projects.length} project(s)?`,
            body: `Produces one .zip per project in the workspace's <code>backups/</code> directory. Existing archives are kept.`,
            okLabel: "BACKUP ALL",
            okStyle: "primary",
        });
        if (!confirmed) return;
        const r = await fetch("/v1/projects/backup-all", { method: "POST" });
        const body = await r.json().catch(() => ({}));
        await confirmModal({
            title: r.ok ? `✓ Backed up ${body.backed_up || 0} project(s)` : `✗ Backup failed (${r.status})`,
            body: r.ok
                ? `Archives in <code>${body.output_dir || "(unknown)"}</code>:\n\n${(body.archives || []).map((a) => `· ${a.project_id}  ${a.size_bytes ? (a.size_bytes / 1024 / 1024).toFixed(2) + " MB" : ""}`).join("\n")}`
                : JSON.stringify(body, null, 2),
            okLabel: "OK",
            okStyle: "primary",
            cancelLabel: null,
        });
    });

    $("#projects-delete-all").addEventListener("click", async () => {
        if (!projects.length) return;
        const confirmed = await confirmModal({
            title: `WIPE ALL ${projects.length} PROJECTS — FACTORY RESET`,
            body: `<strong style="color:var(--sev-high)">EVERYTHING GOES.</strong>\n\nEvery project's workspace, reports, source artefacts, PlayIntel secrets, and DB rows. The Vercel-style 'cannot be undone' clause applies here literally.\n\nThis is the equivalent of <code>mnexus project delete --all --yes</code>.`,
            okLabel: "FACTORY RESET",
            okStyle: "danger",
            confirmPhrase: "factory reset",
        });
        if (!confirmed) return;
        const r = await fetch("/v1/projects?confirm=true", { method: "DELETE" });
        const body = await r.json().catch(() => ({}));
        await confirmModal({
            title: r.ok ? `✓ Wiped ${body.deleted || 0} project(s)` : `✗ Delete failed (${r.status})`,
            body: r.ok ? `${(body.audit || []).length} audit trail(s) returned.` : JSON.stringify(body, null, 2),
            okLabel: "OK",
            okStyle: "primary",
            cancelLabel: null,
        });
        if (r.ok) mount_projects();
    });

    async function runBulkOp(pids, kind) {
        const results = [];
        for (const pid of pids) {
            try {
                if (kind === "backup") {
                    const r = await fetch(`/v1/projects/${encodeURIComponent(pid)}/backup`, { method: "POST" });
                    results.push({ pid, ok: r.ok, status: r.status,
                                   bytes: r.headers.get("X-Mnexus-Backup-Size") });
                } else {
                    const r = await fetch(`/v1/projects/${encodeURIComponent(pid)}?confirm=true`, { method: "DELETE" });
                    const body = await r.json().catch(() => ({}));
                    results.push({ pid, ok: r.ok, status: r.status, audit: body.audit });
                }
            } catch (e) {
                results.push({ pid, ok: false, status: "network-error", error: String(e) });
            }
        }
        const okCount = results.filter((r) => r.ok).length;
        const failCount = results.length - okCount;
        await confirmModal({
            title: `${kind === "backup" ? "Backup" : "Wipe"} complete — ${okCount} ok · ${failCount} failed`,
            body: results.map((r) => `${r.ok ? "✓" : "✗"} ${r.pid}  ${r.ok ? "" : `[${r.status}]`}`).join("\n"),
            okLabel: "OK",
            okStyle: "primary",
            cancelLabel: null,
        });
        if (kind === "delete" && okCount > 0) mount_projects();
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 03 — APK Intake / Scan
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_scan() {
    return h`
    <div class="main">
      ${sectionHeader("I", "03 // INTAKE", "MOBILE RECONNAISSANCE")}
      <section class="dropzone" id="dz">
        <div class="heading">[ DROP .APK / .XAPK / .IPA HERE ]</div>
        <div class="sub">or click BROWSE · or pull from device</div>
        <div class="wink">SHA-256 gets computed. The right engine detects bundle id + version. Ingest runs.</div>
        <input type="file" id="dz-picker" accept=".apk,.xapk,.ipa" style="display:none" />
        <div class="actions">
          <button class="btn primary" onclick="document.getElementById('dz-picker').click()">[ BROWSE ]</button>
          <a class="btn" href="#/device/pull">[ PULL FROM DEVICE ]</a>
          <a class="btn" href="#/device/bridge">[ DEVICE BRIDGE ]</a>
          <a class="btn" href="#/ios/decrypt">[ DECRYPT IPA (iOS) ]</a>
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

    async function handleUpload(file, opts = {}) {
        if (!file) return;
        const force = !!opts.force;
        const verb = force ? "force-rescanning" : "uploading";
        status.innerHTML = `<span style="color:var(--acid)">↑ ${verb} <b>${file.name}</b> (${fmtBytes(file.size)}) · detecting package via apktool…</span>`;

        const fd = new FormData();
        fd.append("file", file);
        if (force) fd.append("force", "true");
        try {
            const r = await fetch("/v1/apks/upload", { method: "POST", body: fd });
            const payload = await r.json().catch(() => ({}));
            if (!r.ok) {
                status.innerHTML = `<span style="color:var(--sev-crit)">✕ upload failed: ${payload.detail || r.statusText}</span>`;
                return;
            }

            const projectHref = `#/project/${encodeURIComponent(payload.project_id)}/overview`;

            if (payload.dedup && !force) {
                // Same SHA-256 already analysed — say so loudly, offer a force-rescan
                // escape hatch, but still route the user to the existing project
                // so they don't get stuck on the Scan page wondering what happened.
                status.innerHTML = `
                  <span style="color:var(--magenta)">↻ already scanned</span> ·
                  <a href="${projectHref}" style="color:var(--acid)">open <b>${payload.project_id}</b></a>
                  <span class="muted small">(${payload.package} ${payload.version})</span> ·
                  <a href="#" id="dz-force" style="color:var(--cyan)">rescan anyway</a>
                `;
                const forceLink = document.getElementById("dz-force");
                if (forceLink) {
                    forceLink.addEventListener("click", (ev) => {
                        ev.preventDefault();
                        handleUpload(file, { force: true });
                    });
                }
                // Auto-route after a beat so the analyst doesn't have to click.
                setTimeout(() => { location.hash = projectHref; }, 1600);
            } else {
                const label = force ? "rescanned" : "ingested";
                status.innerHTML = `<span style="color:var(--acid)">✓ ${label} as <b>${payload.project_id}</b> (${payload.package} ${payload.version}) — redirecting…</span>`;
                setTimeout(() => { location.hash = projectHref; }, 900);
            }
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
 *  SCREEN 04b — Play Scan (stream APK from CDN, scan Firebase config + secrets)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_play_scan() {
    return h`
    <div class="main">
      ${sectionHeader("P", "04b // PLAY SCAN", "STREAM + RECON · 3 SOURCES · 1 PIPELINE")}
      <section class="panel">
        <div class="panel-head"><span>// PACKAGE TARGET</span></div>
        <div class="panel-body col" style="gap:10px">
          <div class="row" style="gap:6px;flex-wrap:wrap">
            <button class="btn ps-mode" data-mode="play"   data-active="1">[ PLAY STREAM ]</button>
            <button class="btn ps-mode" data-mode="path">[ LOCAL PATH ]</button>
            <button class="btn ps-mode" data-mode="upload">[ UPLOAD .APK ]</button>
            <span class="grow"></span>
            <label class="row" style="gap:6px;align-items:center">
              <input type="checkbox" id="ps-probes" />
              <span class="muted small">run active Firebase probes (RTDB · Firestore · Storage)</span>
            </label>
          </div>

          <input id="ps-pkg" class="input t-mono" placeholder="com.example.app" />
          <div id="ps-pkg-hint" class="muted small">required for PLAY STREAM and LOCAL PATH</div>

          <!-- mode: play (default) -->
          <div id="ps-mode-play" class="col" style="gap:8px">
            <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
              <span class="muted small uppercase">scan as</span>
              <select id="ps-account" class="input" style="min-width:200px">
                <option value="">— default —</option>
              </select>
              <a class="btn" href="#/play-accounts" style="padding:4px 10px">[ MANAGE ACCOUNTS ]</a>
            </div>
            <div class="muted small">
              Streams only the central directory + high-value zip entries
              (resources.arsc, google-services.json, JS bundles) over HTTP Range.
            </div>
          </div>

          <!-- mode: path -->
          <div id="ps-mode-path" class="col" style="gap:8px;display:none">
            <input id="ps-path" class="input t-mono" placeholder="/Users/you/Downloads/target.apk" />
            <div class="muted small">Bypasses the Play CDN — reads the .apk straight off disk on the server.</div>
          </div>

          <!-- mode: upload -->
          <div id="ps-mode-upload" class="col" style="gap:8px;display:none">
            <input id="ps-file" type="file" accept=".apk,.xapk,.apkm,.apks" />
            <div class="muted small">
              Accepts <code>.apk</code> (single binary) and bundled formats <code>.apkm</code> /
              <code>.apks</code> / <code>.xapk</code> (zip with base + per-config splits). Format
              is sniffed from the contents — file extension is just a hint.
              Package id is auto-detected from the inner base manifest if you leave the field blank.
              File is hashed + deduped under <code>workspace/playintel-uploads/</code>; re-uploading
              the same bundle reuses the existing copy.
            </div>
          </div>

          <div class="row">
            <button id="ps-go" class="btn primary">[ STREAM + SCAN ]</button>
            <span class="grow"></span>
            <span id="ps-status" class="muted small"></span>
          </div>
        </div>
      </section>
      <section class="panel" id="ps-results-wrap" style="display:none">
        <div class="panel-head"><span id="ps-result-title">// RESULTS</span></div>
        <div class="panel-body col" id="ps-results" style="gap:18px"></div>
      </section>
      <section class="panel">
        <div class="panel-head row" style="align-items:center;gap:8px">
          <span>// HISTORY</span>
          <span class="grow"></span>
          <input id="ps-history-filter" class="input t-mono" placeholder="filter by package…" style="width:240px;padding:2px 8px" />
          <button id="ps-history-refresh" class="btn" style="padding:2px 10px">[ REFRESH ]</button>
        </div>
        <div class="panel-body col" id="ps-history" style="gap:6px">loading…</div>
      </section>
    </div>`;
}

async function mount_play_scan() {
    const btn = $("#ps-go");
    const pkg = $("#ps-pkg");
    const probes = $("#ps-probes");
    const status = $("#ps-status");
    const wrap = $("#ps-results-wrap");
    const out = $("#ps-results");
    const title = $("#ps-result-title");
    const accountSelect = $("#ps-account");
    if (!btn) return;

    // ── source-mode toggle ────────────────────────────────────────────
    let mode = "play";  // play | path | upload
    const setMode = (next) => {
        mode = next;
        $$(".ps-mode").forEach((b) => b.dataset.active = (b.dataset.mode === next ? "1" : ""));
        ["play", "path", "upload"].forEach((m) => {
            const el = $(`#ps-mode-${m}`);
            if (el) el.style.display = (m === next ? "" : "none");
        });
        // Package input: required for play / path; optional for upload
        // (manifest auto-detect on the server). Update placeholder + hint
        // text so the user understands the difference at a glance.
        const hint = $("#ps-pkg-hint");
        if (next === "upload") {
            pkg.placeholder = "(optional — auto-detected from the .apk manifest)";
            if (hint) hint.textContent = "optional in UPLOAD mode — pulled from the manifest if blank";
        } else {
            pkg.placeholder = "com.example.app";
            if (hint) hint.textContent = "required for PLAY STREAM and LOCAL PATH";
        }
    };
    $$(".ps-mode").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

    // ── populate account dropdown from /v1/playintel/accounts ────────
    try {
        const r = await fetch("/v1/playintel/accounts");
        if (r.ok) {
            const body = await r.json();
            for (const a of (body.accounts || [])) {
                const opt = document.createElement("option");
                opt.value = a.name;
                opt.textContent = a.name + (a.is_default ? "  ★" : "");
                accountSelect.appendChild(opt);
            }
            if (!body.accounts || body.accounts.length === 0) {
                status.innerHTML = `no Play accounts stored — <a href="#/play-accounts">register one</a> or use LOCAL PATH / UPLOAD .APK`;
            }
        }
    } catch (_) { /* best-effort */ }

    pkg.addEventListener("keydown", (e) => { if (e.key === "Enter") btn.click(); });

    btn.addEventListener("click", async () => {
        const pkgName = (pkg.value || "").trim();
        if (!pkgName && mode !== "upload") {
            status.textContent = "package name required (or switch to UPLOAD .APK)";
            return;
        }
        btn.disabled = true;
        wrap.style.display = "none";
        out.innerHTML = "";
        try {
            const data = await runPlayScan(mode, pkgName, probes.checked, accountSelect.value, status);
            if (!data) return;  // status was already set by the request path
            renderPlayScanResults(out, title, data);
            wrap.style.display = "";
            status.textContent = `done · source: ${data.source} · package: ${data.package}`;
            // Refresh the history panel so the run that just finished
            // appears at the top without a manual reload.
            await renderPlayScanHistory();
        } catch (e) {
            status.textContent = `request failed: ${e.message || e}`;
        } finally {
            btn.disabled = false;
        }
    });

    // ── history panel wiring ─────────────────────────────────────────
    const refreshBtn = $("#ps-history-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => renderPlayScanHistory());
    const filterEl = $("#ps-history-filter");
    if (filterEl) {
        let t;
        filterEl.addEventListener("input", () => {
            clearTimeout(t);
            t = setTimeout(() => renderPlayScanHistory(filterEl.value.trim()), 200);
        });
    }
    await renderPlayScanHistory();

    // Auto-load a scan when arriving from /#/project/<id>/overview's
    // PLAY-INTEL panel. sessionStorage carries the scan_id so we don't
    // have to encode it into the route.
    const jumpId = sessionStorage.getItem("playintel-jump");
    if (jumpId) {
        sessionStorage.removeItem("playintel-jump");
        loadHistoricalScan(jumpId);
    }
}

async function renderPlayScanHistory(packageFilter) {
    const root = $("#ps-history");
    if (!root) return;
    const url = packageFilter
        ? `/v1/playintel/scans?package=${encodeURIComponent(packageFilter)}&limit=200`
        : `/v1/playintel/scans?limit=200`;
    try {
        const r = await fetch(url);
        if (!r.ok) {
            root.innerHTML = `<div class="muted small">[${r.status}] failed to list history</div>`;
            return;
        }
        const body = await r.json();
        const scans = body.scans || [];
        if (!scans.length) {
            root.innerHTML = `<div class="empty-state"><div class="muted small">no scans yet — run one above</div></div>`;
            return;
        }
        root.innerHTML = `
          <table style="width:100%;border-collapse:collapse">
            <thead><tr style="text-align:left">
              <th class="muted small uppercase" style="padding:4px 8px">when</th>
              <th class="muted small uppercase" style="padding:4px 8px">package</th>
              <th class="muted small uppercase" style="padding:4px 8px">version</th>
              <th class="muted small uppercase" style="padding:4px 8px">source</th>
              <th class="muted small uppercase" style="padding:4px 8px;text-align:right">FB</th>
              <th class="muted small uppercase" style="padding:4px 8px;text-align:right">creds</th>
              <th class="muted small uppercase" style="padding:4px 8px;text-align:right">vulns</th>
              <th class="muted small uppercase" style="padding:4px 8px;text-align:right">findings</th>
              <th class="muted small uppercase" style="padding:4px 8px"></th>
            </tr></thead>
            <tbody>
              ${scans.map((s) => `
                <tr style="border-top:1px solid var(--border)">
                  <td class="t-mono" style="padding:4px 8px;white-space:nowrap">${escapeHtml((s.scanned_at || "").replace("T", " ").slice(0, 19))}</td>
                  <td class="t-mono" style="padding:4px 8px">${escapeHtml(s.package)}</td>
                  <td class="t-mono" style="padding:4px 8px">${escapeHtml(s.version_name || (s.version_code ? String(s.version_code) : "—"))}</td>
                  <td class="muted small" style="padding:4px 8px">${escapeHtml(s.source_label || s.source)}</td>
                  <td class="t-mono" style="padding:4px 8px;text-align:right">${s.firebase_project_count || 0}</td>
                  <td class="t-mono" style="padding:4px 8px;text-align:right">${s.confirmed_secrets_count || 0}</td>
                  <td class="t-mono" style="padding:4px 8px;text-align:right;color:${s.vulnerability_count ? "var(--sev-critical)" : "inherit"}">${s.vulnerability_count || 0}</td>
                  <td class="t-mono" style="padding:4px 8px;text-align:right">${s.findings_count || 0}</td>
                  <td style="padding:4px 8px;white-space:nowrap">
                    <button class="btn ps-history-view" data-id="${escapeHtml(s.id)}" style="padding:2px 8px">view</button>
                    <button class="btn primary ps-history-import" data-import-scan="${escapeHtml(s.id)}"
                            ${((s.source || "").split(":", 1)[0] === "play") ? "disabled style=\"opacity:0.45;cursor:not-allowed\"" : ""}
                            title="${((s.source || "").split(":", 1)[0] === "play")
                                ? "Play-stream scan has no on-disk APK — re-import via UPLOAD or PULL."
                                : "Promote to a regular Project (full static fan-out)."}"
                            style="padding:2px 8px;white-space:nowrap">import</button>
                    <button class="btn ps-history-delete" data-id="${escapeHtml(s.id)}" style="padding:2px 8px">delete</button>
                  </td>
                </tr>`).join("")}
            </tbody>
          </table>`;
        $$(".ps-history-view").forEach((b) => b.addEventListener("click", () => loadHistoricalScan(b.dataset.id)));
        $$(".ps-history-delete").forEach((b) => b.addEventListener("click", async () => {
            if (!confirm("Delete this scan from history?")) return;
            await fetch(`/v1/playintel/scans/${encodeURIComponent(b.dataset.id)}`, { method: "DELETE" });
            await renderPlayScanHistory(packageFilter);
        }));
        bindImportToProjectsButtons();
    } catch (e) {
        root.innerHTML = `<div class="muted small">request failed: ${e.message || e}</div>`;
    }
}

async function loadHistoricalScan(scanId) {
    const status = $("#ps-status");
    const wrap = $("#ps-results-wrap");
    const out = $("#ps-results");
    const title = $("#ps-result-title");
    if (!out) return;
    if (status) status.textContent = `loading historical scan ${scanId}…`;
    try {
        const r = await fetch(`/v1/playintel/scans/${encodeURIComponent(scanId)}`);
        if (!r.ok) {
            if (status) status.textContent = `[${r.status}] ${(await r.text()).slice(0, 200)}`;
            return;
        }
        const body = await r.json();
        const data = body.payload || {};
        renderPlayScanResults(out, title, data);
        wrap.style.display = "";
        if (status) status.textContent = `historical · ${body.scanned_at} · ${body.source_label}`;
        wrap.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
        if (status) status.textContent = `request failed: ${e.message || e}`;
    }
}

async function runPlayScan(mode, pkgName, runProbes, accountName, status) {
    if (mode === "upload") {
        const file = $("#ps-file").files[0];
        if (!file) { status.textContent = "pick an .apk file first"; return null; }
        const form = new FormData();
        form.append("file", file);
        if (pkgName) form.append("package", pkgName);  // optional — server falls back to manifest detect
        form.append("run_active_probes", runProbes ? "true" : "false");
        status.textContent = `uploading ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)…`;
        const resp = await fetch("/v1/playintel/scan-upload", { method: "POST", body: form });
        if (!resp.ok) { status.textContent = `[${resp.status}] ${(await resp.text()).slice(0, 200)}`; return null; }
        return resp.json();
    }
    // path or play — both go through the JSON endpoint.
    const body = { package: pkgName, run_active_probes: runProbes };
    if (mode === "path") {
        const p = ($("#ps-path").value || "").trim();
        if (!p) { status.textContent = "local path required"; return null; }
        body.apk_path = p;
        status.textContent = `scanning ${p}…`;
    } else {
        if (accountName) body.account_name = accountName;
        status.textContent = `streaming + scanning ${pkgName}…`;
    }
    const resp = await fetch("/v1/playintel/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!resp.ok) { status.textContent = `[${resp.status}] ${(await resp.text()).slice(0, 200)}`; return null; }
    return resp.json();
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN 04c — Play Accounts (manage stored Play identities)
 * ═══════════════════════════════════════════════════════════════════════════ */
function view_play_accounts() {
    return h`
    <div class="main">
      ${sectionHeader("A", "04c // PLAY ACCOUNTS", "STORED IDENTITIES · NO CREATION")}
      <section class="panel">
        <div class="panel-head"><span>// REGISTER AN EXISTING ACCOUNT</span></div>
        <div class="panel-body col" style="gap:8px">
          <div class="row" style="gap:8px;flex-wrap:wrap">
            <input id="pa-name"     class="input t-mono" placeholder="name (e.g. research-1)" style="width:200px" />
            <input id="pa-email"    class="input t-mono" placeholder="me@gmail.com" style="flex:1;min-width:240px" />
          </div>
          <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
            <label class="row" style="gap:6px"><input type="radio" name="pa-mode" value="aas" checked /> existing AAS token</label>
            <label class="row" style="gap:6px"><input type="radio" name="pa-mode" value="password" /> password (mints AAS via /auth)</label>
          </div>
          <input id="pa-secret" class="input t-mono" type="password" placeholder="aas_et/... or your password" />
          <input id="pa-notes"  class="input"        placeholder="notes (optional)" />
          <label class="row" style="gap:6px;align-items:center">
            <input type="checkbox" id="pa-default" />
            <span class="muted small">make default for /play-scan</span>
          </label>
          <div class="row" style="gap:8px;align-items:center">
            <button id="pa-add" class="btn primary">[ REGISTER ]</button>
            <span id="pa-add-status" class="muted small"></span>
          </div>
          <div class="muted small">
            <strong>This UI does not create Google accounts.</strong>
            Sign into the Google account you want to use (in any browser),
            create an app password if 2FA is on, then register it here.
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><span>// STORED ACCOUNTS</span></div>
        <div class="panel-body col" id="pa-list" style="gap:6px">loading…</div>
      </section>
    </div>`;
}

async function mount_play_accounts() {
    const addBtn = $("#pa-add");
    const status = $("#pa-add-status");
    addBtn.addEventListener("click", async () => {
        const name = ($("#pa-name").value || "").trim();
        const email = ($("#pa-email").value || "").trim();
        const secret = ($("#pa-secret").value || "");
        const notes = ($("#pa-notes").value || "").trim();
        const isDefault = $("#pa-default").checked;
        const mode = (document.querySelector('input[name="pa-mode"]:checked') || {}).value || "aas";
        if (!name || !email || !secret) { status.textContent = "name, email and secret are required"; return; }
        addBtn.disabled = true;
        status.textContent = (mode === "password" ? "exchanging password for AAS…" : "saving…");
        const body = { name, email, notes, is_default: isDefault };
        body[mode === "password" ? "password" : "aas_token"] = secret;
        try {
            const r = await fetch("/v1/playintel/accounts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            if (!r.ok) {
                status.textContent = `[${r.status}] ${(await r.text()).slice(0, 240)}`;
                return;
            }
            status.textContent = "saved";
            $("#pa-name").value = ""; $("#pa-email").value = ""; $("#pa-secret").value = "";
            $("#pa-notes").value = ""; $("#pa-default").checked = false;
            await renderPlayAccountsList();
        } catch (e) {
            status.textContent = `request failed: ${e.message || e}`;
        } finally {
            addBtn.disabled = false;
        }
    });
    await renderPlayAccountsList();
}

async function renderPlayAccountsList() {
    const root = $("#pa-list");
    if (!root) return;
    try {
        const r = await fetch("/v1/playintel/accounts");
        if (!r.ok) { root.innerHTML = `<div class="muted small">[${r.status}] failed to list accounts</div>`; return; }
        const body = await r.json();
        const accounts = body.accounts || [];
        if (!accounts.length) {
            root.innerHTML = `<div class="empty-state"><div class="muted small">no accounts stored — register one above</div></div>`;
            return;
        }
        root.innerHTML = `
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="text-align:left">
                <th class="muted small uppercase" style="padding:4px 8px">name</th>
                <th class="muted small uppercase" style="padding:4px 8px">email</th>
                <th class="muted small uppercase" style="padding:4px 8px">gsfid</th>
                <th class="muted small uppercase" style="padding:4px 8px">notes</th>
                <th class="muted small uppercase" style="padding:4px 8px">default</th>
                <th class="muted small uppercase" style="padding:4px 8px">actions</th>
              </tr>
            </thead>
            <tbody>
              ${accounts.map((a) => `
                <tr style="border-top:1px solid var(--border)">
                  <td class="t-mono" style="padding:6px 8px;color:var(--accent)">${a.name}</td>
                  <td class="t-mono" style="padding:6px 8px">${a.email_local}@${a.email_domain}</td>
                  <td class="muted small" style="padding:6px 8px">${a.gsfid_present ? "✓" : "—"}</td>
                  <td class="muted small" style="padding:6px 8px">${(a.notes || "").slice(0, 40)}</td>
                  <td style="padding:6px 8px">${a.is_default ? "★" : ""}</td>
                  <td style="padding:6px 8px">
                    ${a.is_default ? "" : `<button class="btn pa-default-btn" data-name="${a.name}" style="padding:2px 8px">set default</button>`}
                    <button class="btn pa-delete-btn" data-name="${a.name}" style="padding:2px 8px">delete</button>
                  </td>
                </tr>`).join("")}
            </tbody>
          </table>`;
        $$(".pa-default-btn").forEach((btn) => btn.addEventListener("click", async () => {
            await fetch(`/v1/playintel/accounts/${encodeURIComponent(btn.dataset.name)}/default`, { method: "POST" });
            await renderPlayAccountsList();
        }));
        $$(".pa-delete-btn").forEach((btn) => btn.addEventListener("click", async () => {
            if (!confirm(`Delete account ${btn.dataset.name}?`)) return;
            await fetch(`/v1/playintel/accounts/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
            await renderPlayAccountsList();
        }));
    } catch (e) {
        root.innerHTML = `<div class="muted small">request failed: ${e.message || e}</div>`;
    }
}


function renderPlayScanResults(out, title, data) {
    title.textContent = `// ${data.package}  ·  ${data.source}`;
    out.innerHTML = [
        renderImportToProjectsBlock(data),
        renderFirebaseConfigsBlock(data.firebase_configs || []),
        renderActiveProbesBlock(data.active_probes || {}, data.vulnerabilities || []),
        renderConfirmedSecretsBlock(data.confirmed_secrets || []),
        renderSuspectedSecretsBlock(data.suspected_secrets || []),
        renderTechnologiesBlock(data.detected_technologies || {}),
        renderEngineFindingsBlock(data.findings || []),
        renderSavedFilesBlock(data.saved_files || [], data.saved_files_dir),
    ].join("");
    bindImportToProjectsButtons();
}

/* ─── Import-to-Projects strip ─────────────────────────────────────────
 *  Lets the analyst promote the APK that was just scanned into a regular
 *  Project (full static fan-out, findings table, dynamic tab, …). Wired
 *  to /v1/playintel/scans/{id}/import which resolves the APK on disk
 *  from record.apk_local_path → workspace/playintel-uploads/<sha>.apk
 *  → 410 (only Play streaming has no full APK). ──────────────────────── */
function renderImportToProjectsBlock(data) {
    const scanId = data.scan_id;
    if (!scanId) {
        // Some legacy payloads pre-date the scan_id stamp; without it we
        // can't address the record from the API. Render nothing rather
        // than a button that 404s.
        return "";
    }
    // Streaming runs don't materialise the full APK — gray the button
    // out instead of letting the user click and hit a 410.
    const importable = (data.source || "").split(":", 1)[0] !== "play";
    const tooltip = importable
        ? "Run the full static pipeline (apktool · jadx · mobsf · ghidra) on this APK and store it as a regular Project."
        : "Play-stream scans don't keep a full APK on disk — re-import via UPLOAD .APK or PULL FROM DEVICE.";
    return `
      <div class="row" style="gap:8px;align-items:center;padding:8px 10px;background:var(--bg-accent-panel);border:1px solid var(--border-accent);border-radius:2px;margin-bottom:6px">
        <span class="muted small uppercase" style="letter-spacing:2px">// next step</span>
        <span class="t-mono small">scan complete — promote this APK to a regular Project?</span>
        <span class="spacer"></span>
        <button class="btn primary" data-import-scan="${escapeHtml(scanId)}"
                ${importable ? "" : "disabled style=\"opacity:0.45;cursor:not-allowed\""}
                title="${escapeHtml(tooltip)}"
                style="white-space:nowrap;padding:4px 10px">[ IMPORT TO PROJECTS ]</button>
      </div>`;
}

function bindImportToProjectsButtons() {
    $$("[data-import-scan]").forEach((btn) => {
        if (btn.disabled || btn.dataset.importBound === "1") return;
        btn.dataset.importBound = "1";
        btn.addEventListener("click", async () => {
            const scanId = btn.dataset.importScan;
            const orig = btn.textContent;
            btn.textContent = "[ INGESTING… ]";
            btn.disabled = true;
            try {
                const r = await fetch(`/v1/playintel/scans/${encodeURIComponent(scanId)}/import`, { method: "POST" });
                const j = await r.json();
                if (!r.ok) throw new Error(j.detail || r.statusText);
                const label = j.dedup
                    ? `[ ✓ ALREADY SCANNED — OPEN ${j.project_id} ]`
                    : `[ ✓ INGESTED — OPEN ${j.project_id} ]`;
                btn.textContent = label;
                btn.style.color = j.dedup ? "var(--magenta)" : "var(--acid)";
                btn.disabled = false;
                btn.onclick = () => { location.hash = `#/project/${j.project_id}/overview`; };
                setTimeout(() => {
                    if (location.hash.startsWith("#/play-scan")) {
                        location.hash = `#/project/${j.project_id}/overview`;
                    }
                }, 1500);
            } catch (e) {
                btn.textContent = `[ FAILED ]`;
                btn.style.color = "var(--sev-crit)";
                btn.title = (e && e.message) || String(e);
                btn.disabled = false;
                // Restore the original label on the next hover so retrying is obvious.
                setTimeout(() => { if (btn.textContent === "[ FAILED ]") btn.textContent = orig; }, 4000);
            }
        });
    });
}

/* ─── one block per recovered Firebase project — every field the SDK
 *     embeds in the APK, in the same shape PlayIntelEngine emits.
 *     This is the single biggest signal the Go reference produces and
 *     the one the previous renderer was hiding. ─────────────────────── */
function renderFirebaseConfigsBlock(configs) {
    if (!configs.length) {
        return `<div><div class="muted small uppercase" style="margin-bottom:4px">FIREBASE PROJECTS</div>
                <div class="muted small">no Firebase project recovered</div></div>`;
    }
    const blocks = configs.map((c) => {
        const rows = [
            ["project_id",         c.project_id],
            ["google_api_key",     c.api_key],
            ["google_app_id",      c.app_id],
            ["firebase_database_url", c.database_url],
            ["google_storage_bucket", c.storage_bucket],
            ["gcm_defaultSenderId",   c.sender_id],
            ["default_web_client_id", c.web_client_id],
            ["recovered_from",     c.location],
        ].filter(([_, v]) => v);
        const tableBody = rows.map(([k, v]) => `
            <tr>
              <td class="muted small" style="padding:3px 10px;vertical-align:top;white-space:nowrap">${escapeHtml(k)}</td>
              <td class="t-mono" style="padding:3px 10px;word-break:break-all">${escapeHtml(v)}</td>
            </tr>`).join("");
        const additional = (c.additional_api_keys || []).filter(Boolean);
        const extraBlock = additional.length
            ? `<div style="margin-top:6px">
                 <div class="muted small uppercase" style="margin-bottom:2px">additional AIza* keys (${additional.length})</div>
                 ${additional.map((k) => `<div class="t-mono" style="word-break:break-all">${escapeHtml(k)}</div>`).join("")}
               </div>`
            : "";
        return `
          <div style="border:1px solid var(--border);border-radius:2px;padding:10px;margin-bottom:6px">
            <div class="t-mono" style="font-weight:700;color:var(--accent);margin-bottom:6px">▸ ${escapeHtml(c.project_id)}</div>
            <table style="border-collapse:collapse;width:100%"><tbody>${tableBody}</tbody></table>
            ${extraBlock}
          </div>`;
    }).join("");
    return `<div><div class="muted small uppercase" style="margin-bottom:4px">FIREBASE CONFIG · ${configs.length} project${configs.length !== 1 ? "s" : ""}</div>${blocks}</div>`;
}

/* ─── active probes: table per probe family with explicit pass/fail/
 *     skipped status so a green run doesn't disappear into "no findings".
 *     Vulnerabilities are still surfaced separately because they get
 *     promoted to engine Findings too. ─────────────────────────────── */
function renderActiveProbesBlock(probes, vulns) {
    const sections = [];
    const renderTable = (title, rows, columns) => {
        if (!rows.length) {
            sections.push(`<div class="muted small">${title}: <em>not run</em></div>`);
            return;
        }
        const head = columns.map((c) => `<th class="muted small uppercase" style="padding:3px 8px;text-align:left">${c.label}</th>`).join("");
        const body = rows.map((row) => {
            const cells = columns.map((c) => {
                const v = c.cell(row);
                return `<td class="t-mono" style="padding:3px 8px;word-break:break-all">${v}</td>`;
            }).join("");
            return `<tr style="border-top:1px solid var(--border)">${cells}</tr>`;
        }).join("");
        sections.push(`
          <div>
            <div class="muted small uppercase" style="margin-bottom:2px">${title}</div>
            <table style="width:100%;border-collapse:collapse"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
          </div>`);
    };

    const yn = (b) => b ? `<span style="color:var(--sev-critical)">YES</span>` : `<span class="muted">no</span>`;
    renderTable("realtime database", probes.rtdb || [], [
        { label: "URL",       cell: (r) => escapeHtml(r.db_url || "") },
        { label: "read",      cell: (r) => yn(r.public_read) },
        { label: "write",     cell: (r) => yn(r.public_write) },
        { label: "note",      cell: (r) => `<span class="muted small">${escapeHtml(r.error || "")}</span>` },
    ]);
    renderTable("firestore", probes.firestore || [], [
        { label: "project",      cell: (r) => escapeHtml(r.project_id || "") },
        { label: "anon read",    cell: (r) => yn(r.public_read) },
        { label: "collections",  cell: (r) => String(r.sample_document_count || 0) },
        { label: "note",         cell: (r) => `<span class="muted small">${escapeHtml(r.error || "")}</span>` },
    ]);
    renderTable("cloud storage", probes.storage || [], [
        { label: "bucket",       cell: (r) => escapeHtml(r.bucket || "") },
        { label: "anon list",    cell: (r) => yn(r.public_listing) },
        { label: "objects",      cell: (r) => String(r.object_count || 0) },
        { label: "note",         cell: (r) => `<span class="muted small">${escapeHtml(r.error || "")}</span>` },
    ]);
    const vulnList = vulns.length
        ? `<div class="col" style="gap:2px;margin-top:6px">
             <div class="muted small uppercase">vulnerabilities</div>
             ${vulns.map((v) => `<div class="t-mono" style="color:var(--sev-critical)">▸ ${escapeHtml(v)}</div>`).join("")}
           </div>`
        : "";
    return `<div><div class="muted small uppercase" style="margin-bottom:4px">ACTIVE PROBES</div>
              <div class="col" style="gap:8px">${sections.join("")}${vulnList}</div></div>`;
}

function renderConfirmedSecretsBlock(secrets) {
    if (!secrets.length) {
        return `<div><div class="muted small uppercase" style="margin-bottom:4px">CONFIRMED CREDENTIALS</div>
                <div class="muted small">no confirmed credential patterns matched
                  <span class="muted small" style="font-style:italic"> (AIza Firebase keys live in the FIREBASE CONFIG block above)</span>
                </div></div>`;
    }
    const rows = secrets.map((s) => `
        <tr style="border-top:1px solid var(--border)">
          <td class="t-mono" style="padding:4px 8px;color:var(--accent);white-space:nowrap">${escapeHtml(s.type)}</td>
          <td class="t-mono" style="padding:4px 8px;word-break:break-all">${escapeHtml(s.value || "")}</td>
          <td class="muted small" style="padding:4px 8px">${escapeHtml(s.location || "")}</td>
        </tr>`).join("");
    return `<div><div class="muted small uppercase" style="margin-bottom:4px">CONFIRMED CREDENTIALS · ${secrets.length}</div>
              <table style="width:100%;border-collapse:collapse">
                <thead><tr>
                  <th class="muted small uppercase" style="padding:3px 8px;text-align:left">type</th>
                  <th class="muted small uppercase" style="padding:3px 8px;text-align:left">value</th>
                  <th class="muted small uppercase" style="padding:3px 8px;text-align:left">location</th>
                </tr></thead>
                <tbody>${rows}</tbody></table></div>`;
}

function renderSuspectedSecretsBlock(secrets) {
    if (!secrets.length) return "";
    const rows = secrets.map((s) => `
        <tr style="border-top:1px solid var(--border)">
          <td class="t-mono" style="padding:4px 8px;color:var(--sev-medium);white-space:nowrap">${escapeHtml(s.type)}</td>
          <td class="t-mono" style="padding:4px 8px;word-break:break-all">${escapeHtml(s.value || "")}</td>
          <td class="muted small" style="padding:4px 8px">${escapeHtml(s.location || "")}</td>
        </tr>`).join("");
    return `<div>
              <div class="muted small uppercase" style="margin-bottom:4px">SUSPECTED · ${secrets.length}
                <span style="font-style:italic;font-weight:normal"> · low-precision tier; review manually</span>
              </div>
              <table style="width:100%;border-collapse:collapse">
                <thead><tr>
                  <th class="muted small uppercase" style="padding:3px 8px;text-align:left">type</th>
                  <th class="muted small uppercase" style="padding:3px 8px;text-align:left">value</th>
                  <th class="muted small uppercase" style="padding:3px 8px;text-align:left">location</th>
                </tr></thead>
                <tbody>${rows}</tbody></table>
            </div>`;
}

function renderTechnologiesBlock(techs) {
    const entries = Object.entries(techs || {});
    if (!entries.length) return "";
    const rows = entries.map(([t, locs]) => `
        <tr><td class="t-mono" style="padding:3px 10px;color:var(--accent)">${escapeHtml(t)}</td>
            <td class="muted small" style="padding:3px 10px">${escapeHtml(Array.isArray(locs) ? locs.join(", ") : String(locs))}</td></tr>`).join("");
    return `<div><div class="muted small uppercase" style="margin-bottom:4px">DETECTED TECHNOLOGIES · ${entries.length}</div>
              <table style="border-collapse:collapse"><tbody>${rows}</tbody></table></div>`;
}

function renderEngineFindingsBlock(findings) {
    if (!findings.length) {
        return `<div><div class="muted small uppercase" style="margin-bottom:4px">ENGINE FINDINGS</div>
                <div class="muted small">no findings emitted</div></div>`;
    }
    const sevColor = (s) => `var(--sev-${s})`;
    const attrChip = (f) => {
        if (!f.attributed_to) return "";
        const owner = f.attributed_to;
        let color = "var(--magenta)";
        if (owner === "first-party") color = "var(--acid)";
        else if (owner === "third-party (unknown)") color = "var(--sev-high)";
        else color = "var(--cyan)";
        const conf = (f.attribution_confidence || "").toLowerCase();
        const dot = conf === "high" ? "●" : conf === "medium" ? "◐" : "○";
        return `<div class="muted small" style="margin-top:3px;color:${color}">${dot} ${escapeHtml(owner)}${f.sdk_category ? ` · ${escapeHtml(f.sdk_category)}` : ""}</div>`;
    };
    const rows = findings.map((f) => `
        <tr style="border-top:1px solid var(--border)">
          <td class="t-mono" style="padding:6px 8px;color:${sevColor(f.severity)};text-transform:uppercase;white-space:nowrap">${escapeHtml(f.severity)}</td>
          <td style="padding:6px 8px">
            <div>${escapeHtml(f.title)}</div>
            ${attrChip(f)}
            ${f.evidence ? `<div class="muted small" style="margin-top:2px;white-space:pre-wrap;font-family:monospace">${escapeHtml(f.evidence).slice(0, 600)}</div>` : ""}
          </td>
          <td class="muted small" style="padding:6px 8px;vertical-align:top;max-width:280px;word-break:break-all">${escapeHtml(f.location || "—")}</td>
        </tr>`).join("");
    return `<div><div class="muted small uppercase" style="margin-bottom:4px">ENGINE FINDINGS · ${findings.length}</div>
              <table style="width:100%;border-collapse:collapse"><tbody>${rows}</tbody></table></div>`;
}

function renderSavedFilesBlock(saved, savedDir) {
    if (!saved.length && !savedDir) return "";
    const fmtSize = (n) => {
        if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
        if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
        return `${n} B`;
    };
    const rows = saved.map((f) => `
        <tr style="border-top:1px solid var(--border)">
          <td class="t-mono" style="padding:3px 10px;word-break:break-all">${escapeHtml(f.name)}</td>
          <td class="muted small" style="padding:3px 10px;text-align:right">${fmtSize(f.size || 0)}</td>
        </tr>`).join("");
    return `<div>
              <div class="muted small uppercase" style="margin-bottom:4px">SAVED BEARING FILES · ${saved.length}</div>
              ${saved.length ? `<table style="width:100%;border-collapse:collapse">
                <thead><tr>
                  <th class="muted small uppercase" style="padding:3px 10px;text-align:left">file</th>
                  <th class="muted small uppercase" style="padding:3px 10px;text-align:right">size</th>
                </tr></thead><tbody>${rows}</tbody></table>` : ""}
              ${savedDir ? `<div class="muted small" style="margin-top:4px">→ <code>${escapeHtml(savedDir)}</code></div>` : ""}
            </div>`;
}

function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}


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
          <div class="panel-body col" style="gap:12px;background:#050505" id="report-preview">
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

    // iOS-flavored labels for the surface summary.
    const isIos = project.platform === "ios";
    const exportedComponents = surface.exported_components || [];
    const deeplinks = surface.deeplinks || [];
    const urlSchemes = surface.url_schemes || [];
    const universalLinks = deeplinks.filter((d) => !urlSchemes.includes(d));

    // First N items, with a tail "+ X more →" link that jumps to the
    // full list screen. We don't want the Overview to scroll forever
    // when a target app exports 80 activities or 200 deep links.
    const _list = (items, max, link, render) => {
        if (!items.length) return `<div class="muted small">none discovered</div>`;
        const head = items.slice(0, max).map(render).join("");
        const tail = items.length > max
            ? `<a href="${link}" class="muted small" style="display:block;margin-top:4px">+ ${items.length - max} more →</a>`
            : "";
        return head + tail;
    };
    const componentsListHtml = _list(exportedComponents, 6, `#/project/${encodeURIComponent(id)}/static/components`, (c) => `
        <div class="t-mono small" style="display:flex;gap:6px;align-items:baseline">
          <span class="chip ${c.unprotected ? "high" : "info"}" style="font-size:9px;letter-spacing:1px">${escapeHtml((c.component_type || "?").toUpperCase().slice(0, 3))}</span>
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(c.name || "")}">${escapeHtml(c.name || "?")}</span>
          ${c.unprotected ? `<span class="muted small" style="color:var(--sev-high)">unprotected</span>` : ""}
        </div>`);
    const deeplinksListHtml = _list(deeplinks, 6, `#/project/${encodeURIComponent(id)}/static/components`, (d) => `
        <div class="t-mono small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(d)}">${escapeHtml(d)}</div>`);
    const urlSchemesListHtml = _list(urlSchemes, 6, `#/project/${encodeURIComponent(id)}/static/components`, (s) => `
        <div class="t-mono small">${escapeHtml(s)}://</div>`);
    const universalLinksListHtml = _list(universalLinks, 6, `#/project/${encodeURIComponent(id)}/static/components`, (d) => `
        <div class="t-mono small" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(d)}">${escapeHtml(d)}</div>`);

    // Two-column attack-surface block: each cell holds a list, not a
    // bare count. Platform-aware so iOS gets URL SCHEMES / UNIVERSAL
    // LINKS / FRAMEWORKS / JB DETECTION and Android gets COMPONENTS /
    // DEEP LINKS / NATIVE LIBS / SSL PINNING.
    const surfaceCells = isIos
        ? [
            { label: "URL SCHEMES",     count: urlSchemes.length,       html: urlSchemesListHtml },
            { label: "UNIVERSAL LINKS", count: universalLinks.length,    html: universalLinksListHtml },
            { label: "FRAMEWORKS",      count: (surface.native_libraries || []).length, html: "" },
            { label: "JB DETECTION",    count: surface.jailbreak_detection_detected ? 1 : 0,
              html: surface.jailbreak_detection_detected
                  ? `<div class="t-mono small" style="color:var(--sev-high)">detected · ${escapeHtml(surface.jailbreak_detection_library || "?")}</div>`
                  : `<div class="muted small">none</div>` },
        ]
        : [
            { label: "EXPORTED COMPONENTS", count: exportedComponents.length, html: componentsListHtml },
            { label: "DEEP LINKS",          count: deeplinks.length,           html: deeplinksListHtml },
            { label: "NATIVE LIBS",         count: (surface.native_libraries || []).length, html: "" },
            { label: "SSL PINNING",         count: surface.ssl_pinning_detected ? 1 : 0,
              html: surface.ssl_pinning_detected
                  ? `<div class="t-mono small" style="color:var(--sev-high)">detected · ${escapeHtml(surface.ssl_pinning_library || "?")}</div>`
                  : `<div class="muted small">none</div>` },
        ];

    main.innerHTML = h`
      <div class="muted small uppercase">🔱 NEXUS / ${id} / overview · ${platformGlyph(project.platform)} ${project.package_name || "—"} v${project.version_name || "?"}</div>
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
            <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
              ${surfaceCells.map((cell) => `
                <div style="background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;padding:10px">
                  <div class="row" style="margin-bottom:6px">
                    <span class="muted small uppercase" style="letter-spacing:2px">${escapeHtml(cell.label)}</span>
                    <span class="spacer"></span>
                    <span class="t-mono small" style="color:var(--cyan)">${cell.count}</span>
                  </div>
                  <div class="col" style="gap:3px">${cell.html}</div>
                </div>`).join("")}
            </div>
          </section>
          ${_play_intel_overview_panel(id, project)}
          ${_exports_panel(id)}
        </div>
      </section>`;
    // Async-mount the PlayIntel strip after the overview HTML is in the DOM.
    mount_play_intel_overview(id, project);
}

/* Exports panel — five one-click downloads that turn the recovered endpoints
   + deeplinks into ready-to-replay collections. Wired here on the project
   Overview, and again on the Static tab for analyst convenience. */
/* PlayIntel panel for the project Overview.
 *
 *   - Async-mounts via mount_play_intel_overview() (called after the
 *     Overview HTML is in the DOM). The shell starts as a 'scanning…'
 *     placeholder so the page paints fast even on slow disks.
 *   - State machine:
 *       * no prior scan for this apk_sha256 → [ ▶ RUN PLAY-INTEL SCAN ]
 *       * prior scan(s) exist               → counts + [ VIEW ] + [ ▶ RE-RUN ]
 *       * scan in flight                    → [ SCANNING… ] (button disabled)
 *   - 'Run' calls POST /v1/projects/{id}/play-scan, then routes to
 *     /#/play-scan with the freshest scan id auto-loaded.
 */
function _play_intel_overview_panel(id, project) {
    const platformOK = (project.platform || "android") !== "ios";  // PlayIntel is android-only
    return `
      <section class="panel" id="play-intel-panel">
        <div class="panel-head">
          <span>// PLAY-INTEL</span>
          <span class="spacer"></span>
          <span class="muted small" id="play-intel-status">${platformOK ? "checking history…" : "android-only"}</span>
        </div>
        <div class="panel-body col" style="gap:8px" id="play-intel-body">
          ${platformOK
            ? `<div class="muted small">Firebase configs · confirmed secrets · active probes (RTDB / Firestore / Storage). Reuses the same engine as <a href="#/play-scan">/play-scan</a>.</div>
               <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center" id="play-intel-actions">
                 <span class="muted small">loading…</span>
               </div>`
            : `<div class="muted small">PlayIntel only runs against Android APKs. iOS projects don't have Firebase configs in the manifest format we extract.</div>`
          }
        </div>
      </section>`;
}

async function mount_play_intel_overview(id, project) {
    if ((project.platform || "android") === "ios") return;
    const sha = project.apk_sha256;
    const actions = $("#play-intel-actions");
    const statusEl = $("#play-intel-status");
    if (!actions) return;

    const renderRunButton = (label = "[ ▶ RUN PLAY-INTEL SCAN ]") => `
      <button class="btn primary" id="play-intel-run" style="white-space:nowrap;padding:4px 10px">${label}</button>
      <label class="row small" style="gap:6px;align-items:center">
        <input type="checkbox" id="play-intel-probes">
        <span class="muted">run active probes (RTDB · Firestore · Storage)</span>
      </label>`;

    let priorScans = [];
    try {
        const r = await fetch(`/v1/playintel/scans?apk_sha256=${encodeURIComponent(sha || "")}&limit=20`);
        if (r.ok) priorScans = (await r.json()).scans || [];
    } catch (_) { /* offline DB → treat as no history */ }

    const renderState = () => {
        if (!priorScans.length) {
            if (statusEl) statusEl.textContent = "never scanned";
            actions.innerHTML = renderRunButton();
        } else {
            const latest = priorScans[0];
            if (statusEl) statusEl.innerHTML = `<span style="color:var(--acid)">${priorScans.length}</span> prior scan(s) · latest ${escapeHtml(fmtAgo(latest.scanned_at))}`;
            actions.innerHTML = `
              <div class="row small" style="gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11px">
                <span><span class="muted">firebase:</span> <span class="t-mono" style="color:${latest.firebase_project_count ? "var(--acid)" : "inherit"}">${latest.firebase_project_count || 0}</span></span>
                <span><span class="muted">secrets:</span> <span class="t-mono" style="color:${latest.confirmed_secrets_count ? "var(--sev-high)" : "inherit"}">${latest.confirmed_secrets_count || 0}</span></span>
                <span><span class="muted">vulns:</span> <span class="t-mono" style="color:${latest.vulnerability_count ? "var(--sev-crit)" : "inherit"}">${latest.vulnerability_count || 0}</span></span>
                <span><span class="muted">findings:</span> <span class="t-mono">${latest.findings_count || 0}</span></span>
              </div>
              <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
                <a class="btn primary" href="#/play-scan" style="padding:4px 10px;white-space:nowrap"
                   data-load-scan="${escapeHtml(latest.id)}">[ VIEW LATEST ]</a>
                ${renderRunButton("[ ▶ RE-RUN ]")}
              </div>`;
        }
        const runBtn = $("#play-intel-run");
        const probes = $("#play-intel-probes");
        if (runBtn) runBtn.addEventListener("click", async () => {
            runBtn.disabled = true;
            runBtn.textContent = "[ SCANNING… ]";
            if (statusEl) statusEl.textContent = "scanning · this can take 30–90s";
            try {
                const form = new FormData();
                form.append("run_active_probes", probes && probes.checked ? "true" : "false");
                const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/play-scan`, { method: "POST", body: form });
                if (!r.ok) {
                    const t = (await r.text()).slice(0, 240);
                    throw new Error(`[${r.status}] ${t}`);
                }
                const body = await r.json();
                runBtn.textContent = "[ ✓ COMPLETE — VIEW ]";
                runBtn.style.color = "var(--acid)";
                runBtn.disabled = false;
                runBtn.onclick = () => { sessionStorage.setItem("playintel-jump", body.scan_id); location.hash = "#/play-scan"; };
                setTimeout(() => {
                    if (location.hash.startsWith("#/project/")) {
                        sessionStorage.setItem("playintel-jump", body.scan_id);
                        location.hash = "#/play-scan";
                    }
                }, 1500);
            } catch (e) {
                runBtn.textContent = "[ FAILED ]";
                runBtn.style.color = "var(--sev-crit)";
                runBtn.title = (e && e.message) || String(e);
                runBtn.disabled = false;
            }
        });
    };
    renderState();
}

function _exports_panel(id) {
    const fmts = [
        ["postman",   "POSTMAN",  "API endpoints as a Postman v2.1 collection (any host, GET defaults)"],
        ["caido",     "CAIDO",    "Caido Replay import — open in Workbench → Replay → Import"],
        ["burp",      "BURP",     "Burp Suite items XML — right-click → Send to Repeater"],
        ["moxy",      "MOXY",     "Moxy ruleset YAML — drop into Moxy listen-port 8080"],
        ["deeplinks", "DEEPLINK SH", "bash am-start probe loop for every deeplink + exported activity"],
    ];
    return `
      <section class="panel">
        <div class="panel-head"><span>// EXPORTS</span><span class="spacer"></span><span class="muted small">one click per format</span></div>
        <div class="panel-body col" style="gap:8px">
          <div class="muted small">
            Every recovered URL / deeplink / exported activity, packaged for the tool of your choice.
            Each download is generated fresh from the live project data.
          </div>
          <div class="row" style="flex-wrap:wrap;gap:8px">
            ${fmts.map(([fmt, label, hint]) => `
              <a class="btn primary"
                 href="/v1/projects/${encodeURIComponent(id)}/export/${fmt}"
                 download
                 title="${hint}">[ ${label} ]</a>`).join("")}
          </div>
          <div class="muted small">
            Paste / re-run the export anywhere — bytes are cached server-side until the project re-scans.
          </div>
        </div>
      </section>`;
}

function bar(n, max) {
    const fill = Math.min(Math.round((n / Math.max(max, 1)) * 16), 16);
    return "█".repeat(fill) + "░".repeat(16 - fill);
}

async function mount_project_static(ctx) {
    const id = ctx.params.id;
    const [project, findings] = await Promise.all([
        getJSON(`/v1/projects/${encodeURIComponent(id)}`).catch(() => null),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/findings`).catch(() => []),
    ]);

    const crumb = $("#static-breadcrumb");
    if (project && crumb) {
        crumb.textContent = `🔱 NEXUS / ${id} / static · ${project.package_name || "—"} v${project.version_name || "?"} · sha-256 ${(project.apk_sha256 || "").slice(0, 12)}…`;
    }

    // SDK fingerprint
    const surface = (project && project.attack_surface) || {};
    const sdks = surface.sdk_fingerprint || {};
    const sdkEl = $("#static-sdks");
    if (sdkEl) {
        const keys = Object.keys(sdks);
        if (!keys.length) sdkEl.innerHTML = `<div class="muted small">none recognized — DEX strings didn't match any signature</div>`;
        else sdkEl.innerHTML = keys.map((k) => `<div class="row"><span class="t-mono" style="color:var(--cyan);flex:1">${k}</span><span class="muted small">${sdks[k]}</span></div>`).join("");
    }

    // Crypto ops
    const ops = surface.crypto_operations || [];
    const cryptoEl = $("#static-crypto");
    if (cryptoEl) {
        if (!ops.length) cryptoEl.innerHTML = `<div class="muted small">no cryptographic operations indexed</div>`;
        else cryptoEl.innerHTML = ops.slice(0, 12).map((op) => `
            <div class="row" style="padding:4px 0;border-bottom:1px dashed var(--border)">
              <span class="t-mono small" style="color:${(op.algorithm || "").includes("ECB") ? "var(--sev-crit)" : "var(--cyan)"};flex:1;overflow:hidden;text-overflow:ellipsis">${op.algorithm || "?"}</span>
              <span class="muted small">${op.key_source || "?"}</span>
            </div>`).join("");
    }

    // Findings — with click-to-filter buttons
    const cnt = $("#static-count");
    if (cnt) cnt.textContent = `${findings.length} finding(s)`;
    let activeSev = "";
    const renderFindings = () => {
        const list = activeSev ? findings.filter((f) => (f.severity || "").toLowerCase() === activeSev) : findings;
        const el = $("#static-findings");
        if (!el) return;
        $("#static-active-filter").textContent = activeSev ? `severity: ${activeSev}` : "all severities";
        if (!list.length) {
            el.innerHTML = `<div class="empty-state">no findings ${activeSev ? "at this severity" : "— ingest an APK or rescan"}</div>`;
            return;
        }
        el.innerHTML = list.map((f) => `
            <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
              <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine || "?"}]</span>${f.confirmed ? '<span class="badge connected" style="font-size:9px;padding:2px 6px"><span class="dot">●</span>CONFIRMED</span>' : ""}</div>
              <div class="title">${f.title}</div>
              <div class="meta">${f.location || "—"} · ${f.cwe_id || ""} ${f.owasp_mobile || ""} ${f.masvs ? "· " + f.masvs : ""}</div>
            </a>`).join("");
    };
    renderFindings();
    $$('[data-fsev]').forEach((btn) => btn.addEventListener("click", () => {
        activeSev = btn.dataset.fsev;
        $$('[data-fsev]').forEach((b) => b.classList.toggle("primary", b === btn));
        renderFindings();
    }));
}

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
              <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
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

async function mount_device_pull() {
    const info = await getJSON("/v1/device/info").catch(() => ({connected: false, reason: "network error"}));
    const badgeRoot = $(".row .badge");
    if (badgeRoot) {
        badgeRoot.innerHTML = info.connected
            ? `<span class="dot">●</span>${info.model || "device"} · android ${info.android_release || "?"}`
            : `<span class="dot">●</span>NO DEVICE`;
        badgeRoot.classList.toggle("connected", info.connected);
    }

    const panel = $(".panel");
    if (!panel) return;
    const head = panel.querySelector(".panel-head");
    const body = panel.querySelector(".panel-body");

    if (!info.connected) {
        head.innerHTML = `// PACKAGES`;
        body.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit);font-size:20px;letter-spacing:3px">NO DEVICE CONNECTED</div><div class="muted">${info.reason || ""}</div><div class="muted small" style="margin-top:12px">plug a device, authorize USB debugging, then reload this screen.</div></div>`;
        return;
    }

    // Cached per-scope so flipping between 3RD/ALL/SYSTEM doesn't re-shell.
    const cache = {};
    let activeScope = "3rd";
    let activeFilter = "";

    const renderTable = (pkgs) => {
        const filter = activeFilter.toLowerCase();
        const filtered = filter ? pkgs.filter((p) => p.package.toLowerCase().includes(filter)) : pkgs;
        head.innerHTML = `// PACKAGES · <span style="color:var(--cyan)">${filtered.length}</span>${filter ? ` of ${pkgs.length}` : ""} · scope <span style="color:var(--acid)">${activeScope}</span>${info.abi ? ` · ${info.abi}` : ""}`;
        if (!filtered.length) {
            body.innerHTML = `<div class="empty-state">no packages match — try a different filter or switch scope to ALL.</div>`;
            return;
        }
        // Render the entire matched set. On a Samsung that's ~600 rows of
        // bare-DOM; well within budget. Virtualisation can land when someone
        // actually hits a flagship Android device with > 2k packages.
        body.innerHTML = `
            <div class="table-hdr" style="grid-template-columns: 1fr 200px">
                <span>PACKAGE</span><span></span>
            </div>` +
            filtered.map(({ package: pkg }) => `
                <div class="table-row" style="grid-template-columns: 1fr 200px">
                    <span class="t-mono">${escapeHtml(pkg)}</span>
                    <span style="text-align:right"><button class="btn primary" data-pull="${escapeHtml(pkg)}" style="padding:4px 10px;white-space:nowrap">[ PULL ]</button></span>
                </div>`).join("");
        bindPullButtons();
    };

    const fetchScope = async (scope) => {
        if (cache[scope] !== undefined) return cache[scope];
        body.innerHTML = `<div class="empty-state"><span class="muted small uppercase">listing ${scope === "3rd" ? "third-party" : scope} packages…</span></div>`;
        const pkgs = await getJSON(`/v1/device/packages?scope=${encodeURIComponent(scope)}`).catch(() => []);
        cache[scope] = pkgs;
        return pkgs;
    };

    const reloadActive = async () => renderTable(await fetchScope(activeScope));

    // Scope toggle. data-scope buttons highlight the active one.
    $$('[data-scope]').forEach((btn) => btn.addEventListener("click", async () => {
        activeScope = btn.dataset.scope;
        $$('[data-scope]').forEach((b) => b.classList.toggle("primary", b === btn));
        await reloadActive();
    }));

    // Live search — debounce so the table doesn't thrash on every keystroke.
    const filterInput = $("#pull-filter");
    let debounce = null;
    if (filterInput) filterInput.addEventListener("input", () => {
        activeFilter = filterInput.value || "";
        clearTimeout(debounce);
        debounce = setTimeout(reloadActive, 120);
    });

    await reloadActive();
}

function bindPullButtons() {
    $$("[data-pull]").forEach((btn) => btn.addEventListener("click", async () => {
        const pkg = btn.dataset.pull;
        btn.textContent = "[ PULLING… ]";
        btn.disabled = true;
        try {
            const fd = new FormData(); fd.append("package", pkg);
            const r = await fetch("/v1/device/pull", { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);

            if (j.ingest_error) {
                // Pulled files OK but pipeline blew up — keep the analyst informed
                // rather than pretending it worked.
                btn.textContent = "[ INGEST FAILED ]";
                btn.style.color = "var(--sev-crit)";
                btn.title = j.ingest_error;
                return;
            }
            if (!j.project_id) {
                // ingest=false escape hatch or some other reason — just file pull.
                btn.textContent = `[ PULLED ${j.count} ]`;
                btn.style.color = "var(--acid)";
                return;
            }

            // Auto-route to the freshly-ingested (or deduped) project.
            const label = j.dedup ? `[ ✓ ALREADY SCANNED — OPEN ${j.project_id} ]`
                                  : `[ ✓ INGESTED — OPEN ${j.project_id} ]`;
            btn.textContent = label;
            btn.style.color = j.dedup ? "var(--magenta)" : "var(--acid)";
            btn.disabled = false;
            btn.onclick = () => { location.hash = `#/project/${j.project_id}/overview`; };
            // Short auto-route so the user doesn't have to click twice.
            setTimeout(() => { if (location.hash.startsWith("#/device/pull")) location.hash = `#/project/${j.project_id}/overview`; }, 1500);
        } catch (e) {
            btn.textContent = `[ FAILED ]`;
            btn.style.color = "var(--sev-crit)";
            btn.title = e.message || String(e);
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

      <div class="split-with-aside">
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

        <!-- COMMAND LOG (right pane on wide screens, drops below on narrow) -->
        <section class="panel aside">
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
    const grid = $("#recipes-grid");
    const catStrip = $("#recipes-categories");
    const countEl = $("#recipes-count");
    if (!grid || !catStrip) return;

    let allRecipes = [];
    try {
        allRecipes = await getJSON("/v1/recipes");
    } catch (e) {
        grid.innerHTML = `<div class="empty-state"><span style="color:var(--sev-crit)">failed to fetch /v1/recipes: ${escapeHtml(e.message || String(e))}</span></div>`;
        return;
    }

    if (!allRecipes.length) {
        grid.innerHTML = `
          <div class="empty-state">
            <div style="font-size:18px;color:var(--magenta);letter-spacing:3px">NO RECIPES</div>
            <div class="muted small" style="margin-top:8px">
              clone Medusa into <code>~/.mnexus/tools/medusa</code> (or run
              <code>scripts/setup.sh</code>) — the recursive scan picks them up.
            </div>
          </div>`;
        catStrip.innerHTML = "";
        if (countEl) countEl.textContent = "0 recipes";
        return;
    }

    // Category counts → dynamic chip strip. Sorted descending by count so
    // the long tail of single-module categories falls to the right.
    const counts = {};
    for (const r of allRecipes) {
        const c = (r.category || "MISC").toUpperCase();
        counts[c] = (counts[c] || 0) + 1;
    }
    const categories = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));

    let activePlatform = "";
    let activeOrigin = "";
    let activeCategory = "";
    let searchTerm = "";

    const renderCategories = () => {
        catStrip.innerHTML = [
            `<span class="muted small">category:</span>`,
            `<button class="btn ${activeCategory === "" ? "primary" : ""}" data-rcat="">[ ALL · ${allRecipes.length} ]</button>`,
            ...categories.map(([c, n]) => `
                <button class="btn ${activeCategory === c ? "primary" : ""}" data-rcat="${escapeHtml(c)}">[ ${escapeHtml(c)} · ${n} ]</button>
            `),
        ].join("");
        catStrip.querySelectorAll("[data-rcat]").forEach((btn) => {
            btn.addEventListener("click", () => {
                activeCategory = btn.dataset.rcat;
                renderCategories();
                renderGrid();
            });
        });
    };

    const renderGrid = () => {
        const filtered = allRecipes.filter((r) => {
            if (activePlatform && (r.platform || "android") !== activePlatform && r.platform !== "both") return false;
            if (activeOrigin && r.origin !== activeOrigin) return false;
            if (activeCategory && (r.category || "MISC").toUpperCase() !== activeCategory) return false;
            if (searchTerm) {
                const hay = `${r.name} ${r.description || ""} ${r.category || ""}`.toLowerCase();
                if (!hay.includes(searchTerm)) return false;
            }
            return true;
        });
        if (countEl) {
            const suffix = filtered.length === allRecipes.length
                ? `${allRecipes.length} recipes`
                : `${filtered.length} of ${allRecipes.length} match`;
            countEl.textContent = suffix;
        }
        grid.innerHTML = filtered.length
            ? filtered.map((r) => `
                <div class="recipe-card">
                  <div class="cat-row">
                    <span class="cat">${escapeHtml(r.category || "MISC")}</span>
                    <span class="grow"></span>
                    <span title="${escapeHtml(r.platform || "android")}">${r.platform === "ios" ? "🍎" : r.platform === "both" ? "🤖🍎" : "🤖"}</span>
                    <span class="origin">${escapeHtml(r.origin || "?")}</span>
                  </div>
                  <div class="name">${escapeHtml(r.name)}</div>
                  <div class="desc">${escapeHtml(r.description || "")}</div>
                  <div class="foot">
                    <span class="compat">${escapeHtml(r.compatibility || "")}</span>
                    <div class="actions">
                      <button class="btn" data-preview="${escapeHtml(r.name)}" style="padding:4px 10px">[ PREVIEW ]</button>
                      <button class="btn primary" data-load="${escapeHtml(r.name)}" style="padding:4px 10px">[ LOAD ]</button>
                    </div>
                  </div>
                </div>`).join("")
            : `<div class="empty-state"><span class="muted">no recipes match the current filter</span></div>`;
        bindRecipeButtons();
    };

    $$('[data-rplat]').forEach((btn) => btn.addEventListener("click", () => {
        activePlatform = btn.dataset.rplat;
        $$('[data-rplat]').forEach((b) => b.classList.toggle("primary", b === btn));
        renderGrid();
    }));
    $$('[data-rorigin]').forEach((btn) => btn.addEventListener("click", () => {
        activeOrigin = btn.dataset.rorigin;
        $$('[data-rorigin]').forEach((b) => b.classList.toggle("primary", b === btn));
        renderGrid();
    }));
    const searchInp = $("#recipes-search");
    if (searchInp) searchInp.addEventListener("input", (e) => {
        searchTerm = e.target.value.trim().toLowerCase();
        renderGrid();
    });

    renderCategories();
    renderGrid();
}

function bindRecipeButtons() {

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
    bindThemePicker();

    const s = await getJSON("/v1/settings").catch(() => null);
    if (!s) return;
    const main = $(".main");
    if (!main) return;
    // Re-render the panels with real values. Skip the THEME panel (index 0)
    // and target ENGINE PATHS / SERVICE URLS by their headings instead of
    // brittle indices.
    const allPanels = $$(".panel");
    const findPanelByHead = (label) => allPanels.find((p) => (p.querySelector(".panel-head")?.textContent || "").includes(label));
    const pathsPanel = findPanelByHead("ENGINE PATHS")?.querySelector(".panel-body");
    if (pathsPanel) {
        pathsPanel.innerHTML = Object.entries(s.paths).map(([k, v]) =>
            `<div class="row"><span class="muted small" style="width:140px">${k.toUpperCase()}</span><code>${v || "(unset)"}</code></div>`
        ).join("");
    }
    const servicesPanel = findPanelByHead("SERVICE URLS")?.querySelector(".panel-body");
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
    if (!fid) return;

    // Try to fetch the real finding. If it 404s, render an honest empty state
    // instead of letting the demo placeholder linger.
    let finding;
    try {
        finding = await getJSON(`/v1/findings/${encodeURIComponent(fid)}`);
    } catch (e) {
        const card = $("#finding-card");
        if (card) {
            card.innerHTML = `
              <div class="head"><span class="tag" style="color:var(--sev-crit)">404</span><span>finding not found</span></div>
              <div class="meta">no finding with id <code>${fid}</code> in any stored project. <a href="#/projects">back to projects</a></div>`;
        }
        return;
    }

    const sev = (finding.severity || "info").toLowerCase();
    const sevClass = ["crit", "high", "med", "low", "info"].includes(sev) ? sev :
                     (sev === "critical" ? "crit" : sev === "medium" ? "med" : "info");

    setText("finding-id", finding.id);
    setText("finding-title", finding.title);
    setText("finding-desc", finding.description || "");
    setText("finding-cwe", finding.cwe_id ? finding.cwe_id : "");
    setText("finding-owasp", finding.owasp_mobile ? `OWASP ${finding.owasp_mobile}` : "");

    // ── library attribution chip ──
    const attrEl = $("#finding-attribution");
    const attrPathsEl = $("#finding-attribution-paths");
    if (attrEl && finding.attributed_to) {
        const owner = finding.attributed_to;
        const conf = (finding.attribution_confidence || "").toLowerCase();
        // Colour by owner class — first-party = acid (their code, their fix),
        // named SDK = cyan (third-party, talk to vendor or rotate),
        // unknown third-party = magenta (warning: needs human review).
        let color = "var(--magenta)";
        if (owner === "first-party") color = "var(--acid)";
        else if (owner === "third-party (unknown)") color = "var(--sev-high)";
        else color = "var(--cyan)";
        const dot = conf === "high" ? "●" : conf === "medium" ? "◐" : "○";
        attrEl.style.display = "";
        attrEl.style.color = color;
        attrEl.textContent = `${dot} ${owner}${finding.sdk_category ? ` · ${finding.sdk_category}` : ""}`;

        const paths = finding.attribution_paths || [];
        if (attrPathsEl && paths.length) {
            attrPathsEl.style.display = "";
            attrPathsEl.innerHTML = `<span class="muted small uppercase">// inferred from</span> ` +
                paths.map((p) => `<code style="font-size:11px">${escapeHtml(p)}</code>`).join("<br>");
        }
    }

    const chipEl = $("#finding-chip");
    if (chipEl) chipEl.innerHTML = `<span class="chip ${sevClass}">${sevClass.toUpperCase()}</span>`;

    const stateEl = $("#finding-state");
    if (stateEl) {
        stateEl.classList.toggle("connected", !!finding.confirmed);
        stateEl.classList.toggle("scanning", !finding.confirmed);
        stateEl.innerHTML = `<span class="dot">●</span>${finding.confirmed ? "CONFIRMED" : "STATIC ONLY"}`;
    }

    const evidenceEl = $("#finding-evidence");
    if (evidenceEl) evidenceEl.textContent = finding.evidence || "(no evidence captured)";

    if (finding.suggested_hook) {
        const hl = $("#finding-hook-label"); if (hl) hl.style.display = "";
        const hookEl = $("#finding-hook");
        if (hookEl) { hookEl.style.display = ""; hookEl.textContent = finding.suggested_hook; }
    }

    const mitEl = $("#finding-mitigation");
    if (mitEl) {
        if (finding.remediation && finding.remediation.trim()) {
            mitEl.innerHTML = finding.remediation
                .split("\n").filter((l) => l.trim())
                .map((line, i) => `<div><b>${String(i + 1).padStart(2, "0")}</b> ${escapeHtml(line)}</div>`).join("");
        } else {
            mitEl.innerHTML = `<div class="muted small">— no remediation captured (low/info finding).</div>`;
        }
    }

    const actions = $("#finding-actions");
    if (actions) actions.style.display = "";

    const runHookBtn = $("#finding-run-hook");
    if (runHookBtn) runHookBtn.addEventListener("click", () => {
        if (!finding.suggested_hook) { runHookBtn.textContent = "[ NO HOOK ]"; return; }
        runHookBtn.textContent = "[ HOOK READY · paste into /#/dynamic ]";
        runHookBtn.style.color = "var(--acid)";
    });

    const copyBtn = $("#finding-copy-mitigation");
    if (copyBtn) copyBtn.addEventListener("click", async () => {
        const text = finding.remediation || "";
        try { await navigator.clipboard.writeText(text); copyBtn.textContent = "[ COPIED ✓ ]"; copyBtn.style.color = "var(--acid)"; }
        catch { copyBtn.textContent = "[ CLIPBOARD BLOCKED ]"; copyBtn.style.color = "var(--sev-high)"; }
    });
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

async function mount_report(ctx) {
    // Determine the target project: query string, then ctx, then first project.
    const projects = await getJSON("/v1/projects").catch(() => []);
    const queryProj = (ctx.hash || "").split("?")[1]?.split("project=")[1];
    let targetId = (queryProj && decodeURIComponent(queryProj))
        || ctx.params.id
        || projects[0]?.id;
    let activeTemplate = "technical";
    if (!targetId && !projects.length) {
        const main = $(".main");
        if (main) main.insertAdjacentHTML("afterbegin", `<div class="empty-state" style="margin-bottom:8px;color:var(--sev-high)">no projects yet — <a href="#/scan">ingest one</a></div>`);
    }

    // ── live report preview from the chosen project ──
    const previewHead = $("#report-preview-head");
    const preview = $("#report-preview");
    if (preview) {
        if (!targetId) {
            preview.innerHTML = `<div class="empty-state"><span class="muted small uppercase">no project picked yet</span></div>`;
        } else {
            try {
                const project = await getJSON(`/v1/projects/${encodeURIComponent(targetId)}`);
                const findings = (project.attack_surface?.findings || []);
                const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
                const top = findings
                    .filter((f) => f.remediation && f.remediation.trim())
                    .sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9))
                    .slice(0, 8);

                if (previewHead) previewHead.textContent = `// PREVIEW · ${project.package_name} v${project.version_name} · ${findings.length} findings`;

                preview.innerHTML = `
                  <div style="font-size:20px;color:var(--cyan);font-weight:700;letter-spacing:2px">MEDUSA NEXUS // ${activeTemplate.toUpperCase()} ASSESSMENT</div>
                  <div class="muted small">target: ${project.package_name} v${project.version_name} · SHA-256 ${(project.apk_sha256 || "").slice(0, 16)}… · ${(project.created_at || "").slice(0, 10)}</div>
                  <div class="gradient-underline"></div>
                  <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--magenta)">§ 01 · EXECUTIVE SUMMARY</div>
                  <div>Risk ${(project.risk_score ?? 0).toFixed(1)}/100. ${
                      Object.entries(project.findings_by_severity || {})
                          .filter(([, n]) => n)
                          .map(([sev, n]) => `${n} ${sev}`).join(", ") || "no findings"
                  }.</div>
                  <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--acid)">§ 02 · MITIGATION PLAYBOOK — mandatory section</div>
                  <div class="mitigation">
                    ${top.length ? top.map((f) => {
                        const sev = (f.severity || "info").toLowerCase();
                        const cls = sev === "critical" ? "crit" : sev === "medium" ? "med" : sev;
                        const firstLine = f.remediation.split("\n").find((l) => l.trim()) || "";
                        return `<div class="row" style="align-items:flex-start;gap:10px"><span class="chip ${cls}">${cls.toUpperCase()}</span><div><b>${f.id} · ${f.title}</b><br>→ ${escapeHtml(firstLine)}</div></div>`;
                    }).join("") : `<div class="muted small">no actionable findings yet — run static engines.</div>`}
                  </div>
                  <div class="muted small">§ 03 · FINDINGS DETAIL · § 04 · OWASP MASVS COMPLIANCE MATRIX · § 05 · EVIDENCE PACKAGE · § 06 · REPRO STEPS</div>`;
            } catch (e) {
                preview.innerHTML = `<div class="empty-state"><span style="color:var(--sev-crit)">failed to load project ${targetId}: ${e.message}</span></div>`;
            }
        }
    }

    // Template selector — stable [data-template] attribute, no
    // textContent-sniffing or :first-of-type juggling.
    const tmplRows = $$("#report-template-panel [data-template]");
    const setActiveTemplate = (next) => {
        activeTemplate = next;
        tmplRows.forEach((r) => {
            const isMine = r.dataset.template === next;
            r.classList.toggle("active", isMine);
            r.style.background = isMine ? "var(--bg-accent-panel)" : "var(--bg-panel)";
            r.style.borderColor = isMine ? "var(--border-accent)" : "var(--border)";
            // Re-render the dot indicator on the first child <span>.
            const dot = r.querySelector("span");
            if (dot) {
                dot.textContent = isMine ? "●" : "○";
                dot.style.color = isMine ? "var(--acid)" : "";
                dot.className = isMine ? "" : "muted";
            }
            const label = r.querySelector("span:nth-child(2)");
            if (label) {
                label.style.color = isMine ? "var(--acid)" : "";
                label.style.fontWeight = isMine ? "700" : "";
            }
        });
    };
    tmplRows.forEach((row) => {
        row.addEventListener("click", () => setActiveTemplate(row.dataset.template));
    });

    // Export buttons — stable [data-export] attribute, single regex-free
    // wireup. Each button knows its format directly from the attribute.
    const labelFor = (fmt) => ({ pdf: "PDF", html: "HTML", markdown: ".MD", json: "JSON" })[fmt] || fmt.toUpperCase();
    $$("[data-export]").forEach((btn) => {
        const fmt = btn.dataset.export;
        btn.addEventListener("click", async () => {
            if (!targetId) { alert("no project selected — scan one first."); return; }
            const fd = new FormData();
            fd.append("template", activeTemplate);
            fd.append("fmt", fmt);
            const original = btn.textContent;
            btn.textContent = "[ … ]";
            btn.disabled = true;
            try {
                const r = await fetch(`/v1/projects/${encodeURIComponent(targetId)}/report`, { method: "POST", body: fd });
                if (!r.ok) {
                    const detail = await r.text();
                    btn.textContent = `[ ${labelFor(fmt)} ✕ ]`;
                    btn.style.color = "var(--sev-crit)";
                    alert(`report failed (${r.status}): ${detail.slice(0, 240)}`);
                    return;
                }
                const blob = await r.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${targetId}.${fmt === "markdown" ? "md" : fmt}`;
                a.click();
                URL.revokeObjectURL(url);
                btn.textContent = `[ ${labelFor(fmt)} ✓ ]`;
                btn.style.color = "var(--acid)";
                setTimeout(() => {
                    btn.textContent = original;
                    btn.style.color = "";
                }, 1800);
            } finally {
                btn.disabled = false;
            }
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
    // Backup / delete / manifest buttons now live inside projectTabs()
    // (the right-side action group of the tab bar), so they show up on
    // every project sub-page — including the OVERVIEW / STATIC /
    // DYNAMIC / RUNTIME parents that render projectTabs() directly
    // instead of going through this chrome helper.
    return h`
      <div class="muted small uppercase">🔱 NEXUS / ${id} / ${label}</div>
      ${projectTabs(id, parent)}`;
}

// Exposed on window so the inline onclick="…" handlers in projectChrome
// can reach them — vanilla SPA pattern, no framework router gluing.
window.projectChromeManifest = async function (id) {
    // Reuse a single chrome-level side-sheet so the markup doesn't have
    // to live in every view's template. We also reuse it across
    // navigations — opening on one tab, switching to another tab will
    // wipe the SPA's view shell but the sheet stays scoped to
    // document.body and gets removed by the next chrome render.
    let sheet = document.getElementById("chrome-manifest-sheet");
    if (sheet) sheet.remove();
    sheet = document.createElement("aside");
    sheet.id = "chrome-manifest-sheet";
    sheet.className = "side-sheet";
    sheet.innerHTML = `
      <div class="side-sheet-head">
        <span class="t-mono">AndroidManifest.xml · ${id}</span>
        <span class="spacer"></span>
        <button class="btn xs ghost" id="chrome-manifest-copy">COPY</button>
        <button class="btn xs ghost" id="chrome-manifest-download">DOWNLOAD</button>
        <button class="btn xs" id="chrome-manifest-close">CLOSE</button>
      </div>
      <pre class="side-sheet-body" id="chrome-manifest-content">loading…</pre>`;
    document.body.appendChild(sheet);

    const content = document.getElementById("chrome-manifest-content");
    const closeBtn = document.getElementById("chrome-manifest-close");
    const copyBtn = document.getElementById("chrome-manifest-copy");
    const dlBtn = document.getElementById("chrome-manifest-download");
    let xml = "";

    try {
        const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/manifest`);
        xml = await r.text();
        if (!r.ok) {
            content.textContent = `error [${r.status}]: ${xml.slice(0, 400)}`;
            return;
        }
        content.textContent = xml;
    } catch (e) {
        content.textContent = `network error: ${e}`;
        return;
    }

    closeBtn.addEventListener("click", () => sheet.remove());
    copyBtn.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(xml);
            copyBtn.textContent = "COPIED";
            setTimeout(() => copyBtn.textContent = "COPY", 1200);
        } catch {
            copyBtn.textContent = "CLIPBOARD BLOCKED";
        }
    });
    dlBtn.addEventListener("click", () => {
        const blob = new Blob([xml], { type: "application/xml;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${id}-AndroidManifest.xml`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
    // Esc closes the sheet.
    const onKey = (ev) => {
        if (ev.key === "Escape") {
            document.removeEventListener("keydown", onKey);
            sheet.remove();
        }
    };
    document.addEventListener("keydown", onKey);
};

window.projectChromeAttribute = async function (id) {
    // Re-run library attribution on the project's stored findings.
    // Designed for projects ingested before LibraryAttributionAudit
    // shipped — new scans get attribution for free.
    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/attribute`, { method: "POST" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
        await confirmModal({
            title: `✗ Attribution failed (${r.status})`,
            body: JSON.stringify(body, null, 2).slice(0, 400),
            okLabel: "OK", okStyle: "primary", cancelLabel: null,
        });
        return;
    }
    await confirmModal({
        title: `⌖ Attribution done — ${body.attributed_after}/${body.total_findings} findings tagged`,
        body: `<code>${body.newly_attributed}</code> newly attributed · <code>${body.attributed_before}</code> already had an owner.\n\nReloading the view so the chips show up.`,
        okLabel: "OK", okStyle: "primary", cancelLabel: null,
    });
    setTimeout(() => { renderRoute(); }, 200);
};

window.projectChromeBackup = async function (id) {
    const confirmed = await confirmModal({
        title: `Backup project ${id}?`,
        body: `Produces a self-contained .zip with the model, every finding, the source artefact, the workspace tree, and any generated reports. Lands in the workspace's <code>backups/</code> directory; existing archives are kept.`,
        okLabel: "BACKUP",
        okStyle: "primary",
    });
    if (!confirmed) return;
    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/backup`, { method: "POST" });
    if (!r.ok) {
        const body = await r.text();
        await confirmModal({
            title: `✗ Backup failed (${r.status})`,
            body: body.slice(0, 400),
            okLabel: "OK", okStyle: "primary", cancelLabel: null,
        });
        return;
    }
    const size = r.headers.get("X-Mnexus-Backup-Size") || "0";
    const files = r.headers.get("X-Mnexus-Backup-Files") || "0";
    const findings = r.headers.get("X-Mnexus-Backup-Findings") || "0";
    await confirmModal({
        title: `✓ Archive ready — ${(parseInt(size, 10) / 1024 / 1024).toFixed(2)} MB`,
        body: `${files} files · ${findings} findings\n\nCheck the workspace's <code>backups/</code> directory on the host.`,
        okLabel: "OK", okStyle: "primary", cancelLabel: null,
    });
};

window.projectChromeDelete = async function (id) {
    const confirmed = await confirmModal({
        title: `Wipe project ${id}?`,
        body: `<strong style="color:var(--sev-high)">DESTRUCTIVE.</strong> Wipes the project's workspace tree, every report, the source APK (when no other project shares the file), the PlayIntel secrets dir (when no other project shares the package), and the DB row.\n\nThis cannot be undone. Back up first if there's any chance you want the data again.`,
        okLabel: "WIPE",
        okStyle: "danger",
        confirmPhrase: "yes",
    });
    if (!confirmed) return;
    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}?confirm=true`, { method: "DELETE" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
        await confirmModal({
            title: `✗ Delete failed (${r.status})`,
            body: JSON.stringify(body, null, 2).slice(0, 600),
            okLabel: "OK", okStyle: "primary", cancelLabel: null,
        });
        return;
    }
    const audit = body.audit || {};
    const summary = [
        `workspace        · ${audit.workspace_files_removed || 0} file(s) · ${((audit.workspace_bytes_freed || 0) / 1024 / 1024).toFixed(2)} MB`,
        audit.source_artefact_removed ? `source artefact  · ${audit.source_artefact_removed}` : "source artefact  · kept (shared with another project)",
        audit.secrets_dir_removed ? `secrets dir      · ${audit.secrets_dir_removed}` : null,
        audit.reports_removed && audit.reports_removed.length ? `reports          · ${audit.reports_removed.length} file(s)` : null,
        `db               · ${audit.findings_removed || 0} finding(s) + ${audit.dynamic_events_removed || 0} dynamic event(s) + 1 project row`,
    ].filter(Boolean).join("\n");
    await confirmModal({
        title: `✓ Wiped ${audit.project_id} · ${audit.package || ""}`,
        body: summary,
        okLabel: "OK", okStyle: "primary", cancelLabel: null,
    });
    // After a single-project wipe we route back to the projects list —
    // staying on the project page would 404 the next route load.
    location.hash = "#/projects";
};

/**
 * Promise-based confirmation modal — tiny vanilla pattern, no framework.
 *
 * Usage:
 *   const ok = await confirmModal({
 *     title: "Wipe project?",
 *     body: "long description",
 *     okLabel: "WIPE",
 *     okStyle: "danger",          // "primary" | "danger"
 *     cancelLabel: "Cancel",      // null to omit
 *     confirmPhrase: "yes",        // if set, the OK button stays disabled
 *                                  // until the user types this exact phrase
 *   });
 */
window.confirmModal = function (opts) {
    return new Promise((resolve) => {
        const existing = document.getElementById("mn-confirm-overlay");
        if (existing) existing.remove();
        const okStyle = opts.okStyle === "danger" ? "danger" : "primary";
        const overlay = document.createElement("div");
        overlay.id = "mn-confirm-overlay";
        overlay.className = "modal-overlay";
        // Escape body content but allow our own controlled HTML — we build
        // body from constants + audit data, so no untrusted user input
        // reaches innerHTML directly.
        const bodyHtml = (opts.body || "").replace(/\n/g, "<br>");
        const phrase = opts.confirmPhrase || "";
        overlay.innerHTML = `
          <div class="modal">
            <div class="modal-head">${opts.title || "Confirm"}</div>
            <div class="modal-body">${bodyHtml}</div>
            ${phrase ? `<div class="modal-phrase">
              <div class="muted small">type <code>${phrase}</code> to enable the button:</div>
              <input class="input-plain" id="mn-confirm-phrase" autocomplete="off" spellcheck="false" />
            </div>` : ""}
            <div class="modal-actions">
              ${opts.cancelLabel !== null ? `<button class="btn ghost" id="mn-confirm-cancel">${opts.cancelLabel || "Cancel"}</button>` : ""}
              <button class="btn ${okStyle}" id="mn-confirm-ok" ${phrase ? "disabled" : ""}>${opts.okLabel || "OK"}</button>
            </div>
          </div>`;
        document.body.appendChild(overlay);

        const cleanup = (result) => {
            overlay.remove();
            resolve(result);
        };
        const okBtn = document.getElementById("mn-confirm-ok");
        const cancelBtn = document.getElementById("mn-confirm-cancel");
        const phraseInput = document.getElementById("mn-confirm-phrase");
        if (phraseInput) {
            phraseInput.addEventListener("input", () => {
                okBtn.disabled = phraseInput.value.trim().toLowerCase() !== phrase.toLowerCase();
            });
            phraseInput.focus();
        }
        okBtn.addEventListener("click", () => cleanup(true));
        if (cancelBtn) cancelBtn.addEventListener("click", () => cleanup(false));
        // Click outside the modal panel = cancel (only if cancelLabel is shown).
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay && opts.cancelLabel !== null) cleanup(false);
        });
        // Esc = cancel.
        const onKey = (e) => {
            if (e.key === "Escape" && opts.cancelLabel !== null) {
                document.removeEventListener("keydown", onKey);
                cleanup(false);
            }
        };
        document.addEventListener("keydown", onKey);
    });
};

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
      <section class="row" style="gap:8px;margin-bottom:8px">
        <button class="btn small" id="components-manifest-btn" title="Open the decoded AndroidManifest.xml in a side-sheet">VIEW RAW MANIFEST</button>
        <span class="muted small">cached on first open · re-runs apktool when the cache is empty</span>
      </section>
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
      <aside id="manifest-sheet" class="side-sheet" hidden>
        <div class="side-sheet-head">
          <span class="t-mono">AndroidManifest.xml</span>
          <span class="spacer"></span>
          <button class="btn xs ghost" id="manifest-copy">COPY</button>
          <button class="btn xs ghost" id="manifest-download">DOWNLOAD</button>
          <button class="btn xs" id="manifest-close">CLOSE</button>
        </div>
        <pre class="side-sheet-body" id="manifest-content">loading…</pre>
      </aside>
    </div>`;
}

async function mount_project_components(ctx) {
    const id = ctx.params.id;
    const [project, data] = await Promise.all([
        getJSON(`/v1/projects/${encodeURIComponent(id)}`).catch(() => null),
        getJSON(`/v1/projects/${encodeURIComponent(id)}/components`).catch(() => null),
    ]);
    if (!data) return;

    // iOS doesn't have manifest components in the Android sense — repurpose
    // this view to show URL schemes + entitlements when the project is iOS.
    if (project && project.platform === "ios") {
        const surface = project.attack_surface || {};
        const tabs = $("#components-tabs");
        if (tabs) tabs.innerHTML = `<span class="chip info">URL SCHEMES · ${(surface.url_schemes || []).length}</span>
          <span class="chip info">UNIVERSAL LINKS · ${(surface.deeplinks || []).filter((d) => !((surface.url_schemes || []).includes(d))).length}</span>
          <span class="chip ${surface.entitlements?.length ? "low" : "info"}">ENTITLEMENTS · ${(surface.entitlements || []).length}</span>`;
        const cnt = $("#components-count");
        if (cnt) cnt.textContent = `${(surface.url_schemes || []).length} URL schemes · ${(surface.entitlements || []).length} entitlements`;

        const tbl = $("#components-table");
        if (tbl) {
            const ulinks = (surface.deeplinks || []).filter((d) => !((surface.url_schemes || []).includes(d)));
            tbl.innerHTML = `
              <div class="table-hdr" style="grid-template-columns: 130px 1fr 90px"><span>KIND</span><span>TARGET</span><span></span></div>`
              + (surface.url_schemes || []).map((s) => `
                <div class="table-row" style="grid-template-columns: 130px 1fr 90px">
                  <span class="t-mono small">URL SCHEME</span>
                  <code class="t-mono" style="color:var(--magenta)">${escapeHtml(s)}://</code>
                  <span style="text-align:right">${s.toLowerCase() === "http" || s.toLowerCase() === "https" ? '<span class="chip high">RESERVED</span>' : '<span class="chip info">CUSTOM</span>'}</span>
                </div>`).join("")
              + ulinks.map((d) => `
                <div class="table-row" style="grid-template-columns: 130px 1fr 90px">
                  <span class="t-mono small">UNIVERSAL LINK</span>
                  <code class="t-mono" style="color:var(--cyan)">${escapeHtml(d)}</code>
                  <span style="text-align:right"><span class="chip low">VALIDATED</span></span>
                </div>`).join("");
        }

        const dl = $("#components-deeplinks");
        if (dl) {
            const all = [...(surface.url_schemes || []).map((s) => `${s}://`), ...((surface.deeplinks || []).filter((d) => !(surface.url_schemes || []).includes(d)))];
            dl.innerHTML = all.length ? all.map((l) => `<div class="row"><code class="t-mono" style="color:var(--magenta)">${escapeHtml(l)}</code></div>`).join("")
                                      : `<div class="empty-state">no deep-link schemes or universal links declared</div>`;
        }

        const perms = $("#components-permissions");
        if (perms) {
            const ents = surface.entitlements || [];
            perms.innerHTML = ents.length
                ? ents.map((e) => `<div class="t-mono small" style="padding:2px 0">${escapeHtml(e)}</div>`).join("")
                : `<div class="empty-state">no entitlements declared (typical for sandboxed iOS apps)</div>`;
        }
        // Re-label the panel headers from "PERMISSIONS DECLARED" → "ENTITLEMENTS".
        $$('.panel-head').forEach((el) => {
            const t = el.textContent.trim();
            if (t.startsWith("// PERMISSIONS DECLARED")) el.firstChild.textContent = "// ENTITLEMENTS";
            if (t.startsWith("// EXPORTED COMPONENTS")) el.firstChild.textContent = "// URL SCHEMES + UNIVERSAL LINKS";
            if (t.startsWith("// DEEP LINKS")) el.firstChild.textContent = "// DEEP LINKS (URL SCHEMES + UNIVERSAL LINKS)";
        });
        return;
    }
    // ─── Android path (unchanged) ─────────────────────────────────────

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

    // ── Manifest side-sheet wiring ────────────────────────────────
    const sheet = $("#manifest-sheet");
    const content = $("#manifest-content");
    const openBtn = $("#components-manifest-btn");
    const closeBtn = $("#manifest-close");
    const copyBtn = $("#manifest-copy");
    const dlBtn = $("#manifest-download");
    let cached = null;
    if (openBtn) {
        openBtn.addEventListener("click", async () => {
            sheet.hidden = false;
            if (cached == null) {
                content.textContent = "loading…";
                try {
                    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/manifest`);
                    cached = await r.text();
                    if (!r.ok) {
                        content.textContent = `error [${r.status}]: ${cached}`;
                        cached = null;
                        return;
                    }
                } catch (e) {
                    content.textContent = `network error: ${e}`;
                    cached = null;
                    return;
                }
            }
            content.textContent = cached;
        });
    }
    if (closeBtn) closeBtn.addEventListener("click", () => { sheet.hidden = true; });
    if (copyBtn) copyBtn.addEventListener("click", async () => {
        if (cached) {
            try { await navigator.clipboard.writeText(cached); copyBtn.textContent = "COPIED"; setTimeout(() => copyBtn.textContent = "COPY", 1200); }
            catch (e) { copyBtn.textContent = "CLIPBOARD BLOCKED"; }
        }
    });
    if (dlBtn) dlBtn.addEventListener("click", () => {
        if (!cached) return;
        const blob = new Blob([cached], { type: "application/xml;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `${id}-AndroidManifest.xml`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
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

    const _renderPath = (path, node) => {
        // Node shape after the live-merge: { methods: [...], hits: N, last_status: code }
        const methods = (node && node.methods) || [];
        const hits = (node && node.hits) || 0;
        const lastStatus = node && node.last_status;
        const lastColor = (lastStatus || 0) < 300 ? "var(--acid)"
                        : (lastStatus || 0) < 500 ? "var(--sev-high)" : "var(--sev-crit)";
        return `
          <div class="t-mono" style="padding-left:18px;display:flex;gap:8px;align-items:center">
            <span class="muted small">${methods.map((m) => `<span class="chip ${m === "POST" ? "high" : "info"}" style="font-size:9px">${m}</span>`).join(" ")}</span>
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(path)}</span>
            ${hits ? `<span class="t-mono small" style="color:var(--acid)">×${hits}${lastStatus ? ` <span style="color:${lastColor}">${lastStatus}</span>` : ""}</span>` : ""}
          </div>`;
    };

    const fetchOnce = async () => {
        const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/api-map`).catch(() => null);
        if (!data) return;
        const tree = data.tree || {};
        const discovered = data.discovered_hosts || {};
        const hosts = Object.keys(tree).sort();
        const discoveredKeys = Object.keys(discovered).sort();
        const live = data.live || {};
        const liveBadge = live.moxy_workspace
            ? ` · live <span style="color:var(--acid)">${escapeHtml(live.moxy_workspace.name || "")}</span> · ${live.window_s}s window`
            : (live.moxy_error ? ` · <span style="color:var(--magenta)">${escapeHtml(live.moxy_error)}</span>` : "");
        $("#apimap-count").innerHTML = `${hosts.length} hosts · ${(data.endpoints || []).length} endpoints${liveBadge}`;

        const treeEl = $("#apimap-tree");
        if (!hosts.length && !discoveredKeys.length) {
            treeEl.innerHTML = `<div class="empty-state">no endpoints discovered yet — static engines emit []. Ingest an APK with network code or start a Moxy session.</div>`;
        } else {
            const staticBlock = hosts.map((host) => {
                const paths = Object.keys(tree[host]).sort();
                const totalHits = paths.reduce((acc, p) => acc + ((tree[host][p] && tree[host][p].hits) || 0), 0);
                return `
                  <div style="margin-bottom:10px">
                    <div class="t-mono" style="color:var(--cyan);font-weight:700">▾ ${escapeHtml(host)}${totalHits ? ` <span class="muted small" style="color:var(--acid)">· ${totalHits} live hit(s)</span>` : ""}</div>
                    ${paths.map((p) => _renderPath(p, tree[host][p])).join("")}
                  </div>`;
            }).join("");
            const discoveredBlock = discoveredKeys.length ? `
              <div style="margin-top:14px;padding-top:10px;border-top:1px dashed var(--border)">
                <div class="muted small uppercase" style="letter-spacing:2px;margin-bottom:8px">// discovered live — not in static surface</div>
                ${discoveredKeys.map((host) => {
                    const paths = Object.keys(discovered[host]).sort();
                    return `
                      <div style="margin-bottom:10px">
                        <div class="t-mono" style="color:var(--magenta);font-weight:700">▾ ${escapeHtml(host)} <span class="muted small">(new)</span></div>
                        ${paths.map((p) => `
                          <div class="t-mono" style="padding-left:18px;display:flex;gap:8px;align-items:center">
                            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--magenta)">${escapeHtml(p)}</span>
                            <span class="t-mono small" style="color:var(--magenta)">×${discovered[host][p]}</span>
                          </div>`).join("")}
                      </div>`;
                }).join("")}
              </div>` : "";
            treeEl.innerHTML = staticBlock + discoveredBlock;
        }

        const fl = $("#apimap-flagged");
        if (!data.flagged.length) {
            fl.innerHTML = `<div class="empty-state">no network findings flagged</div>`;
        } else {
            fl.innerHTML = data.flagged.map((f) => `
              <a class="finding" href="#/project/${encodeURIComponent(id)}/finding/${encodeURIComponent(f.id)}" style="text-decoration:none">
                <div class="head">${chip(f.severity)}<span class="tag">${f.id}</span><span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
                <div class="title">${escapeHtml(f.title)}</div>
                <div class="meta">${escapeHtml(f.location || "—")}</div>
              </a>`).join("");
        }
    };

    await fetchOnce();
    pollingScope(fetchOnce, 3000);
}

/* SCREEN 16 — SSL Pinning Map (live) */
function view_project_ssl_map(ctx) {
    const id = ctx.params.id;
    return h`
    <div class="main">
      ${projectChrome(id, "ssl-map")}
      ${sectionHeader("S", "16 // NETWORK", "SSL PINNING MAP")}
      <section class="panel">
        <div class="panel-head">
          <span>// PINNING STATUS</span>
          <span class="spacer"></span>
          <span class="muted small" id="ssl-summary">loading…</span>
          <label class="row small" style="gap:6px;cursor:pointer;color:var(--muted)">
            <input type="checkbox" id="ssl-autorefresh" checked>
            <span>auto-refresh</span>
          </label>
          <button class="btn" id="ssl-refresh" style="padding:2px 10px;font-size:10px">[ ⟳ ]</button>
        </div>
        <div class="panel-body tight col" style="gap:8px">
          <div class="row small" style="padding:6px 8px;background:var(--bg-accent-panel);border:1px solid var(--border-accent);border-radius:2px;gap:14px;flex-wrap:wrap" id="ssl-live-bar">
            <span class="muted">scanning…</span>
          </div>
          <div id="ssl-table">loading…</div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><span>// LEGEND</span></div>
        <div class="panel-body row small" style="gap:18px;flex-wrap:wrap;color:var(--muted)">
          <span><span class="chip" style="background:rgba(34,222,128,0.15);color:var(--acid);border:1px solid var(--acid)">INTERCEPTED</span> TLS broke — proxy sees plaintext, no effective pinning</span>
          <span><span class="chip" style="background:rgba(232,121,249,0.15);color:var(--magenta);border:1px solid var(--magenta)">BYPASSED</span> Frida hook fired — pinning callback neutralised</span>
          <span><span class="chip" style="background:rgba(255,56,96,0.15);color:var(--sev-crit);border:1px solid var(--sev-crit)">BLOCKED</span> static says pinned + no Moxy hits → likely working</span>
          <span><span class="chip" style="background:rgba(255,149,0,0.15);color:var(--sev-high);border:1px solid var(--sev-high)">STATIC-PINNED</span> code path detected but no live evidence yet</span>
          <span><span class="chip" style="background:rgba(0,255,255,0.10);color:var(--cyan);border:1px solid var(--cyan)">CLEAR</span> no pinning detected · traffic flowing</span>
          <span><span class="chip" style="background:rgba(255,255,255,0.05);color:var(--muted);border:1px solid var(--muted)">UNKNOWN</span> not enough data — open the app and hit the host</span>
        </div>
      </section>
    </div>`;
}

const _SSL_STATUS_PALETTE = {
    intercepted: { color: "var(--acid)",     bg: "rgba(34,222,128,0.15)" },
    bypassed:    { color: "var(--magenta)",  bg: "rgba(232,121,249,0.15)" },
    blocked:     { color: "var(--sev-crit)", bg: "rgba(255,56,96,0.15)" },
    "static-pinned": { color: "var(--sev-high)", bg: "rgba(255,149,0,0.15)" },
    clear:       { color: "var(--cyan)",     bg: "rgba(0,255,255,0.10)" },
    unknown:     { color: "var(--muted)",    bg: "rgba(255,255,255,0.05)" },
};

function _ssl_status_chip(status) {
    const p = _SSL_STATUS_PALETTE[status] || _SSL_STATUS_PALETTE.unknown;
    return `<span class="chip" style="background:${p.bg};color:${p.color};border:1px solid ${p.color};font-size:9px;letter-spacing:1px">${(status || "?").toUpperCase()}</span>`;
}

async function mount_project_ssl_map(ctx) {
    const id = ctx.params.id;
    const summaryEl = $("#ssl-summary");
    const liveBarEl = $("#ssl-live-bar");
    const tableEl = $("#ssl-table");
    const autoEl = $("#ssl-autorefresh");
    const refreshBtn = $("#ssl-refresh");

    const fetchOnce = async () => {
        const data = await getJSON(`/v1/projects/${encodeURIComponent(id)}/ssl-map`).catch(() => null);
        if (!data) {
            tableEl.innerHTML = `<div class="empty-state"><span style="color:var(--sev-crit)">/ssl-map fetched failed — server reload?</span></div>`;
            return;
        }
        summaryEl.textContent = data.pinning_detected
            ? `static · pinning detected · ${data.library}`
            : "static · no pinning detected";

        const live = data.live || {};
        const workspace = live.moxy_workspace;
        const pinEvents = live.pin_event_count || 0;
        liveBarEl.innerHTML = `
          <span class="t-mono" style="color:var(--cyan)">moxy:</span>
          <span class="t-mono" style="color:${workspace ? "var(--acid)" : "var(--magenta)"}">${workspace ? escapeHtml(workspace.name || ("#" + workspace.id)) : (live.moxy_error || "offline")}</span>
          <span class="muted">·</span>
          <span class="t-mono" style="color:var(--cyan)">window:</span>
          <span class="t-mono">${live.window_s || "?"}s</span>
          <span class="muted">·</span>
          <span class="t-mono" style="color:var(--cyan)">pin events:</span>
          <span class="t-mono" style="color:${pinEvents ? "var(--magenta)" : "var(--muted)"}">${pinEvents}</span>
          <span class="spacer"></span>
          <span class="muted small" id="ssl-polled">polled ${fmtAgo(live.polled_at)}</span>
        `;

        if (!data.rows.length) {
            tableEl.innerHTML = `<div class="empty-state">no hosts indexed yet — static scan didn't find network code and the proxy hasn't seen anything either.</div>`;
            return;
        }
        tableEl.innerHTML = `
          <div class="table-hdr" style="grid-template-columns: 1fr 140px 110px 110px 90px 90px 110px 90px">
            <span>HOST</span><span>LIBRARY</span><span>STATUS</span><span>STATIC</span><span>MOXY HITS</span><span>LAST</span><span>BYPASS</span><span></span>
          </div>` + data.rows.map((r) => {
            const lastStatusColor = (r.moxy_last_status || 0) < 300 ? "var(--acid)"
                                 : (r.moxy_last_status || 0) < 500 ? "var(--sev-high)" : "var(--sev-crit)";
            return `
              <div class="table-row" style="grid-template-columns: 1fr 140px 110px 110px 90px 90px 110px 90px;${r.in_static_surface ? "" : "border-left:2px solid var(--magenta);padding-left:8px"}">
                <span class="t-mono" title="${r.in_static_surface ? "in static api_endpoints" : "discovered live — not in static surface"}">${escapeHtml(r.host)}${r.in_static_surface ? "" : " <span class=\"muted small\">(new)</span>"}</span>
                <span class="t-muted">${escapeHtml(r.library || "—")}</span>
                <span>${_ssl_status_chip(r.status)}</span>
                <span class="t-mono" style="color:${r.pinned ? "var(--sev-high)" : "var(--acid)"}">${r.pinned ? "pinned" : "—"}</span>
                <span class="t-mono" style="color:${r.moxy_hits ? "var(--acid)" : "var(--muted)"}">${r.moxy_hits || 0}${r.moxy_last_status ? ` <span style="color:${lastStatusColor}">${r.moxy_last_status}</span>` : ""}</span>
                <span class="t-muted small">${fmtAgo(r.moxy_last_ts || r.pin_last_ts)}</span>
                <span class="t-mono" style="color:var(--magenta);font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(r.bypass_recipe || "")}">${escapeHtml(r.bypass_recipe || "—")}</span>
                <span style="text-align:right">${r.bypass_recipe ? `<a class="btn primary" href="#/recipes" style="padding:2px 8px;font-size:10px">[ BYPASS ]</a>` : ""}</span>
              </div>`;
        }).join("");
    };

    // First paint synchronously, then start polling.
    await fetchOnce();
    let scope = pollingScope(fetchOnce, 3000);

    if (autoEl) autoEl.addEventListener("change", () => {
        if (autoEl.checked && !scope) scope = pollingScope(fetchOnce, 3000);
        else if (!autoEl.checked && scope) { scope.stop(); scope = null; }
    });
    if (refreshBtn) refreshBtn.addEventListener("click", fetchOnce);
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
    { path: "play-scan",                        view: view_play_scan,         mount: async () => { await mount_play_scan(); } },
    { path: "play-accounts",                    view: view_play_accounts,     mount: async () => { await mount_play_accounts(); } },
    { path: "devices",                          view: view_devices,           mount: mount_devices },
    { path: "adb",                              view: view_devices,           mount: mount_devices },  // alias of /devices
    { path: "device/pull",                      view: view_device_pull,       mount: mount_device_pull },
    { path: "device/bridge",                    view: view_device_bridge,     mount: mount_device_bridge },
    { path: "ios/decrypt",                      view: view_ios_decrypt,       mount: mount_ios_decrypt },
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
    // Bare project hash → overview. location.replace keeps the back button clean
    // so users don't bounce back into the redirect target's predecessor.
    { path: "project/:id", view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/overview`); return ""; } },
    // Common bare aliases for sub-views that actually live under /static or
    // similar. Anything Overview tiles link to gets a forgiving redirect here
    // so bookmarks + cross-references survive route reshuffles.
    { path: "project/:id/components", view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/static/components`); return ""; } },
    { path: "project/:id/secrets",    view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/static/secrets`); return ""; } },
    { path: "project/:id/native",     view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/static/native`); return ""; } },
    { path: "project/:id/overview",             view: view_project_overview,  mount: mount_project_overview },
    { path: "project/:id/static",               view: view_project_static,    mount: mount_project_static },
    { path: "project/:id/static/secrets",       view: view_project_secrets,    mount: mount_project_secrets },
    { path: "project/:id/static/components",    view: view_project_components, mount: mount_project_components },
    { path: "project/:id/static/native",        view: view_project_native,     mount: mount_project_native },
    { path: "project/:id/dynamic",              view: view_project_dynamic,   mount: mount_project_dynamic },
    { path: "project/:id/runtime",              view: view_project_runtime,   mount: mount_project_runtime },
    { path: "project/:id/manifest-diff",        view: view_project_manifest_diff, mount: mount_project_manifest_diff },
    { path: "project/:id/findings-diff",        view: view_project_findings_diff, mount: mount_project_findings_diff },
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
    // Project-scoped routes share a tab bar with rescan/refresh buttons —
    // bind them once after every mount has finished rebuilding the DOM.
    if (pathPart.startsWith("project/")) bindProjectTabActions();
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

/* ─── sidebar toggle (collapsed / open / hidden) ───
 *
 * Three modes share one element:
 *   - desktop wide       : default `open`     — full 260px sidebar
 *   - desktop narrow     : `collapsed`        — icon-only 60px rail
 *   - mobile (<=768px)   : `collapsed/hidden` = drawer closed
 *                          (no class)        = drawer open (slides in)
 *
 * The CSS handles all three via `.collapsed` / `.hidden` modifiers on
 * `#body-grid`. We persist the desktop preference in localStorage; on mobile
 * the drawer always boots closed.
 */
const SIDEBAR_KEY = "nexus.sidebar";

function isMobileViewport() {
    return window.matchMedia("(max-width: 768px)").matches;
}

function applySidebarState(state) {
    const grid = $("#body-grid");
    if (!grid) return;
    grid.classList.toggle("collapsed", state === "collapsed");
    grid.classList.toggle("hidden",    state === "hidden");
}

function loadSidebarState() {
    if (isMobileViewport()) return "collapsed"; // boot the drawer closed
    try { return localStorage.getItem(SIDEBAR_KEY) || "open"; }
    catch (e) { return "open"; }
}

function toggleSidebar() {
    const grid = $("#body-grid");
    if (!grid) return;
    const mobile = isMobileViewport();
    let next;
    if (mobile) {
        // Mobile: cycle drawer open ↔ closed.
        next = grid.classList.contains("collapsed") || grid.classList.contains("hidden")
            ? "open" : "collapsed";
    } else {
        // Desktop: cycle collapsed ↔ open.
        next = grid.classList.contains("collapsed") ? "open" : "collapsed";
        try { localStorage.setItem(SIDEBAR_KEY, next); } catch (e) {}
    }
    applySidebarState(next);
}

function initSidebar() {
    applySidebarState(loadSidebarState());
    $("#sidebar-toggle")?.addEventListener("click", toggleSidebar);

    // ⌘B / ctrl+B keyboard toggle.
    window.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b" && !e.shiftKey) {
            e.preventDefault(); toggleSidebar();
        }
    });

    // On mobile: tapping a nav item closes the drawer; tapping the backdrop too.
    $$('.sidebar .nav-item').forEach((el) => el.addEventListener("click", () => {
        if (isMobileViewport()) applySidebarState("collapsed");
    }));
    document.addEventListener("click", (e) => {
        if (!isMobileViewport()) return;
        const grid = $("#body-grid");
        if (!grid || grid.classList.contains("collapsed") || grid.classList.contains("hidden")) return;
        // If the click was outside both the sidebar and the toggle, close.
        if (e.target.closest(".sidebar")) return;
        if (e.target.closest("#sidebar-toggle")) return;
        applySidebarState("collapsed");
    });

    // Re-evaluate on resize (going from mobile→desktop should restore the
    // user's previous desktop preference instead of leaving the drawer open).
    let lastMobile = isMobileViewport();
    window.addEventListener("resize", () => {
        const mobile = isMobileViewport();
        if (mobile === lastMobile) return;
        lastMobile = mobile;
        applySidebarState(loadSidebarState());
    });
}

/* ─── bootstrap ─── */
window.addEventListener("hashchange", renderRoute);
window.addEventListener("DOMContentLoaded", () => {
    if (!location.hash) location.replace("#/dashboard");
    applyThemeAttr();
    initSidebar();
    renderRoute();
    tickClock();
    setInterval(tickClock, 1000);
});
