// ── auto-wired ES-module imports ──
import { $, $$, escapeHtml, getJSON } from "./01-core.js";
import { fillDeviceStatusStrip } from "./04a-project-views.js";

async function mount_device_pull() {
    const info = await getJSON("/v1/device/info").catch(() => ({connected: false, reason: "network error"}));
    const badgeRoot = $(".row .badge");
    if (badgeRoot) {
        badgeRoot.innerHTML = info.connected
            ? `<span class="dot">●</span>${info.model || "device"} · android ${info.android_release || "?"}`
            : `<span class="dot">●</span>NO DEVICE`;
        badgeRoot.classList.toggle("connected", info.connected);
    }

    const panel = $(".panel");
    if (!panel) return;
    const head = panel.querySelector(".panel-head");
    const body = panel.querySelector(".panel-body");

    if (!info.connected) {
        head.innerHTML = `// PACKAGES`;
        body.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit);font-size:20px;letter-spacing:3px">NO DEVICE CONNECTED</div><div class="muted">${info.reason || ""}</div><div class="muted small" style="margin-top:12px">plug a device, authorize USB debugging, then reload this screen.</div></div>`;
        return;
    }

    // Cached per-scope so flipping between 3RD/ALL/SYSTEM doesn't re-shell.
    const cache = {};
    let activeScope = "3rd";
    let activeFilter = "";

    const renderTable = (pkgs) => {
        const filter = activeFilter.toLowerCase();
        const filtered = filter ? pkgs.filter((p) => p.package.toLowerCase().includes(filter)) : pkgs;
        head.innerHTML = `// PACKAGES · <span style="color:var(--cyan)">${filtered.length}</span>${filter ? ` of ${pkgs.length}` : ""} · scope <span style="color:var(--acid)">${activeScope}</span>${info.abi ? ` · ${info.abi}` : ""}`;
        if (!filtered.length) {
            body.innerHTML = `<div class="empty-state">no packages match — try a different filter or switch scope to ALL.</div>`;
            return;
        }
        // Render the entire matched set. On a Samsung that's ~600 rows of
        // bare-DOM; well within budget. Virtualisation can land when someone
        // actually hits a flagship Android device with > 2k packages.
        body.innerHTML = `
            <div class="table-hdr" style="grid-template-columns: 1fr 200px">
                <span>PACKAGE</span><span></span>
            </div>` +
            filtered.map(({ package: pkg }) => `
                <div class="table-row" style="grid-template-columns: 1fr 200px">
                    <span class="t-mono">${escapeHtml(pkg)}</span>
                    <span style="text-align:right"><button class="btn primary" data-pull="${escapeHtml(pkg)}" style="padding:4px 10px;white-space:nowrap">[ PULL ]</button></span>
                </div>`).join("");
        bindPullButtons();
    };

    const fetchScope = async (scope) => {
        if (cache[scope] !== undefined) return cache[scope];
        body.innerHTML = `<div class="empty-state"><span class="muted small uppercase">listing ${scope === "3rd" ? "third-party" : scope} packages…</span></div>`;
        const pkgs = await getJSON(`/v1/device/packages?scope=${encodeURIComponent(scope)}`).catch(() => []);
        cache[scope] = pkgs;
        return pkgs;
    };

    const reloadActive = async () => renderTable(await fetchScope(activeScope));

    // Scope toggle. data-scope buttons highlight the active one.
    $$('[data-scope]').forEach((btn) => btn.addEventListener("click", async () => {
        activeScope = btn.dataset.scope;
        $$('[data-scope]').forEach((b) => b.classList.toggle("primary", b === btn));
        await reloadActive();
    }));

    // Live search — debounce so the table doesn't thrash on every keystroke.
    const filterInput = $("#pull-filter");
    let debounce = null;
    if (filterInput) filterInput.addEventListener("input", () => {
        activeFilter = filterInput.value || "";
        clearTimeout(debounce);
        debounce = setTimeout(reloadActive, 120);
    });

    await reloadActive();
}

