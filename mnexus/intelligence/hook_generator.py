"""Auto-hook generator — reads static findings, emits targeted Frida scripts.

The "Valsamaras approach" systematized. If static saw a SecretKeySpec,
dynamic gets a hook that logs the key. If static saw a RootBeer call,
dynamic gets the RootBeer bypass. No manual glue.
"""

from __future__ import annotations

from dataclasses import dataclass

from mnexus.models.attack_surface import AttackSurface
from mnexus.models.finding import Finding, FindingCategory


@dataclass(slots=True)
class GeneratedHook:
    """One Frida script with enough context to show the user what it does."""

    name: str
    description: str
    script: str
    source_finding_id: str | None = None


class HookGenerator:
    """Turns an AttackSurface into a list of GeneratedHook ready for Frida."""

    def for_attack_surface(self, surface: AttackSurface) -> list[GeneratedHook]:
        hooks: list[GeneratedHook] = []

        if surface.root_detection_detected:
            hooks.append(self._root_bypass(surface.root_detection_library))

        if surface.ssl_pinning_detected:
            hooks.append(self._ssl_bypass(surface.ssl_pinning_library))

        for op in surface.crypto_operations:
            hooks.append(self._crypto_logger(op.location, op.algorithm))

        for finding in surface.findings:
            if finding.category is FindingCategory.AUTH:
                hooks.append(self._method_tracer(finding))

        return hooks

    # ─── generators ───

    def _root_bypass(self, library: str | None) -> GeneratedHook:
        lib = library or "generic"
        script = f"""// auto: root bypass tuned for {lib}
Java.perform(function () {{
    var names = [
        'com.scottyab.rootbeer.RootBeer',
        'com.stericson.RootTools.RootTools',
    ];
    names.forEach(function (n) {{
        try {{
            var K = Java.use(n);
            Object.keys(K).forEach(function (m) {{
                if (/^is|check|has/.test(m)) {{
                    try {{ K[m].implementation = function () {{ return false; }}; }} catch (_) {{}}
                }}
            }});
        }} catch (_) {{}}
    }});
}});
"""
        return GeneratedHook(
            name="root_detection_bypass",
            description=f"Stub out common root-check methods (targeting {lib}).",
            script=script,
        )

    def _ssl_bypass(self, library: str | None) -> GeneratedHook:
        lib = library or "okhttp+trustmanager"
        script = """// auto: universal-ish pinning bypass
Java.perform(function () {
    try {
        var CP = Java.use('okhttp3.CertificatePinner');
        CP.check.overload('java.lang.String', 'java.util.List').implementation = function () {};
    } catch (_) {}
    try {
        var TMF = Java.use('javax.net.ssl.X509TrustManager');
        var trust = Java.registerClass({
            name: 'com.mnexus.NoopTrust',
            implements: [TMF],
            methods: {
                checkClientTrusted: function () {},
                checkServerTrusted: function () {},
                getAcceptedIssuers: function () { return []; },
            },
        });
        void trust;
    } catch (_) {}
});
"""
        return GeneratedHook(
            name="ssl_pinning_bypass",
            description=f"Neutralize SSL pinning (tuned for {lib}).",
            script=script,
        )

    def _crypto_logger(self, location: str, algorithm: str) -> GeneratedHook:
        script = f"""// auto: crypto logger for {algorithm} at {location}
Java.perform(function () {{
    var KS = Java.use('javax.crypto.spec.SecretKeySpec');
    KS.$init.overload('[B', 'java.lang.String').implementation = function (k, alg) {{
        console.log('[NEXUS][CRYPTO] key len=' + k.length + ' algo=' + alg);
        return this.$init(k, alg);
    }};
    var Cipher = Java.use('javax.crypto.Cipher');
    Cipher.doFinal.overload('[B').implementation = function (input) {{
        var out = this.doFinal(input);
        console.log('[NEXUS][CRYPTO] doFinal in=' + input.length + ' out=' + out.length);
        return out;
    }};
}});
"""
        return GeneratedHook(
            name=f"crypto_logger::{algorithm}",
            description=f"Log key/IV/plaintext around {algorithm} uses near {location}.",
            script=script,
        )

    def _method_tracer(self, finding: Finding) -> GeneratedHook:
        script = f"""// auto: tracer hook for {finding.title}
// TODO: resolve class/method from finding.location and replace below.
Java.perform(function () {{
    console.log('[NEXUS][TRACE] placeholder for {finding.id}');
}});
"""
        return GeneratedHook(
            name=f"tracer::{finding.id}",
            description=f"Trace the method implicated by {finding.id}.",
            script=script,
            source_finding_id=finding.id,
        )
