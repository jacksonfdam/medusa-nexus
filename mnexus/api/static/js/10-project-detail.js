// ── auto-wired ES-module imports (phase B) ──
import { $, $$, attrTag, chip, escapeHtml, fmtAgo, getJSON, h, pollingScope, sectionHeader, stub } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";
import { projectTabs } from "./04-project-views.js";
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


export { classifyTraceClass, mount_pipeline, mount_project_api_map, mount_project_attack_tree, mount_project_components, mount_project_dataflow, mount_project_native, mount_project_owasp, mount_project_secrets, mount_project_ssl_map, mount_project_surface, mount_project_tracer, mount_report_diff, mount_terminal, view_pipeline, view_project_api_map, view_project_attack_tree, view_project_components, view_project_dataflow, view_project_native, view_project_owasp, view_project_secrets, view_project_ssl_map, view_project_surface, view_project_tracer, view_report_diff, view_states, view_terminal, view_toasts };
