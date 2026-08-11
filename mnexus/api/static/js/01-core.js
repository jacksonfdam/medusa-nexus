/* MEDUSA NEXUS — SPA (01-core: shared helpers + theme + formatters).
 *
 * The SPA used to be one ~8.3k-line app.js. It's now 19 ES modules under
 * static/js/, each exporting its public functions and importing what it needs.
 * index.html loads a single entry (13-bootstrap, type="module") and the browser
 * resolves the whole graph. Numeric prefixes are a rough reading order, not a
 * load requirement (the import graph drives evaluation):
 *
 *   01-core                       $, $$, h, getJSON, pollingScope, formatters, stub, escapeHtml
 *   02-screens-main               dashboard, projects, scan
 *   03-playintel                  play-scan / play-accounts + firebase/probe/secret blocks
 *   04a-project-views             device pull/bridge/ios + project overview/static/dynamic views
 *   04b-project-runtime           runtime view + mount (Frida introspection)
 *   04c-project-diffs             manifest/findings diff + network/report views
 *   05-misc-screens               report/recipes/tools/settings/about/boot/finding views
 *   06a-devices                   multi-device manager, mirror, shell wiring
 *   06b-project-overview-mounts   overview / play-intel-overview / exports / static mounts
 *   07a-project-mounts            dynamic / memory-inspector / network mounts
 *   07b-device-io-mounts          device pull / bridge mounts
 *   08a-adb                       ADB control panel (helpers + view + mount)
 *   08b-device-io                 device shell / files / screen / logcat
 *   09-mounts-rest                recipes / settings / finding / report mounts
 *   10a-project-chrome            projectChrome + secrets/components/native/tracer sub-screens
 *   10b-project-analysis          api-map/ssl/surface/dataflow/attack-tree/owasp + diff/pipeline/terminal
 *   11-router                     ROUTES table + matchRoute + renderRoute
 *   12-shell-ui                   clock, sidebar, ⌘K command palette, tab strip
 *   13-bootstrap                  entry — DOMContentLoaded wiring
 *
 * Circular edges exist (router ⇄ views via renderRoute) and resolve fine —
 * imported bindings are live and functions are hoisted at instantiation. Inline
 * onclick handlers still call a few globals, so those stay on window
 * (projectChrome*, confirmModal). Every route is a fn of (ctx) returning an HTML
 * string; the router injects it into #view and calls an optional mount().
 */

/* ─── tiny helpers ─── */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const h = (strings, ...values) => String.raw({ raw: strings }, ...values);

/* ─── theme manager ───
 *
 * Eleven themes ship: `nexus` (default cyberpunk), `dracula`, `chaos-feed`
 * (the light one — white desktop, Win95 chrome, neon riot), the four
 * Catppuccin flavors (mocha / macchiato / frappe / latte) and the four
 * Gradianto variants (deep-ocean / dark-fuchsia / nature-green / midnight-blue).
 * `chaos-feed` and `catppuccin-latte` are the two light themes. The CSS lives
 * under [data-theme="<name>"] in
 * app.css; this manager just toggles the attribute and persists the choice.
 * The early <head> script in index.html applies the saved theme before paint,
 * so we never flash the wrong colors.
 *
 * Adding another theme: append to AVAILABLE_THEMES and add the matching
 * [data-theme="…"] block to app.css. No code changes elsewhere — the settings
 * picker and the ⌘K palette read this list.
 */
