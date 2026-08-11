// ── auto-wired ES-module imports ──
import { $, escapeHtml, h } from "./01-core.js";
import { bindProjectTabActions, projectTabs } from "./04a-project-views.js";

/* ═══════════════════════════════════════════════════════════════════════════
 *  PROJECT SUB-VIEW — Attack plan
 *
 *  The proactive-exploitation screen: turn findings into concrete PoCs, then
 *  (opt-in) fire the device subset. Verdicts read PROVABLE (PoC ready),
 *  CONFIRMED (reproduced on a live device), DISPROVEN (mitigation held), or
 *  MANUAL (needs a human). Everything here also lands in the report.
 * ═══════════════════════════════════════════════════════════════════════════ */

const V_META = {
    confirmed: { color: "var(--sev-crit)", label: "CONFIRMED" },
    provable:  { color: "var(--acid)",     label: "PROVABLE" },
    disproven: { color: "var(--sev-low)",  label: "DISPROVEN" },
    manual:    { color: "var(--cyan)",     label: "MANUAL" },
};
const K_GLYPH = { frida: "🐍", adb: "🤖", curl: "🌐", html: "📄", none: "✋" };
const K_LANG = { frida: "javascript", adb: "bash", curl: "bash", html: "html", none: "" };


function view_project_attack(ctx) {
    const id = ctx.params.id;
    if (!id) { location.hash = "#/projects"; return ""; }
    return h`
    <div class="main">
      <div class="muted small uppercase">🔱 NEXUS / ${id} / attack</div>
      ${projectTabs(id, "attack")}

      <section class="panel accent">
        <div class="panel-head" style="color:var(--acid)">// PROACTIVE ATTACK</div>
        <div class="panel-body col">
          <div class="row" style="gap:8px;flex-wrap:wrap">
            <button class="btn" id="atk-plan">[ BUILD PLAN ]</button>
            <button class="btn" id="atk-dry" title="Report what would fire — nothing is triggered">[ DRY-RUN ]</button>
            <button class="btn" id="atk-go" style="color:var(--sev-high)" title="Fire the adb PoCs against the connected device">[ EXECUTE ⚠ ]</button>
            <span class="grow"></span>
            <span id="atk-summary" class="muted small"></span>
          </div>
          <div class="muted small">Offline plan is always safe. EXECUTE fires only the adb PoCs against a
            bridged device (Frida + curl stay PROVABLE) and needs USB debugging authorised.</div>
        </div>
      </section>

      <div id="atk-list" class="col" style="gap:10px">
        <div class="empty-state"><span class="muted small uppercase">loading plan for ${id}…</span></div>
      </div>
    </div>`;
}


async function _get(id) {
    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/attack`, { cache: "no-store" });
    return r.json();
}

async function _post(id, path) {
    const r = await fetch(`/v1/projects/${encodeURIComponent(id)}/attack/${path}`, { method: "POST" });
    const body = await r.json().catch(() => ({}));
    return { ok: r.ok, status: r.status, body };
}


function renderPlan(body) {
    const summary = $("#atk-summary");
    if (summary) {
        const parts = Object.entries(body.summary || {}).map(([k, v]) => {
            const m = V_META[k] || { color: "var(--fg)", label: k.toUpperCase() };
            return `<span style="color:${m.color}">${m.label} ${v}</span>`;
        }).join(" · ");
        summary.innerHTML = parts || `<span class="muted">no attempts</span>`;
    }

    const list = $("#atk-list");
    if (!list) return;
    const attempts = body.attempts || [];
    if (!attempts.length) {
        list.innerHTML = `<div class="empty-state"><span class="muted small uppercase">no plan yet — click BUILD PLAN</span></div>`;
        return;
    }
    list.innerHTML = attempts.map((a) => {
        const m = V_META[a.verdict] || { color: "var(--fg)", label: (a.verdict || "").toUpperCase() };
        const poc = a.poc
            ? `<pre style="background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;padding:10px;overflow:auto;max-height:240px"><code>${escapeHtml(a.poc)}</code></pre>`
            : "";
        const evidence = (a.executed && a.evidence)
            ? `<div class="muted small">device output:</div><pre style="background:var(--bg-panel);border:1px solid var(--border);border-radius:2px;padding:8px;overflow:auto;max-height:160px"><code>${escapeHtml(a.evidence)}</code></pre>`
            : "";
        return `
          <section class="panel">
            <div class="panel-head">
              <span style="color:${m.color};letter-spacing:1px">${m.label}</span>
              &nbsp; ${K_GLYPH[a.poc_kind] || ""} ${escapeHtml(a.technique || "")}
            </div>
            <div class="panel-body col" style="gap:6px">
              <div style="font-weight:700">${escapeHtml(a.title || "")}</div>
              ${a.target ? `<div class="muted small">target: <code>${escapeHtml(a.target)}</code></div>` : ""}
              <div class="muted small">${escapeHtml(a.rationale || "")}</div>
              ${poc}
              ${evidence}
              <div style="border-left:2px solid var(--acid);padding-left:10px">
                <span class="t-mono" style="color:var(--acid);font-size:11px">MITIGATION</span>
                <div class="small">${escapeHtml(a.mitigation || "")}</div>
              </div>
            </div>
          </section>`;
    }).join("");
}


async function mount_project_attack(ctx) {
    bindProjectTabActions();
    const id = ctx.params.id;
    if (!id) return;

    try {
        renderPlan(await _get(id));
    } catch (_) {
        const list = $("#atk-list");
        if (list) list.innerHTML = `<div class="chip high">attack plan unreachable</div>`;
        return;
    }

    const busy = (btn, txt) => { btn._orig = btn.textContent; btn.textContent = txt; btn.disabled = true; };
    const done = (btn) => { btn.textContent = btn._orig; btn.disabled = false; };

    $("#atk-plan")?.addEventListener("click", async (e) => {
        busy(e.target, "building…");
        const { ok, body } = await _post(id, "plan");
        done(e.target);
        if (ok) renderPlan(body);
    });
    $("#atk-dry")?.addEventListener("click", async (e) => {
        busy(e.target, "checking…");
        const { ok, body } = await _post(id, "execute?execute=false");
        done(e.target);
        if (ok) {
            renderPlan(body);
            const s = $("#atk-summary");
            if (s) s.innerHTML += ` <span class="muted">· dry-run: ${(body.would_run || []).length} adb PoC(s) would fire (device ${body.device_connected ? "connected" : "OFFLINE"})</span>`;
        }
    });
    $("#atk-go")?.addEventListener("click", async (e) => {
        if (!confirm("Fire the adb PoCs against the connected device? This actively triggers the app.")) return;
        busy(e.target, "firing…");
        const { ok, status, body } = await _post(id, "execute?execute=true");
        done(e.target);
        if (ok) renderPlan(body);
        else if (status === 503) alert("No device connected — plug one in and authorise USB debugging.");
    });
}


export { mount_project_attack, view_project_attack };
