// ── auto-wired ES-module imports ──
import { applyThemeAttr } from "./01-core.js";
import { renderRoute } from "./11-router.js";
import { initCommandPalette, initSidebar, initTabs, tickClock } from "./12-shell-ui.js";

/* ─── bootstrap ─── */
window.addEventListener("hashchange", renderRoute);
window.addEventListener("DOMContentLoaded", () => {
    if (!location.hash) location.replace("#/dashboard");
    applyThemeAttr();
    initSidebar();
    initCommandPalette();
    initTabs();
    renderRoute();
    tickClock();
    setInterval(tickClock, 1000);
});