const THEME_KEY = "nexus.theme";
const AVAILABLE_THEMES = [
    {
        id: "nexus",
        name: "🔱 Nexus",
        kicker: "default · cyberpunk neon",
        swatches: ["#000000", "#00FFFF", "#22DE80", "#E879F9", "#FF3860"],
    },
    {
        id: "dracula",
        name: "🧛 Dracula",
        kicker: "draculatheme.com",
        swatches: ["#282A36", "#8BE9FD", "#50FA7B", "#BD93F9", "#FF5555"],
    },
    {
        id: "chaos-feed",
        name: "🗞 Chaos Feed",
        kicker: "light · win95 chrome · neon riot",
        swatches: ["#FFFFFF", "#000080", "#00E7FF", "#FF0077", "#CCFF00"],
    },
    {
        id: "catppuccin-mocha",
        name: "🐱 Catppuccin Mocha",
        kicker: "catppuccin · dark flagship",
        swatches: ["#1E1E2E", "#89DCEB", "#A6E3A1", "#CBA6F7", "#F38BA8"],
    },
    {
        id: "catppuccin-macchiato",
        name: "🐱 Catppuccin Macchiato",
        kicker: "catppuccin · mid dark",
        swatches: ["#24273A", "#91D7E3", "#A6DA95", "#C6A0F6", "#ED8796"],
    },
    {
        id: "catppuccin-frappe",
        name: "🐱 Catppuccin Frappé",
        kicker: "catppuccin · soft dark",
        swatches: ["#303446", "#99D1DB", "#A6D189", "#CA9EE6", "#E78284"],
    },
    {
        id: "catppuccin-latte",
        name: "🐱 Catppuccin Latte",
        kicker: "catppuccin · light",
        swatches: ["#EFF1F5", "#179299", "#40A02B", "#8839EF", "#D20F39"],
    },
    {
        id: "gradianto-deep-ocean",
        name: "🌊 Gradianto Deep Ocean",
        kicker: "gradianto · petrol blue",
        swatches: ["#1C2739", "#04D9FF", "#75AA5F", "#8EC1FF", "#CC844F"],
    },
    {
        id: "gradianto-dark-fuchsia",
        name: "🔮 Gradianto Dark Fuchsia",
        kicker: "gradianto · plum + fuchsia",
        swatches: ["#3D214E", "#D07BD2", "#2EA9AA", "#71AA84", "#C6C666"],
    },
    {
        id: "gradianto-nature-green",
        name: "🌿 Gradianto Nature Green",
        kicker: "gradianto · forest",
        swatches: ["#20403F", "#2EA9AA", "#71AA84", "#D07BD2", "#C6C666"],
    },
    {
        id: "gradianto-midnight-blue",
        name: "🌌 Gradianto Midnight Blue",
        kicker: "gradianto · indigo",
        swatches: ["#282839", "#8F9BF2", "#96BF7D", "#A98FD8", "#CC8B60"],
    },
];

function getTheme() {
    try { return localStorage.getItem(THEME_KEY) || "nexus"; }
    catch (e) { return "nexus"; }
}

function setTheme(id) {
    if (!AVAILABLE_THEMES.some((t) => t.id === id)) return;
    document.documentElement.setAttribute("data-theme", id);
    try { localStorage.setItem(THEME_KEY, id); } catch (e) { /* ignore */ }
    // Notify listeners (e.g. the settings page) so swatches re-render.
    window.dispatchEvent(new CustomEvent("nexus:theme", { detail: { id } }));
}

function applyThemeAttr() {
    document.documentElement.setAttribute("data-theme", getTheme());
}

async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`${url} → ${r.status}`);
    return r.json();
}

/* ──────────────────────────────────────────────────────────────────
 *  Per-pane lifecycle scope — the keep-alive tab strip keeps every open
 *  view's DOM (plus its pollers/streams) warm in the background, so a
 *  poller must NOT die just because you switched tabs. It dies when its
 *  TAB is closed. Every mount runs inside an "active scope"; pollers,
 *  intervals and EventSources register their teardown via onTeardown()
 *  and the router fires them all when that pane is evicted. Deferred
 *  handlers (a click that opens a stream) only fire while their pane is
 *  the visible/active one, so onTeardown always lands in the right scope.
 *  See renderRoute() + the pane pool in 11-router.
 * ────────────────────────────────────────────────────────────────── */
let _activeScope = null;
function makeScope() { return { teardowns: [] }; }
function setActiveScope(scope) { _activeScope = scope; }
function runScope(scope) {
    if (!scope) return;
    for (const fn of scope.teardowns.splice(0)) {
        try { fn(); } catch (_) { /* one bad teardown shouldn't block the rest */ }
    }
}
function onTeardown(fn) {
    if (typeof fn === "function" && _activeScope) _activeScope.teardowns.push(fn);
    // No active scope → the poller just won't be auto-reaped; its own guards
    // (serial change, checkbox off) still apply. Shouldn't happen in a mount.
}

/* ──────────────────────────────────────────────────────────────────
 *  Polling helper — runs `tick()` every `intervalMs` until its owning
 *  TAB is closed (pane teardown) or the scope is explicitly cancelled.
 *  Used by the SSL Map / API Map / Dynamic console / runtime screens.
 *
 *  Keep-alive: the loop no longer stops on `hashchange` — a backgrounded
 *  tab keeps streaming so live data survives a tab switch. Its stop() is
 *  registered with the active pane scope and fires on tab close. Returns
 *  a `{ stop }` handle for callers that toggle it manually (auto-refresh
 *  checkboxes). The harness also re-runs `tick()` once when the page
 *  regains visibility so a browser tab hidden for a minute doesn't show
 *  stale data for one more interval.
 * ────────────────────────────────────────────────────────────────── */
