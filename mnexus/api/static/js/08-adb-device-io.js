// ── auto-wired ES-module imports (phase B) ──
import { $, $$, escapeHtml, getJSON, h, sectionHeader } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";
import { deviceTabs, fillDeviceStatusStrip } from "./04-project-views.js";

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
const NEXUS_ADB = window.NEXUS_ADB; // module-local alias for the window global

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


export { mount_adb, mount_device_files, mount_device_logcat, mount_device_screen, mount_device_shell, view_adb, view_device_files, view_device_logcat, view_device_screen, view_device_shell };
