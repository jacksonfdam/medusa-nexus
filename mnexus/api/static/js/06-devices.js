// ── auto-wired ES-module imports (phase B) ──
import { $, $$, attrTag, chip, escapeHtml, fmtAgo, getJSON, h, platformGlyph, sectionHeader } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";
import { projectTabs } from "./04-project-views.js";

/* ═══════════════════════════════════════════════════════════════════════════
 *  SCREEN — Devices (multi-device ADB manager)
 * ═══════════════════════════════════════════════════════════════════════════ */

const DEVICE_CONNECT_FLAVORS = [
    { key: "adb_server",      label: "ADB + ffmpeg",        impl: "server-side",   load: "medium", value: "high",   default: true },
    { key: "webusb_yaadb",    label: "WebUSB / ya-webadb",  impl: "browser-direct", load: "medium", value: "high",   default: false },
    { key: "webrtc_signaling",label: "WebRTC + helper app", impl: "phone-side app", load: "low",    value: "medium", default: false },
];

// Currently active connection flavor (drives the device-list source).
let _activeFlavor = "adb_server";

function view_devices() {
    return h`
    <div class="main">
      ${sectionHeader("D", "04 // INTAKE", "DEVICES")}
      <div class="devices-bar">
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <span class="muted small uppercase">connect via:</span>
          ${DEVICE_CONNECT_FLAVORS.map((f) => `
            <button type="button" class="chip ${_activeFlavor === f.key ? "low" : "info"}" data-flavor="${f.key}" title="${f.impl} · load=${f.load} · value=${f.value}" style="cursor:pointer;border-style:solid">
              ${_activeFlavor === f.key ? "● " : "○ "}${f.label}
            </button>`).join("")}
        </div>
        <span class="spacer"></span>
        <form id="connect-form" class="row" style="gap:8px;flex-wrap:nowrap">
          <div class="input" style="width:200px">
            <span class="prompt">tcp&gt;</span>
            <input id="connect-host" placeholder="192.168.1.42" autocomplete="off">
          </div>
          <div class="input" style="width:90px">
            <input id="connect-port" placeholder="5555" value="5555" autocomplete="off">
          </div>
          <button class="btn primary" type="submit">[ CONNECT ]</button>
        </form>
        <button class="btn" id="devices-refresh">[ REFRESH ]</button>
      </div>
      <div class="muted small" id="connect-status" style="min-height:16px"></div>
      <section class="panel">
        <div class="panel-head">
          <span>// CONNECTED DEVICES</span>
          <span class="spacer"></span>
          <span class="muted" id="devices-count">scanning…</span>
        </div>
        <div class="panel-body" id="devices-grid-host">
          <div class="empty-state">scanning…</div>
        </div>
      </section>
      <section class="panel" id="device-detail-panel" style="display:none">
        <div class="panel-head">
          <span id="device-detail-title">// DEVICE DETAIL</span>
          <span class="spacer"></span>
          <button class="btn" id="device-detail-close">[ CLOSE ]</button>
        </div>
        <div class="panel-body" id="device-detail-host"></div>
      </section>
    </div>`;
}

let _devicesPollTimer = null;
let _mirrorTimer = null;
let _activeSerial = null;

async function mount_devices() {
    await refreshDevices();
    clearInterval(_devicesPollTimer);
    _devicesPollTimer = setInterval(() => {
        if (location.hash.startsWith("#/devices")) refreshDevices();
        else { clearInterval(_devicesPollTimer); clearInterval(_mirrorTimer); }
    }, 4000);

    const form = $("#connect-form");
    if (form) form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const host = $("#connect-host").value.trim();
        const port = $("#connect-port").value.trim() || "5555";
        if (!host) return;
        const status = $("#connect-status");
        status.innerHTML = `<span style="color:var(--acid)">↑ adb connect ${host}:${port}…</span>`;
        try {
            const fd = new FormData();
            fd.append("host", host);
            fd.append("port", port);
            const r = await fetch("/v1/devices/connect", { method: "POST", body: fd });
            const j = await r.json();
            const ok = !j.output.toLowerCase().includes("failed") && !j.output.toLowerCase().includes("cannot");
            status.innerHTML = `<span style="color:var(--${ok ? "acid" : "sev-crit"})">${j.output}</span>`;
            await refreshDevices();
        } catch (e) {
            status.innerHTML = `<span style="color:var(--sev-crit)">${e.message}</span>`;
        }
    });

    const refreshBtn = $("#devices-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", refreshDevices);

    const closeBtn = $("#device-detail-close");
    if (closeBtn) closeBtn.addEventListener("click", () => closeDeviceDetail());

    // ── Connection-flavor chip click handlers ─────────────────────────────
    $$("[data-flavor]").forEach((chip) => chip.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const flavor = chip.dataset.flavor;
        if (flavor === _activeFlavor) return;

        if (flavor === "adb_server") {
            _activeFlavor = "adb_server";
            redrawFlavorChips();
            setConnectStatus("flavor: ADB + ffmpeg (server-side)", "var(--acid)");
            await refreshDevices();
            return;
        }

        if (flavor === "webusb_yaadb") {
            await activateWebUSB();
            return;
        }

        if (flavor === "webrtc_signaling") {
            showWebRTCInfo();
            return;
        }
    }));
}

