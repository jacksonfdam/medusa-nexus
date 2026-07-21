// ── auto-wired ES-module imports ──
import { $, $$, attrTag, chip, escapeHtml, getJSON, h, sectionHeader, stub } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";
import { projectTabs } from "./04a-project-views.js";
import { renderRoute } from "./11-router.js";

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
    // Live spinner state on the clicked button because the workspace
    // walk can take a few seconds on release APKs and a dead-looking
    // button is exactly the "clicked twice, wondered if broken" UX.
    const btn = document.querySelector(`.tab[onclick*="projectChromeAttribute('${id}')"]`);
    const origLabel = btn ? btn.textContent : null;
    const origColor = btn ? btn.style.color : null;
    if (btn) {
        btn.disabled = true;
        btn.textContent = "⌖ attributing…";
        btn.style.color = "var(--magenta)";
    }
    try {
        const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/attribute`, { method: "POST" });
        const body = await r.json().catch(() => ({}));
        if (!r.ok) {
            if (btn) {
                btn.textContent = "⌖ FAILED";
                btn.style.color = "var(--sev-high)";
            }
            await confirmModal({
                title: `✗ Attribution failed (${r.status})`,
                body: JSON.stringify(body, null, 2).slice(0, 400),
                okLabel: "OK", okStyle: "primary", cancelLabel: null,
            });
            return;
        }
        if (btn) {
            btn.textContent = `✓ ${body.newly_attributed} tagged`;
            btn.style.color = "var(--acid)";
        }
        await confirmModal({
            title: `⌖ Attribution done — ${body.attributed_after}/${body.total_findings} findings tagged`,
            body: `<code>${body.newly_attributed}</code> newly attributed · <code>${body.attributed_before}</code> already had an owner.\n\nReloading the view so the chips show up.`,
            okLabel: "OK", okStyle: "primary", cancelLabel: null,
        });
        setTimeout(() => { renderRoute(); }, 200);
    } finally {
        // Restore the label ~2s later — long enough for the user to see
        // the outcome, short enough that the ATTRIBUTE button reads
        // normal by the time they look for it again.
        setTimeout(() => {
            if (btn) {
                btn.disabled = false;
                if (origLabel) btn.textContent = origLabel;
                if (origColor !== null) btn.style.color = origColor;
            }
        }, 2000);
    }
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
            <div class="head">${chip((f.severity || "info").toLowerCase())}<span class="tag">${f.id}</span>${attrTag(f)}<span class="spacer"></span><span class="tag">[${f.source_engine || "?"}]</span></div>
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
            <div class="head">${chip(f.severity)}<span class="tag">${f.id}</span>${attrTag(f)}<span class="spacer"></span><span class="tag">[${f.source_engine}]</span></div>
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

/* SCREEN 15 — API Endpoint Map */

export { classifyTraceClass, mount_project_components, mount_project_native, mount_project_secrets, mount_project_tracer, projectChrome, view_project_components, view_project_native, view_project_secrets, view_project_tracer };
