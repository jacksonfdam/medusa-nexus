// ── auto-wired ES-module imports ──
import { $, $$, escapeHtml, getJSON } from "./01-core.js";
import { bindThemePicker } from "./05-misc-screens.js";

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

    // Cache the project once so template-switching is instant. The
    // network round-trip only happens on mount or when the project id
    // changes (currently never inside this screen).
    let cachedProject = null;
    if (targetId) {
        try { cachedProject = await getJSON(`/v1/projects/${encodeURIComponent(targetId)}`); }
        catch (e) { cachedProject = { _error: e.message }; }
    }

    function renderPreview() {
        if (!preview) return;
        if (!targetId) {
            preview.innerHTML = `<div class="empty-state"><span class="muted small uppercase">no project picked yet</span></div>`;
            return;
        }
        if (cachedProject && cachedProject._error) {
            preview.innerHTML = `<div class="empty-state"><span style="color:var(--sev-crit)">failed to load project ${targetId}: ${cachedProject._error}</span></div>`;
            return;
        }
        const project = cachedProject || {};
        const findings = (project.attack_surface?.findings || []);
        const order = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
        const sorted = findings
            .filter((f) => f.remediation && f.remediation.trim())
            .sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));

        if (previewHead) {
            previewHead.textContent = `// PREVIEW · ${project.package_name} v${project.version_name} · ${findings.length} findings · ${activeTemplate.toUpperCase()}`;
        }

        const header = `
          <div style="font-size:20px;color:var(--cyan);font-weight:700;letter-spacing:2px">MEDUSA NEXUS // ${activeTemplate.toUpperCase().replace("-", " ")} ASSESSMENT</div>
          <div class="muted small">target: ${project.package_name} v${project.version_name} · SHA-256 ${(project.apk_sha256 || "").slice(0, 16)}… · ${(project.created_at || "").slice(0, 10)}</div>
          <div class="gradient-underline"></div>`;

        const sevSummary = Object.entries(project.findings_by_severity || {})
            .filter(([, n]) => n)
            .map(([sev, n]) => `${n} ${sev}`).join(", ") || "no findings";

        const sevToCls = (sev) => sev === "critical" ? "crit" : sev === "medium" ? "med" : sev;

        let body = "";
        if (activeTemplate === "executive") {
            // C-suite cut: numbers + 3-line "what to do today", no code.
            const top3 = sorted.slice(0, 3);
            body = `
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--magenta)">§ 01 · RISK POSTURE</div>
              <div style="font-size:32px;color:var(--cyan);font-weight:700">Risk ${(project.risk_score ?? 0).toFixed(1)}<span class="muted small" style="font-size:14px"> / 100</span></div>
              <div class="muted">${sevSummary}.</div>
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--acid);margin-top:8px">§ 02 · TOP 3 — ACT THIS SPRINT</div>
              ${top3.length ? top3.map((f, i) => {
                  const cls = sevToCls((f.severity || "info").toLowerCase());
                  return `<div class="row" style="align-items:flex-start;gap:10px"><span class="chip ${cls}">${cls.toUpperCase()}</span><div><b>${String(i + 1).padStart(2, "0")} · ${escapeHtml(f.title)}</b></div></div>`;
              }).join("") : `<div class="muted small">no high-severity findings.</div>`}
              <div class="muted small">§ 03 · BUSINESS IMPACT · § 04 · REGULATORY EXPOSURE · § 05 · ROADMAP — generated on export</div>`;
        } else if (activeTemplate === "owasp-matrix") {
            // MASVS compliance grid: every finding bucketed by MASVS control.
            const byMasvs = {};
            findings.forEach((f) => {
                const key = f.masvs || "uncategorized";
                (byMasvs[key] ||= []).push(f);
            });
            const rows = Object.entries(byMasvs).sort(([a], [b]) => a.localeCompare(b));
            body = `
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--magenta)">§ 01 · OWASP MASVS MATRIX</div>
              <div class="muted small">${rows.length} control(s) hit · ${findings.length} finding(s) total</div>
              <table style="width:100%;border-collapse:collapse;margin-top:6px">
                <thead><tr style="border-bottom:1px solid var(--border)">
                  <th class="muted small uppercase" style="text-align:left;padding:4px 8px">MASVS</th>
                  <th class="muted small uppercase" style="text-align:right;padding:4px 8px">findings</th>
                  <th class="muted small uppercase" style="text-align:left;padding:4px 8px">worst</th>
                </tr></thead>
                <tbody>
                ${rows.map(([k, fs]) => {
                    const worst = fs.map((f) => (f.severity || "info").toLowerCase())
                        .sort((a, b) => (order[a] ?? 9) - (order[b] ?? 9))[0] || "info";
                    return `<tr style="border-top:1px solid var(--border)">
                      <td class="t-mono" style="padding:4px 8px">${escapeHtml(k)}</td>
                      <td class="t-mono" style="padding:4px 8px;text-align:right">${fs.length}</td>
                      <td class="t-mono" style="padding:4px 8px;color:var(--sev-${worst});text-transform:uppercase">${worst}</td>
                    </tr>`;
                }).join("")}
                </tbody>
              </table>
              <div class="muted small">§ 02 · CONTROL-BY-CONTROL EVIDENCE — generated on export</div>`;
        } else if (activeTemplate === "diff") {
            // Diff template needs a baseline; show the picker hint.
            body = `
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--magenta)">§ 01 · DIFF SCOPE</div>
              <div class="muted">Pick a baseline project under <a href="#/projects">/projects</a> and pass <code>--against PRJ-XXXX</code> on scan, or use the per-project <b>findings-diff</b> tab.</div>
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--acid);margin-top:8px">§ 02 · CURRENT SURFACE</div>
              <div>Risk ${(project.risk_score ?? 0).toFixed(1)}/100 · ${sevSummary}.</div>
              <div class="muted small">§ 03 · NEW vs RESOLVED · § 04 · SEVERITY ESCALATIONS — populated when a baseline is set</div>`;
        } else {
            // technical (default): full mitigation playbook.
            const top = sorted.slice(0, 8);
            body = `
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--magenta)">§ 01 · EXECUTIVE SUMMARY</div>
              <div>Risk ${(project.risk_score ?? 0).toFixed(1)}/100. ${sevSummary}.</div>
              <div class="panel-head" style="background:transparent;border:0;padding:0;color:var(--acid)">§ 02 · MITIGATION PLAYBOOK — mandatory section</div>
              <div class="mitigation">
                ${top.length ? top.map((f) => {
                    const cls = sevToCls((f.severity || "info").toLowerCase());
                    const firstLine = f.remediation.split("\n").find((l) => l.trim()) || "";
                    return `<div class="row" style="align-items:flex-start;gap:10px"><span class="chip ${cls}">${cls.toUpperCase()}</span><div><b>${f.id} · ${escapeHtml(f.title)}</b><br>→ ${escapeHtml(firstLine)}</div></div>`;
                }).join("") : `<div class="muted small">no actionable findings yet — run static engines.</div>`}
              </div>
              <div class="muted small">§ 03 · FINDINGS DETAIL · § 04 · OWASP MASVS COMPLIANCE MATRIX · § 05 · EVIDENCE PACKAGE · § 06 · REPRO STEPS</div>`;
        }

        preview.innerHTML = header + body;
    }

    renderPreview();

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
        // Repaint the preview pane so the body actually reflects the
        // newly-selected template — the whole point of clicking it.
        renderPreview();
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


export { mount_finding_detail, mount_recipes, mount_report, mount_settings };