function bindPullButtons() {
    $$("[data-pull]").forEach((btn) => btn.addEventListener("click", async () => {
        const pkg = btn.dataset.pull;
        btn.textContent = "[ PULLING… ]";
        btn.disabled = true;
        try {
            const fd = new FormData(); fd.append("package", pkg);
            const r = await fetch("/v1/device/pull", { method: "POST", body: fd });
            const j = await r.json();
            if (!r.ok) throw new Error(j.detail || r.statusText);

            if (j.ingest_error) {
                // Pulled files OK but pipeline blew up — keep the analyst informed
                // rather than pretending it worked.
                btn.textContent = "[ INGEST FAILED ]";
                btn.style.color = "var(--sev-crit)";
                btn.title = j.ingest_error;
                return;
            }
            if (!j.project_id) {
                // ingest=false escape hatch or some other reason — just file pull.
                btn.textContent = `[ PULLED ${j.count} ]`;
                btn.style.color = "var(--acid)";
                return;
            }

            // Auto-route to the freshly-ingested (or deduped) project.
            const label = j.dedup ? `[ ✓ ALREADY SCANNED — OPEN ${j.project_id} ]`
                                  : `[ ✓ INGESTED — OPEN ${j.project_id} ]`;
            btn.textContent = label;
            btn.style.color = j.dedup ? "var(--magenta)" : "var(--acid)";
            btn.disabled = false;
            btn.onclick = () => { location.hash = `#/project/${j.project_id}/overview`; };
            // Short auto-route so the user doesn't have to click twice.
            setTimeout(() => { if (location.hash.startsWith("#/device/pull")) location.hash = `#/project/${j.project_id}/overview`; }, 1500);
        } catch (e) {
            btn.textContent = `[ FAILED ]`;
            btn.style.color = "var(--sev-crit)";
            btn.title = e.message || String(e);
        }
    }));
}