function redrawFlavorChips() {
    $$("[data-flavor]").forEach((c) => {
        const k = c.dataset.flavor;
        const active = k === _activeFlavor;
        c.classList.toggle("low", active);
        c.classList.toggle("info", !active);
        const flavor = DEVICE_CONNECT_FLAVORS.find((f) => f.key === k);
        c.innerHTML = (active ? "● " : "○ ") + (flavor ? flavor.label : k);
    });
}

function setConnectStatus(text, color) {
    const status = $("#connect-status");
    if (status) {
        status.innerHTML = `<span style="color:${color || "var(--muted)"}">${text}</span>`;
    }
}

// ── WebUSB / ya-webadb path ─────────────────────────────────────────────
async function activateWebUSB() {
    if (!("usb" in navigator)) {
        setConnectStatus(
            "✕ this browser doesn't expose <code>navigator.usb</code> — try Chrome/Edge over HTTPS or localhost",
            "var(--sev-crit)",
        );
        return;
    }
    setConnectStatus("↑ requesting USB device — pick the phone in the browser prompt", "var(--acid)");
    try {
        // ADB USB interface signature on Android.
        const usbDev = await navigator.usb.requestDevice({
            filters: [
                { classCode: 0xFF, subclassCode: 0x42, protocolCode: 0x01 }, // ADB
                { classCode: 0xFF, subclassCode: 0x42, protocolCode: 0x03 }, // ADB v2
            ],
        });
        _activeFlavor = "webusb_yaadb";
        redrawFlavorChips();
        renderWebUSBPanel(usbDev);
    } catch (e) {
        // User cancelled the chooser, or no matching device.
        setConnectStatus(`✕ ${e.name === "NotFoundError" ? "no ADB-class USB device picked" : e.message}`, "var(--sev-high)");
    }
}

function renderWebUSBPanel(usbDev) {
    const host = $("#devices-grid-host");
    if (!host) return;
    const product = usbDev.productName || "(unknown)";
    const vendor = usbDev.manufacturerName || "(unknown)";
    const vid = usbDev.vendorId.toString(16).padStart(4, "0");
    const pid = usbDev.productId.toString(16).padStart(4, "0");
    host.innerHTML = `
      <div class="empty-state">
        <div style="font-size:18px;color:var(--acid);letter-spacing:3px;margin-bottom:14px">WEBUSB DEVICE PICKED</div>
        <div class="t-mono" style="text-align:left;display:inline-block">
          <div>vendor:    <span style="color:var(--cyan)">${vendor}</span> (0x${vid})</div>
          <div>product:   <span style="color:var(--cyan)">${product}</span> (0x${pid})</div>
          <div>serial:    <span style="color:var(--cyan)">${usbDev.serialNumber || "(none)"}</span></div>
        </div>
        <div class="muted small" style="margin-top:18px;max-width:560px;margin-left:auto;margin-right:auto">
          We have the USB handle. Driving ADB over WebUSB needs the
          <a href="https://github.com/yume-chan/ya-webadb" target="_blank" style="color:var(--magenta)">ya-webadb</a>
          library bundled into the SPA — that's tagged <b>iter 2</b>. For now we hand the handle back so you
          can confirm the path works; commands still flow through server-side ADB.
        </div>
        <div style="margin-top:14px"><button class="btn" id="webusb-back">[ ← BACK TO ADB SERVER ]</button></div>
      </div>`;
    const back = $("#webusb-back");
    if (back) back.addEventListener("click", async () => {
        _activeFlavor = "adb_server";
        redrawFlavorChips();
        await refreshDevices();
    });
    setConnectStatus(
        `✓ WebUSB picked: ${product} (0x${vid}/0x${pid}) — bundle ya-webadb to enable command flow`,
        "var(--acid)",
    );
}

