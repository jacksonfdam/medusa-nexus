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
