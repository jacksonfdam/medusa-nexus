// ── auto-wired ES-module imports ──
import { $, $$, chip, getJSON, h, onTeardown, sectionHeader } from "./01-core.js";
import { fmtBytes } from "./02-screens-main.js";

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
    _devicesPollTimer = setInterval(refreshDevices, 4000);
    // keep-alive: the device poll + any mirror die when the /devices tab is
    // closed, not when you navigate away — the mirror stays warm in the pool.
    onTeardown(() => { clearInterval(_devicesPollTimer); clearInterval(_mirrorTimer); });

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
            // keep-alive: stop mirroring only when the selected device changes;
            // switching tabs leaves the stream warm (reaped on tab close).
            if (_activeSerial !== serial) { clearInterval(pollTimer); return; }
            pollOnce();
        }, 800);
        _mirrorTimer = pollTimer;
        onTeardown(() => clearInterval(pollTimer));
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


export { mount_devices, view_devices };