// ── WebRTC signaling info ───────────────────────────────────────────────
function showWebRTCInfo() {
    const host = $("#devices-grid-host");
    if (!host) return;
    _activeFlavor = "webrtc_signaling";
    redrawFlavorChips();
    host.innerHTML = `
      <div class="empty-state">
        <div style="font-size:18px;color:var(--magenta);letter-spacing:3px;margin-bottom:14px">WEBRTC + HELPER APP</div>
        <div class="t-mono" style="text-align:left;display:inline-block;line-height:1.7">
          <div>1. companion app on the device (APK to be built) opens a WebRTC peer.</div>
          <div>2. nexus signals it via <code>ws://nexus:8765/v1/devices/webrtc/signal</code>.</div>
          <div>3. data channel ferries adb commands; video track ferries the screen.</div>
        </div>
        <div class="muted small" style="margin-top:18px;max-width:560px;margin-left:auto;margin-right:auto">
          Lowest server load (only signaling), works through NAT, but <b>requires a phone-side app</b> we
          haven't built yet. <span style="color:var(--magenta)">iter 2.</span>
        </div>
        <div style="margin-top:14px"><button class="btn" id="webrtc-back">[ ← BACK TO ADB SERVER ]</button></div>
      </div>`;
    const back = $("#webrtc-back");
    if (back) back.addEventListener("click", async () => {
        _activeFlavor = "adb_server";
        redrawFlavorChips();
        await refreshDevices();
    });
    setConnectStatus("flavor: WebRTC + helper app (iter 2 — informational only)", "var(--magenta)");
}

async function refreshDevices() {
    const host = $("#devices-grid-host");
    if (!host) return;
    const devices = await getJSON("/v1/devices").catch(() => []);
    $("#devices-count").textContent = `${devices.length} attached`;
    const navCount = $("#nav-devices-count");
    if (navCount) navCount.textContent = devices.length ? String(devices.length) : "";

    if (!devices.length) {
        host.innerHTML = `
          <div class="empty-state">
            <div style="font-size:18px;color:var(--magenta);letter-spacing:3px">NO DEVICES</div>
            <div class="muted small" style="margin-top:8px">plug a USB device with debugging on, or use <b>tcp&gt;</b> above to <code>adb connect &lt;host&gt;</code></div>
          </div>`;
        return;
    }

    host.innerHTML = `<div class="devices-grid">${devices.map(deviceCardHtml).join("")}</div>`;
    $$("[data-serial]").forEach((card) => {
        card.addEventListener("click", () => openDeviceDetail(card.dataset.serial, devices.find((d) => d.serial === card.dataset.serial)));
    });
}

function deviceCardHtml(d) {
    const ok = d.state === "device";
    const stateColor = ok ? "var(--acid)" : (d.state === "unauthorized" ? "var(--sev-high)" : "var(--sev-crit)");
    return `
    <div class="device-card ${d.serial === _activeSerial ? "active" : ""}" data-serial="${d.serial}">
      <div class="head">
        <span class="t-mono" style="font-weight:700;flex:1">${d.model || d.product || d.serial}</span>
        <span class="badge" style="color:${stateColor};border-color:${stateColor}">${d.state.toUpperCase()}</span>
      </div>
      <div class="muted small t-mono">${d.serial}</div>
      ${ok ? `
      <div class="grid">
        <span class="key">ANDROID</span><span class="val">${d.android_release || "?"} (SDK ${d.android_sdk || "?"})</span>
        <span class="key">ABI</span><span class="val">${d.abi || "?"}</span>
        <span class="key">SCREEN</span><span class="val">${d.screen_width || "?"}×${d.screen_height || "?"}</span>
        <span class="key">DEBUG</span><span class="val" style="color:var(--${d.debuggable === "1" ? "sev-high" : "muted"})">${d.debuggable === "1" ? "yes" : "no"}</span>
        <span class="key">FRIDA</span><span class="val" style="color:var(--${d.frida_server_running ? "acid" : d.frida_server_staged ? "sev-high" : "muted"})">${d.frida_server_running ? "running" : d.frida_server_staged ? "staged" : "—"}</span>
        <span class="key">BRAND</span><span class="val">${d.brand || d.manufacturer || "?"}</span>
      </div>` : ""}
    </div>`;
}

