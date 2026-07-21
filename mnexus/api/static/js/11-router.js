// ── auto-wired ES-module imports ──
import { $, $$, h } from "./01-core.js";
import { mount_dashboard, mount_projects, mount_scan, mount_scan_after_upload_wiring, view_dashboard, view_projects, view_scan } from "./02-screens-main.js";
import { mount_play_accounts, mount_play_scan, view_play_accounts, view_play_scan } from "./03-playintel.js";
import { bindProjectTabActions, mount_ios_decrypt, view_device_bridge, view_device_pull, view_ios_decrypt, view_project_dynamic, view_project_overview, view_project_static } from "./04a-project-views.js";
import { mount_project_runtime, view_project_runtime } from "./04b-project-runtime.js";
import { mount_project_findings_diff, mount_project_manifest_diff, view_project_findings_diff, view_project_manifest_diff, view_project_network, view_project_report } from "./04c-project-diffs.js";
import { mount_tools, view_about, view_boot, view_finding_detail, view_recipes, view_report, view_settings, view_tools } from "./05-misc-screens.js";
import { mount_devices, view_devices } from "./06a-devices.js";
import { mount_project_overview, mount_project_static } from "./06b-project-overview-mounts.js";
import { mount_project_dynamic, mount_project_network } from "./07a-project-mounts.js";
import { mount_device_bridge, mount_device_pull } from "./07b-device-io-mounts.js";
import { mount_adb, view_adb } from "./08a-adb.js";
import { mount_device_files, mount_device_logcat, mount_device_screen, mount_device_shell, view_device_files, view_device_logcat, view_device_screen, view_device_shell } from "./08b-device-io.js";
import { mount_finding_detail, mount_recipes, mount_report, mount_settings } from "./09-mounts-rest.js";
import { mount_project_components, mount_project_native, mount_project_secrets, mount_project_tracer, view_project_components, view_project_native, view_project_secrets, view_project_tracer } from "./10a-project-chrome.js";
import { mount_pipeline, mount_project_api_map, mount_project_attack_tree, mount_project_dataflow, mount_project_owasp, mount_project_ssl_map, mount_project_surface, mount_report_diff, mount_terminal, view_pipeline, view_project_api_map, view_project_attack_tree, view_project_dataflow, view_project_owasp, view_project_ssl_map, view_project_surface, view_report_diff, view_states, view_terminal, view_toasts } from "./10b-project-analysis.js";
import { tabsRestoreScroll, tabsSaveScroll, tabsTrack } from "./12-shell-ui.js";

/* ═══════════════════════════════════════════════════════════════════════════
 *  Route map + router
 * ═══════════════════════════════════════════════════════════════════════════ */
