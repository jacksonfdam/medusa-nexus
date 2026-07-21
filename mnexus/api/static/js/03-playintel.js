// ── auto-wired ES-module imports ──
import { $, $$, attrTag, escapeHtml, h, sectionHeader } from "./01-core.js";

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
    const rows = findings.map((f) => `
        <tr style="border-top:1px solid var(--border)">
          <td class="t-mono" style="padding:6px 8px;color:${sevColor(f.severity)};text-transform:uppercase;white-space:nowrap">${escapeHtml(f.severity)}</td>
          <td style="padding:6px 8px">
            <div>${escapeHtml(f.title)} ${attrTag(f)}</div>
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


export { mount_play_accounts, mount_play_scan, view_play_accounts, view_play_scan };