function openDeviceDetail(serial, d) {
    _activeSerial = serial;
    document.querySelectorAll(".device-card").forEach((c) => c.classList.toggle("active", c.dataset.serial === serial));
    const panel = $("#device-detail-panel");
    const host = $("#device-detail-host");
    const title = $("#device-detail-title");
    if (!panel || !host) return;
    panel.style.display = "";
    title.textContent = `// DEVICE :: ${d?.model || serial}`;

    const ok = d?.state === "device";
    if (!ok) {
        host.innerHTML = `
          <div class="empty-state">
            <div style="color:var(--sev-crit);font-size:18px">${d?.state?.toUpperCase() || "OFFLINE"}</div>
            <div class="muted small">authorize USB debugging on the device, or <code>adb kill-server && adb start-server</code></div>
          </div>`;
        return;
    }

    const w = d.screen_width || 1080;
    const h = d.screen_height || 2400;
    host.innerHTML = `
      <div class="device-detail">
        <div class="device-mirror" id="mirror">
          <div class="mirror-stage">
            <img id="mirror-img" alt="screen mirror" data-w="${w}" data-h="${h}" />
            <img id="mirror-img-b" alt="" aria-hidden="true" />
          </div>
          <div class="mirror-foot">
            <span>MIRROR · ${w}×${h}</span>
            <span>·</span>
            <span>mjpeg primary · poll fallback</span>
            <span class="spacer"></span>
            <span id="mirror-status" style="color:var(--acid)">connecting…</span>
          </div>
        </div>
        <div class="col">
          <section class="panel">
            <div class="panel-head">// QUICK ACTIONS</div>
            <div class="panel-body col">
              <div class="row" style="flex-wrap:wrap;gap:8px">
                <button class="btn primary" data-action="frida">[ START FRIDA ]</button>
                <button class="btn" data-action="tcpip">[ ADB OVER TCP ]</button>
                <button class="btn" data-action="reboot">[ REBOOT ]</button>
                <button class="btn" data-action="reboot-bootloader">[ → BOOTLOADER ]</button>
                <button class="btn" data-action="reboot-recovery">[ → RECOVERY ]</button>
                <button class="btn danger" data-action="disconnect">[ DISCONNECT ]</button>
              </div>
              <div class="col" style="gap:6px">
                <div class="muted small" style="letter-spacing:2px">// INSTALL FROM A SAVED PROJECT</div>
                <div class="row" style="gap:8px;align-items:center">
                  <select id="install-from-project" class="input" style="flex:1;padding:6px 10px"><option>loading projects…</option></select>
                  <button class="btn primary" id="install-from-project-btn">[ INSTALL ]</button>
                </div>
                <div class="muted small" style="margin-top:6px;letter-spacing:2px">// OR UPLOAD A FRESH APK</div>
                <div class="row" style="gap:8px;align-items:center">
                  <input type="file" id="install-file" accept=".apk" style="display:none">
                  <button class="btn" onclick="document.getElementById('install-file').click()">[ ↑ UPLOAD NEW APK ]</button>
                  <span id="install-status" class="muted small grow"></span>
                </div>
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-head">// KEY EVENTS · adb shell input keyevent</div>
            <div class="panel-body">
              <div class="key-grid">
                <button class="btn" data-key="3">HOME</button>
                <button class="btn" data-key="4">BACK</button>
                <button class="btn" data-key="187">RECENTS</button>
                <button class="btn" data-key="26">POWER</button>
                <button class="btn" data-key="24">VOL+</button>
                <button class="btn" data-key="25">VOL-</button>
                <button class="btn" data-key="82">MENU</button>
                <button class="btn" data-key="66">ENTER</button>
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="panel-head">// SHELL</div>
            <div class="panel-body col">
              <form id="shell-form" class="row" style="gap:8px">
                <div class="input grow">
                  <span class="prompt">$</span>
                  <input id="shell-input" placeholder="getprop ro.build.fingerprint" autocomplete="off">
                  <span class="cursor">_</span>
                </div>
                <button class="btn primary" type="submit">[ RUN ]</button>
              </form>
              <pre id="shell-out" class="code" style="max-height:240px"></pre>
            </div>
          </section>
        </div>
      </div>`;

    bindMirror(serial, w, h);
    bindActions(serial);
    bindKeys(serial);
    bindShell(serial);
    bindInstall(serial);
}

