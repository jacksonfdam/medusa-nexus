// ── auto-wired ES-module imports ──
import { $, $$, AVAILABLE_THEMES, chip, h, setTheme } from "./01-core.js";
import { bar } from "./06b-project-overview-mounts.js";

/* ─── live clock ─── */
function tickClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const iso = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
    const t = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
    const el = $("#clock");
    if (el) el.textContent = `${iso} · ${t} UTC`;
}

/* ─── sidebar toggle (collapsed / open / hidden) ───
 *
 * Three modes share one element:
 *   - desktop wide       : default `open`     — full 260px sidebar
 *   - desktop narrow     : `collapsed`        — icon-only 60px rail
 *   - mobile (<=768px)   : `collapsed/hidden` = drawer closed
 *                          (no class)        = drawer open (slides in)
 *
 * The CSS handles all three via `.collapsed` / `.hidden` modifiers on
 * `#body-grid`. We persist the desktop preference in localStorage; on mobile
 * the drawer always boots closed.
 */
const SIDEBAR_KEY = "nexus.sidebar";

function isMobileViewport() {
    return window.matchMedia("(max-width: 768px)").matches;
}

function applySidebarState(state) {
    const grid = $("#body-grid");
    if (!grid) return;
    grid.classList.toggle("collapsed", state === "collapsed");
    grid.classList.toggle("hidden",    state === "hidden");
}

function loadSidebarState() {
    if (isMobileViewport()) return "collapsed"; // boot the drawer closed
    try { return localStorage.getItem(SIDEBAR_KEY) || "open"; }
    catch (e) { return "open"; }
}

function toggleSidebar() {
    const grid = $("#body-grid");
    if (!grid) return;
    const mobile = isMobileViewport();
    let next;
    if (mobile) {
        // Mobile: cycle drawer open ↔ closed.
        next = grid.classList.contains("collapsed") || grid.classList.contains("hidden")
            ? "open" : "collapsed";
    } else {
        // Desktop: cycle collapsed ↔ open.
        next = grid.classList.contains("collapsed") ? "open" : "collapsed";
        try { localStorage.setItem(SIDEBAR_KEY, next); } catch (e) {}
    }
    applySidebarState(next);
}

function initSidebar() {
    applySidebarState(loadSidebarState());
    $("#sidebar-toggle")?.addEventListener("click", toggleSidebar);

    // ⌘B / ctrl+B keyboard toggle.
    window.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b" && !e.shiftKey) {
            e.preventDefault(); toggleSidebar();
        }
    });

    // On mobile: tapping a nav item closes the drawer; tapping the backdrop too.
    $$('.sidebar .nav-item').forEach((el) => el.addEventListener("click", () => {
        if (isMobileViewport()) applySidebarState("collapsed");
    }));
    document.addEventListener("click", (e) => {
        if (!isMobileViewport()) return;
        const grid = $("#body-grid");
        if (!grid || grid.classList.contains("collapsed") || grid.classList.contains("hidden")) return;
        // If the click was outside both the sidebar and the toggle, close.
        if (e.target.closest(".sidebar")) return;
        if (e.target.closest("#sidebar-toggle")) return;
        applySidebarState("collapsed");
    });

    // Re-evaluate on resize (going from mobile→desktop should restore the
    // user's previous desktop preference instead of leaving the drawer open).
    let lastMobile = isMobileViewport();
    window.addEventListener("resize", () => {
        const mobile = isMobileViewport();
        if (mobile === lastMobile) return;
        lastMobile = mobile;
        applySidebarState(loadSidebarState());
    });
}

/* ─── ⌘K command palette ───
 *
 * Fuzzy-search every destination and action, then run it blind — no mouse, no
 * hunting through the sidebar. ⌘K / Ctrl+K (or the topbar search box) opens it;
 * type, ↑/↓ to aim, Enter to fire, Esc to bail.
 *
 * The index is rebuilt on every open so project-scoped commands reflect wherever
 * you currently are. Two kinds of entries live here:
 *   - routes  → set location.hash and let the router do its thing
 *   - actions → call a function (toggle sidebar, cycle theme, project chrome…)
 *
 * Zero dependencies, zero build step. The fuzzy scorer is a subsequence match
 * with boundary/consecutive bonuses — good enough to feel psychic, small enough
 * to read in one sitting.
 */