const ROUTES = [
    { path: "boot",                             view: view_boot },
    { path: "dashboard",                        view: view_dashboard,         mount: mount_dashboard },
    { path: "projects",                         view: view_projects,          mount: mount_projects },
    { path: "scan",                             view: view_scan,              mount: async (ctx) => { mount_scan(); await mount_scan_after_upload_wiring(); } },
    { path: "play-scan",                        view: view_play_scan,         mount: async () => { await mount_play_scan(); } },
    { path: "play-accounts",                    view: view_play_accounts,     mount: async () => { await mount_play_accounts(); } },
    { path: "devices",                          view: view_devices,           mount: mount_devices },
    { path: "adb",                              view: view_devices,           mount: mount_devices },  // alias of /devices
    { path: "device/pull",                      view: view_device_pull,       mount: mount_device_pull },
    { path: "device/bridge",                    view: view_device_bridge,     mount: mount_device_bridge },
    { path: "ios/decrypt",                      view: view_ios_decrypt,       mount: mount_ios_decrypt },
    { path: "device/shell",                     view: view_device_shell,      mount: mount_device_shell },
    { path: "device/files",                     view: view_device_files,      mount: mount_device_files },
    { path: "device/screen",                    view: view_device_screen,     mount: mount_device_screen },
    { path: "device/logcat",                    view: view_device_logcat,     mount: mount_device_logcat },
    { path: "adb",                              view: view_adb,               mount: mount_adb },
    { path: "dynamic",                          view: (ctx) => view_project_dynamic(ctx), mount: mount_project_dynamic },
    { path: "network",                          view: (ctx) => view_project_network(ctx) },
    { path: "report",                           view: view_report,            mount: mount_report },
    { path: "report/diff",                      view: view_report_diff,       mount: mount_report_diff },
    { path: "pipeline",                         view: view_pipeline,          mount: mount_pipeline },
    { path: "recipes",                          view: view_recipes,           mount: mount_recipes },
    { path: "tools",                            view: view_tools,             mount: mount_tools },
    { path: "settings",                         view: view_settings,          mount: mount_settings },
    { path: "about",                            view: view_about },
    { path: "terminal",                         view: view_terminal,          mount: mount_terminal },
    { path: "states",                           view: view_states },
    { path: "toasts",                           view: view_toasts },
    { path: "finding/:fid",                     view: view_finding_detail,    mount: mount_finding_detail },

    /* project scoped */
    // Bare project hash → overview. location.replace keeps the back button clean
    // so users don't bounce back into the redirect target's predecessor.
    { path: "project/:id", view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/overview`); return ""; } },
    // Common bare aliases for sub-views that actually live under /static or
    // similar. Anything Overview tiles link to gets a forgiving redirect here
    // so bookmarks + cross-references survive route reshuffles.
    { path: "project/:id/components", view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/static/components`); return ""; } },
    { path: "project/:id/secrets",    view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/static/secrets`); return ""; } },
    { path: "project/:id/native",     view: (ctx) => { location.replace(`#/project/${encodeURIComponent(ctx.params.id)}/static/native`); return ""; } },
    { path: "project/:id/overview",             view: view_project_overview,  mount: mount_project_overview },
    { path: "project/:id/static",               view: view_project_static,    mount: mount_project_static },
    { path: "project/:id/static/secrets",       view: view_project_secrets,    mount: mount_project_secrets },
    { path: "project/:id/static/components",    view: view_project_components, mount: mount_project_components },
    { path: "project/:id/static/native",        view: view_project_native,     mount: mount_project_native },
    { path: "project/:id/dynamic",              view: view_project_dynamic,   mount: mount_project_dynamic },
    { path: "project/:id/runtime",              view: view_project_runtime,   mount: mount_project_runtime },
    { path: "project/:id/manifest-diff",        view: view_project_manifest_diff, mount: mount_project_manifest_diff },
    { path: "project/:id/findings-diff",        view: view_project_findings_diff, mount: mount_project_findings_diff },
    { path: "project/:id/tracer",               view: view_project_tracer,    mount: mount_project_tracer },
    { path: "project/:id/network",              view: view_project_network,   mount: mount_project_network },
    { path: "project/:id/api-map",              view: view_project_api_map,   mount: mount_project_api_map },
    { path: "project/:id/ssl-map",              view: view_project_ssl_map,   mount: mount_project_ssl_map },
    { path: "project/:id/surface",              view: view_project_surface,   mount: mount_project_surface },
    { path: "project/:id/dataflow",             view: view_project_dataflow,  mount: mount_project_dataflow },
    { path: "project/:id/attack-tree",          view: view_project_attack_tree, mount: mount_project_attack_tree },
    { path: "project/:id/owasp",                view: view_project_owasp,     mount: mount_project_owasp },
    { path: "project/:id/report",               view: view_project_report },
    { path: "project/:id/finding/:fid",         view: view_finding_detail,    mount: mount_finding_detail },
];

function matchRoute(hashPath) {
    for (const route of ROUTES) {
        const patternParts = route.path.split("/");
        const pathParts = hashPath.split("/");
        if (patternParts.length !== pathParts.length) continue;
        const params = {};
        let matched = true;
        for (let i = 0; i < patternParts.length; i++) {
            if (patternParts[i].startsWith(":")) {
                params[patternParts[i].slice(1)] = decodeURIComponent(pathParts[i]);
            } else if (patternParts[i] !== pathParts[i]) {
                matched = false;
                break;
            }
        }
        if (matched) return { route, params };
    }
    return null;
}

function setActiveSidebar(topLevel) {
    $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.route === topLevel));
}

async function renderRoute() {
    // Stash the outgoing view's scroll into its chip before the DOM swaps out.
    tabsSaveScroll();
    const raw = location.hash.replace(/^#\/?/, "") || "dashboard";
    const [pathPart] = raw.split("?");
    const hit = matchRoute(pathPart);
    const ctx = { params: hit?.params || {}, hash: raw };
    const view = $("#view");
    if (!view) return;
    if (!hit) {
        view.innerHTML = h`
        <div class="main">
          <div class="empty-state">
            <div style="font-size:48px;color:var(--magenta);letter-spacing:4px">404 // GHOST ROUTE</div>
            <div class="muted">no view wired for <code>#/${pathPart}</code></div>
            <div style="margin-top:16px"><a class="btn primary" href="#/dashboard">[ HOME ]</a></div>
          </div>
        </div>`;
        setActiveSidebar(null);
        return;
    }
    const html = hit.route.view(ctx);
    view.innerHTML = html;
    // Update sidebar active based on top-level segment (sidebar only lists the 9 primaries).
    const topLevel = pathPart.split("/")[0];
    setActiveSidebar(topLevel);
    // Redirect stubs return "" and immediately rewrite the hash — don't give
    // them a chip; only real views earn a tab.
    const isRealView = !!(html && html.trim());
    if (isRealView) tabsTrack(location.hash || "#/dashboard");
    if (typeof hit.route.mount === "function") {
        try { await hit.route.mount(ctx); } catch (e) { console.error("mount failed:", e); }
    }
    // Project-scoped routes share a tab bar with rescan/refresh buttons —
    // bind them once after every mount has finished rebuilding the DOM.
    if (pathPart.startsWith("project/")) bindProjectTabActions();
    document.title = `🔱 MEDUSA::NEXUS / ${pathPart}`;
    // Mount may have reflowed the page — restore this chip's scroll after it settles.
    if (isRealView) tabsRestoreScroll();
}


export { renderRoute };