function bindMirror(serial, w, h) {
    const mirror = $("#mirror");
    const imgA = $("#mirror-img");          // primary
    const imgB = $("#mirror-img-b");        // backbuffer (polling fallback)
    if (!mirror || !imgA) return;
    const status = $("#mirror-status");
    const fps = 6;

    // ── 1. PRIMARY: MJPEG stream — browser renders multipart natively ────────
    // No JS polling, no <img> swap → no flicker, single TCP connection.
    let usingMjpeg = true;
    let pollTimer = null;
    let inFlight = false;
    let fails = 0;
    let active = 0;

    function setStatus(text, color) {
        if (!status) return;
        status.textContent = text;
        status.style.color = color || "var(--acid)";
    }

    imgA.style.opacity = "1";
    imgA.src = `/v1/devices/${encodeURIComponent(serial)}/screen.mjpeg?fps=${fps}&_=${Date.now()}`;
    setStatus(`live · mjpeg @ ${fps}fps`);
    hideMirrorError(mirror);

    // If no frame painted in 4s, assume mjpeg failed → fall back.
    const mjpegStallTimer = setTimeout(() => {
        if (imgA.naturalWidth === 0) imgA.dispatchEvent(new Event("error"));
    }, 4000);
    imgA.addEventListener("load", () => clearTimeout(mjpegStallTimer), { once: true });
    imgA.addEventListener("error", () => {
        if (!usingMjpeg) return;
        clearTimeout(mjpegStallTimer);
        setStatus("mjpeg unavailable → polling", "var(--sev-high)");
        startPolling();
    }, { once: true });

    // ── 2. FALLBACK: double-buffered PNG polling ─────────────────────────────
    async function pollOnce() {
        if (inFlight) return;            // skip overlapping ticks
        inFlight = true;
        try {
            const url = `/v1/devices/${encodeURIComponent(serial)}/screencap.png?t=${Date.now()}`;
            const r = await fetch(url, { cache: "no-store" });
            if (!r.ok) {
                fails++;
                if (fails > 2) {
                    setStatus("stalled · polling", "var(--sev-crit)");
                    showMirrorError(mirror, await safeJSON(r));
                }
                return;
            }
            const blob = await r.blob();
            const buffers = [imgA, imgB];
            const next = buffers[1 - active];
            if (!next) {
                // Backbuffer not present → just swap on the primary (might flicker).
                const obj0 = URL.createObjectURL(blob);
                const old0 = imgA.dataset.lastUrl;
                imgA.src = obj0;
                if (old0) URL.revokeObjectURL(old0);
                imgA.dataset.lastUrl = obj0;
            } else {
                const oldUrl = next.dataset.lastUrl;
                const obj = URL.createObjectURL(blob);
                next.src = obj;
                try { await next.decode(); } catch { /* swap anyway */ }
                buffers[active].style.opacity = "0";
                next.style.opacity = "1";
                next.dataset.lastUrl = obj;
                if (oldUrl) URL.revokeObjectURL(oldUrl);
                active = 1 - active;
            }
            fails = 0;
            const path = r.headers.get("X-MNexus-Path") || "?";
            setStatus(`live · poll · ${path}`);
            hideMirrorError(mirror);
        } catch (e) {
            fails++;
            if (fails > 2) {
                setStatus("stalled · polling", "var(--sev-crit)");
                showMirrorError(mirror, { error: "network", detail: e.message });
            }
        } finally {
            inFlight = false;
        }
    }

    function startPolling() {
        usingMjpeg = false;
        pollOnce();
        clearInterval(pollTimer);
        pollTimer = setInterval(() => {
            if (!location.hash.startsWith("#/devices")) { clearInterval(pollTimer); return; }
            if (_activeSerial !== serial) { clearInterval(pollTimer); return; }
            pollOnce();
        }, 800);
        _mirrorTimer = pollTimer;
    }

    // ── 3. tap-to-click ──────────────────────────────────────────────────────
    function tapHandler(ev) {
        const target = ev.currentTarget;
        const rect = target.getBoundingClientRect();
        const xRatio = (ev.clientX - rect.left) / rect.width;
        const yRatio = (ev.clientY - rect.top) / rect.height;
        const x = Math.round(xRatio * w);
        const y = Math.round(yRatio * h);
        const fd = new FormData(); fd.append("x", x); fd.append("y", y);
        fetch(`/v1/devices/${encodeURIComponent(serial)}/tap`, { method: "POST", body: fd });
    }
    imgA.addEventListener("click", tapHandler);
    if (imgB) imgB.addEventListener("click", tapHandler);
}