const PALETTE_STATE = { open: false, items: [], filtered: [], sel: 0 };

// Last project we saw in the hash, so its sub-views stay one keystroke away even
// after you wander off into /devices or /tools.
let lastProjectId = null;

function currentProjectId() {
    const m = location.hash.match(/^#\/project\/([^/?]+)/);
    if (m) lastProjectId = decodeURIComponent(m[1]);
    return lastProjectId;
}

/* Static global destinations — curated labels/icons beat auto-deriving from the
 * route table. Keywords widen the fuzzy net (synonyms the label doesn't spell). */
const PALETTE_GLOBAL = [
    ["dashboard",       "Dashboard",        "🏠", "home start overview"],
    ["projects",        "Projects",         "📁", "apps list library"],
    ["scan",            "Scan APK / IPA",   "🔬", "upload analyze static new"],
    ["play-scan",       "Play Scan",        "▶", "google play store fetch"],
    ["play-accounts",   "Play Accounts",    "👤", "google login credentials"],
    ["devices",         "Devices",          "📱", "adb emulator phone"],
    ["adb",             "ADB Console",      "⌁", "shell bridge android"],
    ["device/pull",     "Pull App from Device", "↓", "extract apk dump"],
    ["device/bridge",   "Device Bridge",    "🌉", "connect wifi tcp"],
    ["ios/decrypt",     "iOS Decrypt",      "", "ipa frida dump"],
    ["device/shell",    "Device Shell",     ">_", "adb terminal command"],
    ["device/files",    "Device Files",     "🗂", "explorer sdcard push pull"],
    ["device/screen",   "Screen Mirror",    "🖥", "scrcpy record cast"],
    ["device/logcat",   "Logcat",           "📜", "logs crash stream"],
    ["report",          "Report",           "📄", "export pdf findings"],
    ["report/diff",     "Report Diff",      "±", "compare versions delta"],
    ["pipeline",        "Pipeline",         "⛓", "automation stages ci"],
    ["recipes",         "Recipes",          "📖", "presets playbook"],
    ["tools",           "Tools",            "🧰", "utilities helpers"],
    ["terminal",        "Terminal",         "▓", "repl console shell"],
    ["settings",        "Settings",         "⚙", "config preferences theme"],
    ["about",           "Credits",          "☠", "about license authors"],
];

/* Sub-views under a given project — offered only when we know an id. */
const PALETTE_PROJECT_VIEWS = [
    ["overview",         "Overview",        "◎", "summary risk"],
    ["static",           "Static Analysis", "🔬", "code manifest"],
    ["static/secrets",   "Secrets",         "🔑", "keys tokens api"],
    ["static/components","Components",       "🧩", "activities services receivers"],
    ["static/native",    "Native Libs",     "⚙", "so jni arm"],
    ["dynamic",          "Dynamic Analysis","⚡", "runtime frida hook"],
    ["runtime",          "Runtime",         "🎛", "live instrumentation"],
    ["network",          "Network",         "🌐", "traffic http tls"],
    ["api-map",          "API Map",         "🗺", "endpoints routes"],
    ["ssl-map",          "SSL Map",         "🔒", "tls certificates pinning"],
    ["surface",          "Attack Surface",  "🎯", "exposed entrypoints"],
    ["dataflow",         "Dataflow",        "💧", "taint sources sinks"],
    ["attack-tree",      "Attack Tree",     "🌳", "threat model paths"],
    ["owasp",            "OWASP MASVS",     "🛡", "masvs compliance"],
    ["tracer",           "Tracer",          "🧭", "call trace"],
    ["manifest-diff",    "Manifest Diff",   "±", "compare permissions"],
    ["findings-diff",    "Findings Diff",   "±", "compare regression"],
    ["report",           "Project Report",  "📄", "export findings"],
];

function buildPaletteItems() {
    const items = [];
    // routes → hash
    for (const [path, label, icon, kw] of PALETTE_GLOBAL) {
        items.push({ label, icon: icon || "▸", hint: `#/${path}`, group: "Go to",
                     keys: `${label} ${kw}`, run: () => { location.hash = `#/${path}`; } });
    }
    const pid = currentProjectId();
    if (pid) {
        const short = pid.length > 22 ? pid.slice(0, 21) + "…" : pid;
        for (const [sub, label, icon, kw] of PALETTE_PROJECT_VIEWS) {
            items.push({ label: `${label}`, icon: icon || "▸",
                         hint: `${short} · ${sub}`, group: `Project · ${short}`,
                         keys: `${label} ${kw} ${pid} project`,
                         run: () => { location.hash = `#/project/${encodeURIComponent(pid)}/${sub}`; } });
        }
        // project chrome actions (only wired when the fns exist on the page)
        const chrome = [
            ["View Manifest", "📄", "manifest xml plist", () => window.projectChromeManifest?.(pid)],
            ["Re-Attribute Findings", "⌖", "attribute sdk owner library", () => window.projectChromeAttribute?.(pid)],
            ["Backup Project", "↓", "zip archive export save", () => window.projectChromeBackup?.(pid)],
            ["Delete Project", "🗑", "wipe destroy remove", () => window.projectChromeDelete?.(pid)],
        ];
        for (const [label, icon, kw, fn] of chrome) {
            items.push({ label, icon, hint: `${short}`, group: `Project · ${short}`,
                         keys: `${label} ${kw} ${pid}`, danger: label.startsWith("Delete"),
                         run: fn });
        }
    }
    // global actions
    items.push({ label: "Toggle Sidebar", icon: "☰", hint: "⌘B", group: "Actions",
                 keys: "sidebar collapse expand nav", run: () => toggleSidebar() });
    for (const t of AVAILABLE_THEMES) {
        items.push({ label: `Theme · ${t.name}`, icon: "🎨", hint: t.kicker, group: "Actions",
                     keys: `theme ${t.name} ${t.id} color`, run: () => setTheme(t.id) });
    }
    return items;
}

/* Subsequence fuzzy scorer. Returns {score, pos} on the LABEL, or a positive
 * score with empty pos when the match only lived in the keywords. null = miss. */
function fuzzyScore(query, label, keys) {
    const q = query.toLowerCase();
    const scoreOn = (text, trackPos) => {
        const t = text.toLowerCase();
        let qi = 0, score = 0, prev = -2; const pos = [];
        for (let ti = 0; ti < t.length && qi < q.length; ti++) {
            if (t[ti] !== q[qi]) continue;
            let bonus = 1;
            if (ti === prev + 1) bonus += 3;                       // consecutive run
            if (ti === 0 || /[^a-z0-9]/.test(t[ti - 1])) bonus += 6; // word boundary
            score += bonus; prev = ti; qi++;
            if (trackPos) pos.push(ti);
        }
        return qi === q.length ? { score: score - t.length * 0.04, pos } : null;
    };
    const onLabel = scoreOn(label, true);
    if (onLabel) return onLabel;
    const onKeys = scoreOn(keys, false);
    return onKeys ? { score: onKeys.score * 0.5, pos: [] } : null;
}

function highlightLabel(label, pos) {
    if (!pos || !pos.length) return escapeHtmlSafe(label);
    const set = new Set(pos); let out = "";
    for (let i = 0; i < label.length; i++) {
        const c = escapeHtmlSafe(label[i]);
        out += set.has(i) ? `<b>${c}</b>` : c;
    }
    return out;
}

// Minimal escaper — labels are ours, but never trust a string near innerHTML.
function escapeHtmlSafe(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function paletteFilter(query) {
    const q = query.trim();
    PALETTE_STATE.query = q;
    if (!q) {
        PALETTE_STATE.filtered = PALETTE_STATE.items.map((it) => ({ it, pos: [] }));
    } else {
        PALETTE_STATE.filtered = PALETTE_STATE.items
            .map((it) => { const m = fuzzyScore(q, it.label, it.keys); return m ? { it, pos: m.pos, score: m.score } : null; })
            .filter(Boolean)
            .sort((a, b) => b.score - a.score)
            .slice(0, 40);
    }
    PALETTE_STATE.sel = 0;
    renderPaletteResults();
}

function renderPaletteResults() {
    const list = $("#cmdk-results");
    if (!list) return;
    const rows = PALETTE_STATE.filtered;
    if (!rows.length) {
        list.innerHTML = `<div class="cmdk-empty">no command matches // ghost query</div>`;
        return;
    }
    // Group headers only make sense in the unfiltered list — once you're
    // searching, the ranked order interleaves groups and repeated headers turn
    // into noise. So: grouped when idle, flat when hunting.
    const grouped = !PALETTE_STATE.query;
    let lastGroup = null; let html = "";
    rows.forEach(({ it, pos }, i) => {
        if (grouped && it.group !== lastGroup) {
            html += `<div class="cmdk-group">${escapeHtmlSafe(it.group)}</div>`;
            lastGroup = it.group;
        }
        html += `<div class="cmdk-row${i === PALETTE_STATE.sel ? " sel" : ""}${it.danger ? " danger" : ""}" data-i="${i}">
            <span class="cmdk-ico">${escapeHtmlSafe(it.icon)}</span>
            <span class="cmdk-label">${highlightLabel(it.label, pos)}</span>
            <span class="cmdk-hint">${escapeHtmlSafe(it.hint || "")}</span>
        </div>`;
    });
    list.innerHTML = html;
    $$("#cmdk-results .cmdk-row").forEach((row) => {
        row.addEventListener("mousemove", () => {
            const i = Number(row.dataset.i);
            if (i === PALETTE_STATE.sel) return;
            PALETTE_STATE.sel = i; paintPaletteSelection();
        });
        row.addEventListener("click", () => runPaletteSelection(Number(row.dataset.i)));
    });
    paintPaletteSelection();
}

function paintPaletteSelection() {
    $$("#cmdk-results .cmdk-row").forEach((row, i) =>
        row.classList.toggle("sel", i === PALETTE_STATE.sel));
    const sel = $("#cmdk-results .cmdk-row.sel");
    if (sel) sel.scrollIntoView({ block: "nearest" });
}

function runPaletteSelection(i) {
    const row = PALETTE_STATE.filtered[i ?? PALETTE_STATE.sel];
    if (!row) return;
    closePalette();
    try { row.it.run(); } catch (e) { console.error("palette action failed:", e); }
}

function openPalette() {
    if (PALETTE_STATE.open) return;
    PALETTE_STATE.open = true;
    PALETTE_STATE.items = buildPaletteItems();
    const wrap = document.createElement("div");
    wrap.className = "cmdk-overlay";
    wrap.id = "cmdk-overlay";
    wrap.innerHTML = `
      <div class="cmdk" role="dialog" aria-label="command palette">
        <div class="cmdk-search">
          <span class="cmdk-prompt">⌘K</span>
          <input id="cmdk-input" type="text" autocomplete="off" spellcheck="false"
                 placeholder="search features // jump anywhere…" />
          <span class="cmdk-esc">ESC</span>
        </div>
        <div class="cmdk-results" id="cmdk-results"></div>
        <div class="cmdk-foot"><span>↑↓ move</span><span>⏎ run</span><span>esc close</span></div>
      </div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) closePalette(); });
    const inp = $("#cmdk-input");
    inp.addEventListener("input", () => paletteFilter(inp.value));
    inp.addEventListener("keydown", onPaletteKey);
    paletteFilter("");
    inp.focus();
}

function closePalette() {
    PALETTE_STATE.open = false;
    $("#cmdk-overlay")?.remove();
}

function onPaletteKey(e) {
    const n = PALETTE_STATE.filtered.length;
    if (e.key === "Escape") { e.preventDefault(); closePalette(); return; }
    if (e.key === "Enter") { e.preventDefault(); runPaletteSelection(); return; }
    if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) {
        e.preventDefault(); if (n) { PALETTE_STATE.sel = (PALETTE_STATE.sel + 1) % n; paintPaletteSelection(); } return;
    }
    if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) {
        e.preventDefault(); if (n) { PALETTE_STATE.sel = (PALETTE_STATE.sel - 1 + n) % n; paintPaletteSelection(); } return;
    }
}

function initCommandPalette() {
    window.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            PALETTE_STATE.open ? closePalette() : openPalette();
        }
    });
    // Topbar search box → same palette. The box is a decoy; the palette is real.
    $("#cmdk-trigger")?.addEventListener("click", openPalette);
}

/* ─── horizontal tab strip (Android-Studio style) ───
 *
 * Every place you land becomes a chip in a strip above the content. Revisit a
 * spot and it re-focuses its chip instead of spawning a duplicate; wander off
 * and the old chip waits with your scroll position intact. Close what you don't
 * need; ＋ (or ⌘K) opens the next one.
 *
 * Grouping — this is the reconciliation with the in-project sub-nav (projectTabs):
 * every `#/project/<id>/*` sub-view collapses into ONE chip keyed by the project.
 * The strip is your top-level workspaces (projects, devices, tools…); the sub-nav
 * inside a project is that project's own tabs. Two systems, zero overlap. A chip
 * remembers the last sub-view you were on, so clicking it drops you back there.
 *
 * Session-stack model: switching a chip re-runs the router for its hash — no
 * keep-alive DOM, so live streams (logcat, screen mirror) restart on return.
 * Scroll is tracked per real hash (TAB_SCROLL), independent of the grouping.
 */
const TABS_KEY = "nexus.tabs";
const TABS_MAX = 14;
const TAB_STATE = { list: [], activeKey: null, currentHash: null, seq: 0 };
const TAB_SCROLL = new Map(); // real hash → scrollY, decoupled from chip grouping

// Lazily invert the global palette table into path→{label,icon} for chip titles.
let _tabGlobalMap = null;
function tabLookups() {
    if (!_tabGlobalMap) {
        _tabGlobalMap = new Map(PALETTE_GLOBAL.map(([p, label, icon]) => [p, { label, icon: icon || "▸" }]));
    }
    return _tabGlobalMap;
}

// Tell the router to reap the keep-alive panes belonging to a closed/evicted
// chip — fires that group's scope teardowns (pollers stop, streams close).
function paneEvict(key) {
    window.dispatchEvent(new CustomEvent("nexus:pane-evict", { detail: { key } }));
}

// One chip per project (all sub-views share it); every other route is its own chip.
function tabGroupKey(hash) {
    const path = String(hash).replace(/^#\/?/, "").split("?")[0];
    const proj = path.match(/^project\/([^/]+)(?:\/|$)/);
    return proj ? `proj:${decodeURIComponent(proj[1])}` : `hash:${hash}`;
}

function tabMeta(hash) {
    const raw = String(hash).replace(/^#\/?/, "");
    const [path] = raw.split("?");
    const proj = path.match(/^project\/([^/]+)/);
    if (proj) {
        const id = decodeURIComponent(proj[1]);
        return { icon: "📦", title: id.length > 16 ? id.slice(0, 15) + "…" : id };
    }
    const fnd = path.match(/^finding\/(.+)$/);
    if (fnd) return { icon: "🔎", title: `Finding ${fnd[1]}` };
    const hitg = tabLookups().get(path);
    if (hitg) return { icon: hitg.icon, title: hitg.label };
    return { icon: "▸", title: path || "dashboard" };
}

function tabsPersist() {
    try {
        sessionStorage.setItem(TABS_KEY, JSON.stringify({
            list: TAB_STATE.list.map((t) => ({ key: t.key, hash: t.hash })),
            activeKey: TAB_STATE.activeKey,
            scroll: Object.fromEntries(TAB_SCROLL),
        }));
    } catch (e) { /* private mode → tabs just won't survive a reload */ }
}

function tabsSaveScroll() {
    if (TAB_STATE.currentHash) {
        TAB_SCROLL.set(TAB_STATE.currentHash, window.scrollY || document.documentElement.scrollTop || 0);
    }
}

function tabsRestoreScroll() {
    const y = TAB_SCROLL.get(location.hash) || 0;
    requestAnimationFrame(() => window.scrollTo(0, y));
}

function tabsTrack(hash) {
    hash = hash || "#/dashboard";
    const key = tabGroupKey(hash);
    let t = TAB_STATE.list.find((x) => x.key === key);
    if (!t) {
        t = { key, hash, seq: ++TAB_STATE.seq, ...tabMeta(hash) };
        TAB_STATE.list.push(t);
        // Evict the oldest non-active chip once we blow past the cap.
        while (TAB_STATE.list.length > TABS_MAX) {
            const victim = TAB_STATE.list.findIndex((x) => x.key !== key);
            if (victim < 0) break;
            const [gone] = TAB_STATE.list.splice(victim, 1);
            if (gone) { TAB_SCROLL.delete(gone.hash); paneEvict(gone.key); }
        }
    } else {
        t.hash = hash;                   // remember where we are inside this chip
        t.seq = ++TAB_STATE.seq;
        Object.assign(t, tabMeta(hash));
    }
    TAB_STATE.activeKey = key;
    TAB_STATE.currentHash = hash;
    renderTabStrip();
    tabsPersist();
}

function tabsClose(key) {
    const idx = TAB_STATE.list.findIndex((x) => x.key === key);
    if (idx < 0) return;
    const wasActive = TAB_STATE.activeKey === key;
    const [gone] = TAB_STATE.list.splice(idx, 1);
    if (gone) TAB_SCROLL.delete(gone.hash);
    paneEvict(key);   // reap the closed chip's keep-alive panes + their streams
    if (!wasActive) { renderTabStrip(); tabsPersist(); return; }
    // Hand focus to the chip that slid into this slot, else the left neighbor.
    const next = TAB_STATE.list[idx] || TAB_STATE.list[idx - 1] || TAB_STATE.list[TAB_STATE.list.length - 1];
    if (next) { location.hash = next.hash; }
    else { TAB_STATE.activeKey = null; TAB_STATE.currentHash = null; tabsPersist(); location.hash = "#/dashboard"; }
}

function renderTabStrip() {
    const strip = $("#tab-strip");
    if (!strip) return;
    if (!TAB_STATE.list.length) { strip.innerHTML = ""; strip.classList.remove("has-tabs"); return; }
    strip.classList.add("has-tabs");
    const chips = TAB_STATE.list.map((t) => {
        const active = t.key === TAB_STATE.activeKey;
        return `<div class="tab-chip${active ? " active" : ""}" data-key="${escapeHtmlSafe(t.key)}" data-hash="${escapeHtmlSafe(t.hash)}" title="${escapeHtmlSafe(t.hash)}">
            <span class="tab-chip-ico">${escapeHtmlSafe(t.icon)}</span>
            <span class="tab-chip-label">${escapeHtmlSafe(t.title)}</span>
            <button class="tab-chip-close" data-close="${escapeHtmlSafe(t.key)}" aria-label="close tab" title="close">✕</button>
        </div>`;
    }).join("");
    strip.innerHTML = `<div class="tab-chips">${chips}</div>
        <button class="tab-new" id="tab-new" title="open a new view (⌘K)" aria-label="new tab">＋</button>`;
    $$("#tab-strip .tab-chip").forEach((chip) => {
        chip.addEventListener("mousedown", (e) => {
            if (e.target.closest(".tab-chip-close")) return;
            if (e.button === 1) { e.preventDefault(); tabsClose(chip.dataset.key); return; } // middle-click closes
            if (e.button !== 0) return;
            const hash = chip.dataset.hash;
            if (hash && hash !== location.hash) location.hash = hash;
        });
    });
    $$("#tab-strip .tab-chip-close").forEach((btn) =>
        btn.addEventListener("click", (e) => { e.stopPropagation(); tabsClose(btn.dataset.close); }));
    $("#tab-new")?.addEventListener("click", openPalette);
    $("#tab-strip .tab-chip.active")?.scrollIntoView({ inline: "nearest", block: "nearest" });
}

function measureTopbar() {
    const bar = $(".topbar");
    if (bar) document.documentElement.style.setProperty("--topbar-h", `${bar.offsetHeight}px`);
}

function initTabs() {
    measureTopbar();
    window.addEventListener("resize", measureTopbar);
    try {
        const saved = JSON.parse(sessionStorage.getItem(TABS_KEY) || "null");
        if (saved && Array.isArray(saved.list)) {
            TAB_STATE.list = saved.list
                .filter((t) => t && typeof t.key === "string" && typeof t.hash === "string")
                .map((t) => ({ key: t.key, hash: t.hash, seq: ++TAB_STATE.seq, ...tabMeta(t.hash) }));
            TAB_STATE.activeKey = saved.activeKey || null;
            if (saved.scroll) for (const [h, y] of Object.entries(saved.scroll)) TAB_SCROLL.set(h, y);
        }
    } catch (e) { /* corrupt state → start clean */ }
    renderTabStrip();
}


export { initCommandPalette, initSidebar, initTabs, tabGroupKey, tabsRestoreScroll, tabsSaveScroll, tabsTrack, tickClock };
