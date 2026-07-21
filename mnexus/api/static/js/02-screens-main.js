// ── auto-wired ES-module imports (phase B) ──
import { $, $$, chip, classifyRisk, getJSON, h, platformGlyph, sectionHeader } from "./01-core.js";

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


export { fmtBytes, mount_dashboard, mount_projects, mount_scan, mount_scan_after_upload_wiring, view_dashboard, view_projects, view_scan };
