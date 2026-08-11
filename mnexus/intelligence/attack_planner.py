"""Attack planner — turn a static surface into concrete exploitation paths.

Offline and deterministic: no device, no network, no side effects. For every
angle it recognises it emits an :class:`ExploitAttempt` with a ready-to-run
PoC and a ``PROVABLE`` verdict; the :mod:`attack_runner` later upgrades the
runnable ones to ``CONFIRMED`` (or ``DISPROVEN``) against a live device.

Coverage, in the order the report reads best:

  1. Frida PoCs synthesised from the surface (SSL-pin / root bypass, crypto
     loggers, method tracers) — reuses :class:`HookGenerator` so there's one
     source of truth for the scripts.
  2. Unprotected exported components → ``adb am start/startservice/broadcast``.
  3. Deep links → ``adb am start -a VIEW -d`` (+ the drive-by HTML endpoint).
  4. Firebase-shaped findings → an unauthenticated ``curl`` read.
  5. Anything CRITICAL/HIGH left uncovered → a MANUAL attempt so the report
     never quietly drops a blocker just because we lack a template for it.
"""

from __future__ import annotations

import re
import shlex

from mnexus.intelligence.hook_generator import HookGenerator
from mnexus.models.exploit import ExploitAttempt, ExploitVerdict, PocKind
from mnexus.models.finding import Finding, Severity
from mnexus.models.project import Project

# Default mitigations for technique classes that don't ride on a single
# finding's remediation. Kept accurate — these are the real controls.
_TECH_MITIGATION = {
    "ssl-pin-bypass": (
        "Pin with a backup key set and fail closed; pair pinning with Frida/root "
        "detection that refuses to run when the trust store is tampered with."
    ),
    "root-bypass": (
        "Treat root detection as defence-in-depth, never a sole control. Move "
        "secrets server-side so a rooted device can't extract anything of value."
    ),
    "crypto-logger": (
        "Stop deriving keys on-device; use the Android Keystore / iOS Keychain "
        "with hardware backing and AEAD (AES/GCM) so logged calls reveal nothing."
    ),
    "method-tracer": (
        "Obfuscate + integrity-check sensitive methods; assume anything traceable "
        "at runtime is readable by an attacker and keep trust decisions server-side."
    ),
}

_FIREBASE_RE = re.compile(r"https?://[a-z0-9.\-]+\.firebaseio\.com|[a-z0-9\-]+\.firebaseio\.com|firebase", re.I)
_RTDB_URL_RE = re.compile(r"https?://[a-z0-9.\-]+\.firebaseio\.com", re.I)


def plan_attacks(project: Project) -> list[ExploitAttempt]:
    """Map ``project``'s static surface to exploitation attempts. Pure."""
    surface = project.attack_surface
    if surface is None:
        return []

    pkg = project.package_name or "com.target.app"
    findings = list(surface.findings)
    by_id = {f.id: f for f in findings}
    attempts: list[ExploitAttempt] = []
    covered: set[str] = set()

    # 1. Frida PoCs (reuse the hook synthesiser).
    for hook in HookGenerator().for_attack_surface(surface, platform=project.platform):
        technique, title, target = _frida_meta(hook.name)
        mitigation = _mitigation_for(hook.source_finding_id, by_id, technique)
        attempts.append(ExploitAttempt(
            technique=technique,
            title=title,
            finding_id=hook.source_finding_id,
            target=target,
            verdict=ExploitVerdict.PROVABLE,
            poc_kind=PocKind.FRIDA,
            poc=hook.script,
            rationale=hook.description,
            mitigation=mitigation,
            requires_device=True,
        ))
        if hook.source_finding_id:
            covered.add(hook.source_finding_id)

    # 2. Unprotected exported components (Android).
    for comp in surface.exported_components:
        if not comp.unprotected:
            continue
        attempts.append(_component_attempt(pkg, comp))

    # 3. Deep links.
    for uri in surface.deeplinks:
        attempts.append(_deeplink_attempt(pkg, uri))

    # 4. Firebase-shaped findings.
    for f in findings:
        if f.id in covered:
            continue
        if _looks_firebase(f):
            attempts.append(_firebase_attempt(f))
            covered.add(f.id)

    # 5. MANUAL fallback for uncovered blockers — never silently drop a CRIT/HIGH.
    for f in findings:
        if f.id in covered:
            continue
        if f.severity in (Severity.CRITICAL, Severity.HIGH):
            attempts.append(ExploitAttempt(
                technique="manual-review",
                title=f"Manual PoC — {f.title}",
                finding_id=f.id,
                target=f.location or "",
                verdict=ExploitVerdict.MANUAL,
                poc_kind=PocKind.NONE,
                rationale=f"No automated template for this {f.category.value} finding; "
                          f"exploitability needs a hands-on repro.",
                mitigation=f.remediation or "See the finding's remediation.",
            ))
            covered.add(f.id)

    return attempts


# ─── technique builders ─────────────────────────────────────────────────