async function mount_device_bridge() {
    fillDeviceStatusStrip();
    const info = await getJSON("/v1/device/info/full").catch(() => ({connected: false, reason: "network error"}));
    const badge = $("#bridge-badge");
    if (badge) {
        const ok = !!info.connected;
        badge.classList.toggle("connected", ok);
        badge.classList.toggle("scanning", !ok);
        badge.innerHTML = `<span class="dot">●</span>${ok ? "CONNECTED" : "NO DEVICE"}`;
    }

    const devicePanel = $("#bridge-info");
    if (!info.connected) {
        if (devicePanel) devicePanel.innerHTML = `<div class="empty-state"><div style="color:var(--sev-crit);font-size:18px">NO DEVICE</div><div class="muted small">${info.reason || ""}</div></div>`;
        const empty = '<div class="muted small">— device offline —</div>';
        if ($("#bridge-battery")) $("#bridge-battery").innerHTML = empty;
        if ($("#bridge-memory")) $("#bridge-memory").innerHTML = empty;
        if ($("#bridge-storage")) $("#bridge-storage").innerHTML = empty;
    } else if (devicePanel) {
        const row = (label, val, color) => `<div class="row"><span class="muted small" style="width:160px">${label}</span><span class="t-mono"${color ? ` style="color:${color}"` : ""}>${val || "—"}</span></div>`;
        const debuggable = info.debuggable === "1";
        devicePanel.innerHTML = [
            row("DEVICE", info.device),
            row("PRODUCT", info.product),
            row("MODEL", `${info.manufacturer || ""} ${info.model || ""}`.trim()),
            row("BRAND", info.brand),
            row("SERIAL NO", info.serial_no),
            row("PLATFORM", info.platform || info.hardware),
            row("ABI", info.abi),
            row("ABI LIST", info.abi_list),
            row("ANDROID", info.android),
            row("API LEVEL", info.api_level),
            row("FINGERPRINT", info.fingerprint),
            row("SECURITY PATCH", info.security_patch, "var(--cyan)"),
            row("BUILD DATE", info.build_date),
            row("BUILD ID", info.build_id),
            row("RESOLUTION", info.resolution),
            row("DISPLAY DENSITY", info.display_density ? `${info.display_density} dpi` : ""),
            row("DEBUGGABLE", debuggable ? "yes" : "no", debuggable ? "var(--sev-high)" : "var(--acid)"),
        ].join("");

        // Battery
        const b = info.battery || {};
        const batRow = (k, v, c) => v == null ? "" : `<div class="row"><span class="muted small" style="width:140px">${k}</span><span class="t-mono"${c ? ` style="color:${c}"` : ""}>${v}</span></div>`;
        const lvl = parseInt(b.level || "0", 10);
        const lvlColor = lvl >= 50 ? "var(--acid)" : lvl >= 20 ? "var(--sev-high)" : "var(--sev-crit)";
        $("#bridge-battery").innerHTML = (Object.keys(b).length === 0)
            ? `<div class="muted small">battery info unavailable</div>`
            : [
                batRow("LEVEL", b.level ? `${b.level}%` : null, lvlColor),
                batRow("STATUS", b.status),
                batRow("HEALTH", b.health),
                batRow("VOLTAGE", b.voltage ? `${b.voltage} mV` : null),
                batRow("TEMPERATURE", b.temperature ? `${(parseInt(b.temperature, 10) / 10).toFixed(1)} °C` : null),
                batRow("AC", b.ac_powered),
                batRow("USB", b.usb_powered),
                batRow("WIRELESS", b.wireless_powered),
                batRow("TECHNOLOGY", b.technology),
            ].join("");

        // Memory
        const mem = info.memory || {};
        $("#bridge-memory").innerHTML = Object.keys(mem).length
            ? Object.entries(mem).map(([k, v]) => `<div class="row"><span class="muted small" style="width:140px">${k}</span><span class="t-mono">${v}</span></div>`).join("")
            : `<div class="muted small">/proc/meminfo unreadable</div>`;

        // Storage
        const st = info.storage || [];
        $("#bridge-storage").innerHTML = st.length
            ? `<div class="table-hdr" style="grid-template-columns: 1fr 80px 80px 80px 60px 1fr"><span>FS</span><span>SIZE</span><span>USED</span><span>FREE</span><span>%</span><span>MOUNT</span></div>`
              + st.map((r) => `<div class="table-row" style="grid-template-columns: 1fr 80px 80px 80px 60px 1fr"><span class="t-mono">${r.filesystem}</span><span class="t-mono">${r.size}</span><span class="t-mono">${r.used}</span><span class="t-mono">${r.available}</span><span class="t-mono" style="color:${parseInt(r.use_pct, 10) > 90 ? "var(--sev-crit)" : "var(--cyan)"}">${r.use_pct}</span><span class="t-mono">${r.mounted_on}</span></div>`).join("")
            : `<div class="muted small">df unavailable</div>`;
    }

    // Wire action buttons.
    $$(".btn").forEach((btn) => {
        const label = btn.textContent.trim().toUpperCase();
        if (label.includes("START FRIDA")) {
            btn.addEventListener("click", async () => {
                btn.textContent = "[ STARTING… ]";
                try {
                    const r = await fetch("/v1/device/frida/start", { method: "POST" });
                    const j = await r.json();
                    if (!r.ok) throw new Error(j.detail || r.statusText);
                    btn.textContent = j.running ? `[ RUNNING pid=${j.pid} ]` : "[ FAILED TO START ]";
                    btn.style.color = j.running ? "var(--acid)" : "var(--sev-crit)";
                } catch (e) {
                    btn.textContent = "[ ERROR ]";
                    btn.style.color = "var(--sev-crit)";
                }
            });
        } else if (label.includes("PUSH SCRIPTS")) {
            btn.addEventListener("click", () => { btn.textContent = "[ NOT WIRED — see /v1/recipes ]"; btn.style.color = "var(--sev-high)"; });
        } else if (label.includes("PATCH WITH STHENO")) {
            btn.addEventListener("click", () => { btn.textContent = "[ STHENO BINDING PENDING ]"; btn.style.color = "var(--sev-high)"; });
        } else if (label.includes("FORCE REBOOT")) {
            btn.addEventListener("click", () => {
                if (!confirm("really reboot the connected device?")) return;
                btn.textContent = "[ NOT WIRED — adb reboot disabled ]"; btn.style.color = "var(--sev-high)";
            });
        }
    });
}


export { mount_device_bridge, mount_device_pull };