function pollingScope(tick, intervalMs = 3000) {
    let cancelled = false;
    let timer = null;
    let inFlight = false;

    const run = async () => {
        if (cancelled || inFlight) return;
        inFlight = true;
        try { await tick(); } catch (_) { /* don't break the loop on one bad tick */ }
        inFlight = false;
        if (!cancelled) timer = setTimeout(run, intervalMs);
    };

    const onVisibilityChange = () => { if (!document.hidden) run(); };
    const stop = () => {
        if (cancelled) return;
        cancelled = true;
        if (timer) clearTimeout(timer);
        document.removeEventListener("visibilitychange", onVisibilityChange);
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    onTeardown(stop);
    // First tick immediate; subsequent ones every intervalMs.
    run();
    return { stop };
}

/* Relative "Xs ago / Xm ago" for live status lines. Defensive on bad input. */
function fmtAgo(ts) {
    if (!ts) return "—";
    const t = Date.parse(ts);
    if (Number.isNaN(t)) return "—";
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
}

function classifyRisk(score) {
    if (score >= 75) return "crit";
    if (score >= 50) return "high";
    if (score >= 25) return "med";
    return "acid";
}

function chip(sev) {
    const cls = ["crit", "high", "med", "low", "info"].includes(sev) ? sev : "info";
    return `<span class="chip ${cls}">${cls.toUpperCase()}</span>`;
}

/* Library-attribution chip — the acid/cyan/sev-high dot that tags a
 * finding with its owner (first-party / named SDK / third-party unknown).
 * Returns '' for findings the LibraryAttributionAudit didn't touch, so
 * callers can drop it inline without a conditional. Colour coding:
 *   - first-party         → acid       (your code, your fix)
 *   - named SDK           → cyan       (vendor rotation + SDK override)
 *   - unknown third-party → sev-high   (needs human review)
 * Confidence encoded in the leading glyph: ● high · ◐ medium · ○ low. */
function attrTag(f) {
    if (!f || !f.attributed_to) return "";
    const owner = f.attributed_to;
    let color = "var(--magenta)";
    if (owner === "first-party") color = "var(--acid)";
    else if (owner === "third-party (unknown)") color = "var(--sev-high)";
    else color = "var(--cyan)";
    const conf = (f.attribution_confidence || "").toLowerCase();
    const dot = conf === "high" ? "●" : conf === "medium" ? "◐" : "○";
    const cat = f.sdk_category ? ` · ${f.sdk_category}` : "";
    return `<span class="tag" title="LibraryAttributionAudit · ${conf || "?"} confidence" style="color:${color}">${dot} ${owner}${cat}</span>`;
}

/* Platform glyph — rendered next to the bundle id everywhere a project is listed. */
function platformGlyph(platform) {
    if (platform === "ios") return `<span title="iOS" style="color:#fff">🍎</span>`;
    return `<span title="Android" style="color:var(--acid)">🤖</span>`;
}

function sectionHeader(ascii, kicker, title) {
    return `
    <div>
      <div class="section-header">
        <div class="ascii">${ascii}</div>
        <div class="label-group">
          <div class="kicker">${kicker}</div>
          <div class="title">${title}</div>
        </div>
      </div>
      <div class="gradient-underline"></div>
    </div>`;
}

/* ─── stub renderer: rich wireframe for screens still under construction ─── */
function stub({ id, kicker, title, hero, detail, features = [], cta }) {
    return h`
    <div class="main">
      ${sectionHeader(hero, kicker, title)}
      <section class="panel">
        <div class="panel-head">// SPEC — from docs/SPEC.md</div>
        <div class="panel-body">
          <p class="muted" style="margin:0 0 12px">${detail}</p>
          <ul style="margin:0;padding-left:18px;color:var(--cyan);font-size:12px;line-height:1.7">
            ${features.map((f) => `<li>${f}</li>`).join("")}
          </ul>
        </div>
      </section>
      <section class="empty-state">
        <div style="font-size:20px;letter-spacing:4px;color:var(--magenta);margin-bottom:12px">
          [ ${id}  ·  iteration 2 // full fidelity ]
        </div>
        ${cta ? `<div>${cta}</div>` : ""}
        <div style="margin-top:12px">the design is locked in the Pencil deck · <a href="#/about">design INDEX</a></div>
      </section>
    </div>`;
}


/* Shared HTML escaper (was duplicated across playintel + project-chrome). */
function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

export { $, $$, AVAILABLE_THEMES, applyThemeAttr, attrTag, chip, classifyRisk, escapeHtml, fmtAgo, getJSON, getTheme, h, makeScope, onTeardown, platformGlyph, pollingScope, runScope, sectionHeader, setActiveScope, setTheme, stub };