async function safeJSON(response) {
    try { return await response.json(); } catch { return { error: `HTTP ${response.status}`, detail: response.statusText }; }
}

function showMirrorError(mirror, payload) {
    if (!mirror) return;
    let banner = mirror.querySelector(".mirror-error");
    if (!banner) {
        banner = document.createElement("div");
        banner.className = "mirror-error";
        banner.style.cssText = "padding:14px;background:#1a0008;border-top:1px solid var(--border-crit);color:var(--sev-crit);font-size:11px;line-height:1.55;display:flex;flex-direction:column;gap:6px";
        mirror.appendChild(banner);
    }
    const detail = payload?.detail || payload || {};
    const lines = [];
    if (typeof detail === "string") lines.push(detail);
    else {
        if (detail.error) lines.push(`<b>${detail.error}</b>`);
        if (detail.exec_out) lines.push(`exec-out: ${detail.exec_out}`);
        if (detail.temp_file) lines.push(`temp-file: ${detail.temp_file}`);
        if (detail.hint) lines.push(`<span style="color:var(--magenta)">→ ${detail.hint}</span>`);
    }
    banner.innerHTML = `
      <div>screencap stalled — diagnostics:</div>
      <div style="font-family:var(--mono)">${lines.join("<br>")}</div>
      <div><a href="/v1/devices/${encodeURIComponent(_activeSerial)}/screencap-debug" target="_blank" style="color:var(--cyan)">[ open /screencap-debug ]</a></div>`;
}

function hideMirrorError(mirror) {
    const banner = mirror?.querySelector(".mirror-error");
    if (banner) banner.remove();
}

function bindActions(serial) {
    $$("[data-action]").forEach((btn) => btn.addEventListener("click", async () => {
        const a = btn.dataset.action;
        const orig = btn.textContent;
        btn.textContent = "[ … ]";
        try {
            if (a === "frida") {
                const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/frida-server`, { method: "POST" });
                const j = await r.json();
                btn.textContent = j.running ? `[ FRIDA pid=${j.pid} ]` : "[ FAILED ]";
                btn.style.color = j.running ? "var(--acid)" : "var(--sev-crit)";
            } else if (a === "tcpip") {
                const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/tcpip`, { method: "POST", body: new FormData() });
                const j = await r.json();
                btn.textContent = `[ TCP/IP :${j.port} ]`;
            } else if (a === "reboot" || a === "reboot-bootloader" || a === "reboot-recovery") {
                const fd = new FormData();
                if (a === "reboot-bootloader") fd.append("mode", "bootloader");
                if (a === "reboot-recovery") fd.append("mode", "recovery");
                await fetch(`/v1/devices/${encodeURIComponent(serial)}/reboot`, { method: "POST", body: fd });
                btn.textContent = "[ REBOOTING ]"; btn.style.color = "var(--sev-high)";
            } else if (a === "disconnect") {
                await fetch(`/v1/devices/${encodeURIComponent(serial)}/disconnect`, { method: "POST" });
                closeDeviceDetail(); refreshDevices();
            }
        } catch (e) {
            btn.textContent = "[ ERROR ]"; btn.style.color = "var(--sev-crit)";
            console.error(e);
        }
        setTimeout(() => { if (btn.textContent.includes("…") || btn.textContent === "[ ERROR ]") btn.textContent = orig; }, 2500);
    }));
}

