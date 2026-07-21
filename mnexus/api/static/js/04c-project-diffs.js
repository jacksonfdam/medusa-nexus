// ── auto-wired ES-module imports ──
import { $, chip, escapeHtml, getJSON, h } from "./01-core.js";
import { projectTabs } from "./04a-project-views.js";
import { view_report } from "./05-misc-screens.js";
import { _exports_panel } from "./06b-project-overview-mounts.js";

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


export { mount_project_findings_diff, mount_project_manifest_diff, view_project_findings_diff, view_project_manifest_diff, view_project_network, view_project_report };