def _frida_meta(hook_name: str) -> tuple[str, str, str]:
    """Map a GeneratedHook name to (technique slug, title, target)."""
    if hook_name.startswith(("ssl_pinning_bypass", "ios_ssl_kill_switch")):
        return "ssl-pin-bypass", "Bypass TLS certificate pinning", "TLS pinning"
    if hook_name.startswith(("root_detection_bypass", "ios_jailbreak_bypass")):
        return "root-bypass", "Defeat root/jailbreak detection", "root detection"
    if hook_name.startswith(("crypto_logger", "ios_cccrypt_logger")):
        alg = hook_name.split("::", 1)[1] if "::" in hook_name else ""
        return "crypto-logger", f"Log crypto operations{f' ({alg})' if alg else ''}", alg
    if hook_name.startswith("ios_keychain_dump"):
        return "keychain-dump", "Dump the iOS keychain", "keychain"
    if hook_name.startswith("tracer::"):
        return "method-tracer", "Trace the class methods at runtime", hook_name.split("::", 1)[1]
    return "frida-hook", f"Run the {hook_name} hook", hook_name


def _component_attempt(pkg: str, comp) -> ExploitAttempt:  # type: ignore[no-untyped-def]
    """Build an adb invocation for an unprotected exported component."""
    ctype = (comp.component_type or "").lower()
    target = f"{pkg}/{comp.name}"
    base = "adb shell am"
    if ctype == "activity":
        poc = f"{base} start -n {shlex.quote(target)}"
        verb = "start the activity"
    elif ctype == "service":
        poc = f"{base} startservice -n {shlex.quote(target)}"
        verb = "start the service"
    elif ctype == "receiver":
        poc = f"{base} broadcast -n {shlex.quote(target)}"
        verb = "deliver a broadcast to the receiver"
    else:  # provider or unknown → not a one-liner am invocation
        return ExploitAttempt(
            technique="exported-provider",
            title=f"Exported {ctype or 'component'}: {comp.name}",
            target=target,
            verdict=ExploitVerdict.MANUAL,
            poc_kind=PocKind.NONE,
            rationale=f"'{comp.name}' is exported with no permission; a provider "
                      "needs a content:// path enumerated by hand to demonstrate access.",
            mitigation="Set android:exported=\"false\" or guard it with a signature-level permission.",
        )
    return ExploitAttempt(
        technique=f"exported-{ctype}",
        title=f"Invoke exported {ctype}: {comp.name}",
        target=target,
        verdict=ExploitVerdict.PROVABLE,
        poc_kind=PocKind.ADB,
        poc=poc,
        rationale=f"'{comp.name}' is exported with no permission — any app can {verb}.",
        mitigation="Set android:exported=\"false\" if it isn't a genuine entry point, "
                   "or guard it with a signature-level permission and validate every extra.",
        requires_device=True,
    )


def _deeplink_attempt(pkg: str, uri: str) -> ExploitAttempt:
    poc = f"adb shell am start -W -a android.intent.action.VIEW -d {shlex.quote(uri)}"
    return ExploitAttempt(
        technique="deeplink",
        title=f"Fire deep link: {uri}",
        target=uri,
        verdict=ExploitVerdict.PROVABLE,
        poc_kind=PocKind.ADB,
        poc=poc,
        rationale=f"'{uri}' resolves without a permission prompt; a hostile web page "
                  "can trigger it (see GET /v1/projects/{id}/mango/deeplink/poc for a drive-by).",
        mitigation="Validate + sanitise every deep-link parameter, require app-links "
                   "(autoVerify) so arbitrary sites can't forge the host, and never route "
                   "a deep link straight into a privileged action.",
        requires_device=True,
    )


def _looks_firebase(f: Finding) -> bool:
    hay = f"{f.title}\n{f.evidence}\n{f.location or ''}"
    return bool(_FIREBASE_RE.search(hay))


def _firebase_attempt(f: Finding) -> ExploitAttempt:
    m = _RTDB_URL_RE.search(f"{f.evidence}\n{f.title}")
    base = m.group(0).rstrip("/") if m else "https://<project>.firebaseio.com"
    poc = f"curl -s {shlex.quote(base + '/.json')}"
    return ExploitAttempt(
        technique="firebase-open-db",
        title="Read the Firebase Realtime Database unauthenticated",
        finding_id=f.id,
        target=base,
        verdict=ExploitVerdict.PROVABLE,
        poc_kind=PocKind.CURL,
        poc=poc,
        rationale="The RTDB root answers an unauthenticated GET — a `200` with JSON "
                  "means the rules are wide open.",
        mitigation=f.remediation or (
            "Lock the RTDB rules to authenticated, per-user paths "
            "(`auth != null` at minimum); default-open rules leak the whole tree."
        ),
    )


def _mitigation_for(finding_id: str | None, by_id: dict[str, Finding], technique: str) -> str:
    if finding_id and finding_id in by_id and by_id[finding_id].remediation:
        return by_id[finding_id].remediation  # type: ignore[return-value]
    return _TECH_MITIGATION.get(technique, "Apply the platform control for this weakness (see the finding).")
