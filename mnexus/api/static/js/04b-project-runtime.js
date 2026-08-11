// ── auto-wired ES-module imports ──
import { $, $$, escapeHtml, getJSON, h, pollingScope } from "./01-core.js";
import { projectTabs } from "./04a-project-views.js";

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
          <pre id="rt-script" style="margin:0;padding:12px;background:var(--bg-code);color:var(--cyan);font-family:inherit;font-size:11px;max-height:340px;overflow:auto;white-space:pre">// generated Frida script will appear here</pre>
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
          <div class="muted small" id="rt-mango-dl-out" style="display:none;padding:6px 8px;background:var(--bg-code);border:1px solid var(--border);border-radius:2px;white-space:pre-wrap;font-family:inherit"></div>

          <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted small uppercase" style="letter-spacing:2px;width:110px">decode flag:</span>
            <input id="rt-mango-flag" class="input t-mono" placeholder="0x10000004 · 268435460 · 0b1010" style="flex:1;min-width:200px">
            <button class="btn primary" id="rt-mango-flag-go" style="white-space:nowrap">[ DECODE ]</button>
          </div>
          <div id="rt-mango-flag-out" class="muted small" style="display:none;padding:6px 8px;background:var(--bg-code);border:1px solid var(--border);border-radius:2px"></div>

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
          <div id="rt-mango-patch-out" class="muted small" style="display:none;padding:6px 8px;background:var(--bg-code);border:1px solid var(--border);border-radius:2px;white-space:pre-wrap"></div>

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
            <div id="rt-ipa-patch-out" class="muted small" style="display:none;padding:6px 8px;background:var(--bg-code);border:1px solid var(--border);border-radius:2px;white-space:pre-wrap;font-family:'Courier Prime',monospace;max-height:200px;overflow:auto"></div>
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


export { mount_project_runtime, view_project_runtime };
