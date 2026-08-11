// ── auto-wired ES-module imports ──
import { $, $$, escapeHtml, getJSON, h, onTeardown, sectionHeader } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";
import { deviceTabs, fillDeviceStatusStrip } from "./04a-project-views.js";

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
        <div class="panel-body" id="cap-body" style="display:flex;align-items:center;justify-content:center;min-height:380px;background:var(--bg-code)">
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
    // keep-alive: auto-refresh survives tab switches, reaped on tab close.
    onTeardown(() => { if (timer) clearInterval(timer); });
}


export { mount_device_files, mount_device_logcat, mount_device_screen, mount_device_shell, renderKeycodeButtons, view_device_files, view_device_logcat, view_device_screen, view_device_shell };