function bindKeys(serial) {
    $$("[data-key]").forEach((btn) => btn.addEventListener("click", async () => {
        const fd = new FormData(); fd.append("keycode", btn.dataset.key);
        btn.style.background = "var(--bg-accent-panel)";
        await fetch(`/v1/devices/${encodeURIComponent(serial)}/key`, { method: "POST", body: fd });
        setTimeout(() => { btn.style.background = ""; }, 200);
    }));
}

function bindShell(serial) {
    const form = $("#shell-form"); if (!form) return;
    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const cmd = $("#shell-input").value.trim(); if (!cmd) return;
        const out = $("#shell-out");
        out.textContent += `$ ${cmd}\n`;
        const fd = new FormData(); fd.append("cmd", cmd);
        try {
            const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/shell`, { method: "POST", body: fd });
            const j = await r.json();
            out.textContent += (j.output || "(no output)") + "\n";
        } catch (e) {
            out.textContent += `<error: ${e.message}>\n`;
        }
        out.scrollTop = out.scrollHeight;
        $("#shell-input").value = "";
    });
}

async function bindInstall(serial) {
    const status = $("#install-status");
    const setStatus = (text, color) => { if (status) { status.textContent = text; status.style.color = color || ""; } };

    // ── 1. Populate the saved-projects dropdown from /v1/projects ──
    const select = $("#install-from-project");
    if (select) {
        const projects = await getJSON("/v1/projects").catch(() => []);
        if (!projects.length) {
            select.innerHTML = `<option value="">— no saved projects yet (upload one at /#/scan) —</option>`;
            select.disabled = true;
        } else {
            select.disabled = false;
            select.innerHTML = `<option value="">— pick a saved project —</option>` +
                projects.map((p) => {
                    const label = `${p.package_name || p.name || p.id}` +
                        (p.version_name ? ` v${p.version_name}` : "") +
                        ` · ${p.id}`;
                    return `<option value="${p.id}">${label}</option>`;
                }).join("");
        }
    }

    // ── 2. Install-from-project button ──
    const installBtn = $("#install-from-project-btn");
    if (installBtn) installBtn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const projectId = select?.value;
        if (!projectId) { setStatus("pick a project from the dropdown first", "var(--sev-high)"); return; }
        setStatus(`pushing ${projectId} via adb install -r…`, "var(--acid)");
        installBtn.disabled = true;
        try {
            const fd = new FormData(); fd.append("project_id", projectId);
            const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/install-project`, { method: "POST", body: fd });
            const j = await r.json().catch(() => ({}));
            if (!r.ok) {
                const detail = j.detail || j;
                setStatus(`✕ ${typeof detail === "string" ? detail : (detail.error || "install failed")}`, "var(--sev-crit)");
                return;
            }
            setStatus(
                j.success
                    ? `✓ installed ${j.package} v${j.version} (${j.apk})`
                    : `✕ ${(j.output || "").split("\n").slice(-2).join(" ").trim() || "adb refused"}`,
                j.success ? "var(--acid)" : "var(--sev-crit)",
            );
        } catch (e) {
            setStatus(`✕ ${e.message}`, "var(--sev-crit)");
        } finally {
            installBtn.disabled = false;
        }
    });

    // ── 3. Fresh-file upload (existing path, kept as a secondary option) ──
    const input = $("#install-file");
    if (input) input.addEventListener("change", async () => {
        const f = input.files?.[0]; if (!f) return;
        setStatus(`installing ${f.name} (${fmtBytes(f.size)})…`, "var(--acid)");
        const fd = new FormData(); fd.append("file", f);
        try {
            const r = await fetch(`/v1/devices/${encodeURIComponent(serial)}/install`, { method: "POST", body: fd });
            const j = await r.json();
            setStatus(
                j.success ? "✓ installed" : `✕ ${(j.output || "").split("\n").slice(-2).join(" ")}`,
                j.success ? "var(--acid)" : "var(--sev-crit)",
            );
        } catch (e) {
            setStatus(`✕ ${e.message}`, "var(--sev-crit)");
        }
    });
}

function closeDeviceDetail() {
    _activeSerial = null;
    clearInterval(_mirrorTimer);
    const panel = $("#device-detail-panel");
    if (panel) panel.style.display = "none";
    document.querySelectorAll(".device-card").forEach((c) => c.classList.remove("active"));
}

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


export { _exports_panel, bar, mount_devices, mount_project_overview, mount_project_static, view_devices };
