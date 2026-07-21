// ── auto-wired ES-module imports ──
import { $, $$, attrTag, chip, escapeHtml, fmtAgo, getJSON, h, platformGlyph } from "./01-core.js";
import { projectTabs } from "./04a-project-views.js";

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
            ${attrTag(f)}
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


export { _exports_panel, bar, mount_project_overview, mount_project_static };
