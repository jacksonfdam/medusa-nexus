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
 * Two themes ship: `nexus` (default cyberpunk) and `dracula`. The CSS lives
 * under [data-theme="<name>"] in app.css; this manager just toggles the
 * attribute and persists the choice. The early <head> script in index.html
 * applies the saved theme before paint, so we never flash the wrong colors.
 *
 * Adding a third theme: append to AVAILABLE_THEMES and add the matching
 * [data-theme="…"] block to app.css. No code changes elsewhere.
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
 *  Polling helper — runs `tick()` every `intervalMs` until the route
 *  changes (hashchange) or the scope is explicitly cancelled. Used by
 *  the SSL Map / API Map / Dynamic console screens.
 *
 *  Returns a `{ stop }` handle; calling stop() detaches the listener
 *  and cancels any pending tick. The harness also re-runs `tick()`
 *  once when the page regains visibility so a tab that was hidden
 *  for a minute doesn't show stale data for one more interval.
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

    const onHashChange = () => stop();
    const onVisibilityChange = () => { if (!document.hidden) run(); };
    const stop = () => {
        if (cancelled) return;
        cancelled = true;
        if (timer) clearTimeout(timer);
        window.removeEventListener("hashchange", onHashChange);
        document.removeEventListener("visibilitychange", onVisibilityChange);
    };

    window.addEventListener("hashchange", onHashChange);
    document.addEventListener("visibilitychange", onVisibilityChange);
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

export { $, $$, AVAILABLE_THEMES, applyThemeAttr, attrTag, chip, classifyRisk, escapeHtml, fmtAgo, getJSON, getTheme, h, platformGlyph, pollingScope, sectionHeader, setTheme, stub };
