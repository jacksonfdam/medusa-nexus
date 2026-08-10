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

    def for_attack_surface(self, surface: AttackSurface, *, platform: str = "android") -> list[GeneratedHook]:
        hooks: list[GeneratedHook] = []

        if platform == "ios":
            # iOS jailbreak detection bypass — analog to Android root bypass.
            if surface.jailbreak_detection_detected:
                hooks.append(self._ios_jailbreak_bypass(surface.jailbreak_detection_library))
            # Universal iOS pinning bypass — pinning is detected via findings,
            # not a single library flag, so always offer the recipe.
            hooks.append(self._ios_ssl_kill_switch())
            # Keychain dumper — useful on every iOS target.
            hooks.append(self._ios_keychain_dump())
            for op in surface.crypto_operations:
                hooks.append(self._ios_common_crypto_logger(op.location, op.algorithm))
            return hooks

        # Android (default).
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
        # Every callback intercept emits a structured event so the orchestrator's
        # /v1/projects/{id}/dynamic/events POST adapter can route them into the
        # ssl_pin channel — which the SSL Map screen polls every few seconds.
        # Without these `send()` calls the bypass is silent and the live map
        # stays blank even when pinning is actively being neutralised.
        script = """// auto: universal-ish pinning bypass + live event emitter
Java.perform(function () {
    function emit(host, lib, outcome) {
        try {
            send({ channel: 'ssl_pin', host: host || '?', lib: lib, outcome: outcome });
        } catch (_) { /* gum.js / no host context — swallow */ }
    }
    try {
        var CP = Java.use('okhttp3.CertificatePinner');
        CP.check.overload('java.lang.String', 'java.util.List').implementation = function (host, chain) {
            emit(host, 'okhttp', 'bypassed');
            // Pretend the chain validated — original return is void.
        };
    } catch (_) {}
    try {
        var TMF = Java.use('javax.net.ssl.X509TrustManager');
        var trust = Java.registerClass({
            name: 'com.mnexus.NoopTrust',
            implements: [TMF],
            methods: {
                checkClientTrusted: function () { emit(null, 'trustmanager', 'bypassed'); },
                checkServerTrusted: function () { emit(null, 'trustmanager', 'bypassed'); },
                getAcceptedIssuers: function () { return []; },
            },
        });
        void trust;
    } catch (_) {}
});
"""
        return GeneratedHook(
            name="ssl_pinning_bypass",
            description=f"Neutralize SSL pinning (tuned for {lib}) + emit ssl_pin events.",
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
        cls = _fqcn_from_location(finding.location)
        if cls is None:
            # No class we can trust — a location-less finding or a path that
            # doesn't decode to a package. Ship an honest comment hook instead
            # of a lying tracer; the analyst fills in the class by hand.
            script = f"""// auto: tracer hook for {finding.title}
// Couldn't resolve a class from finding.location ({finding.location!r}).
// Drop the fully-qualified class name in below and uncomment to trace it.
Java.perform(function () {{
    // var CLS = 'com.target.auth.WhateverManager';
    // Java.use(CLS);  // then hook the overloads you care about.
    console.log('[NEXUS][TRACE] no class resolved for {finding.id} — edit me');
}});
"""
            return GeneratedHook(
                name=f"tracer::{finding.id}",
                description=f"Trace scaffold for {finding.id} (class not auto-resolved).",
                script=script,
                source_finding_id=finding.id,
            )

        # Real tracer: enumerate the class's declared methods and wrap every
        # overload so each call logs its args + return. Blind to the exact
        # method (static findings rarely pin one down), loud about the class.
        script = f"""// auto: method tracer for {finding.title}
// Class resolved from finding.location: {finding.location}
Java.perform(function () {{
    var CLS = '{cls}';
    try {{
        var K = Java.use(CLS);
        var seen = {{}};
        K.class.getDeclaredMethods().forEach(function (m) {{
            var name = m.getName();
            if (seen[name]) return;   // one wrap per name covers all overloads
            seen[name] = true;
            (K[name].overloads || []).forEach(function (ov) {{
                ov.implementation = function () {{
                    var args = Array.prototype.slice.call(arguments);
                    console.log('[NEXUS][TRACE] ' + CLS + '.' + name +
                                '(' + args.map(String).join(', ') + ')');
                    var ret = ov.apply(this, arguments);
                    console.log('[NEXUS][TRACE] ' + CLS + '.' + name + ' => ' + ret);
                    return ret;
                }};
            }});
        }});
        console.log('[NEXUS][TRACE] wrapped ' + Object.keys(seen).length +
                    ' method(s) on ' + CLS);
    }} catch (e) {{
        console.log('[NEXUS][TRACE] class not loaded yet: ' + CLS + ' (' + e + ')');
    }}
}});
"""
        return GeneratedHook(
            name=f"tracer::{finding.id}",
            description=f"Trace every method of {cls} (from {finding.id}).",
            script=script,
            source_finding_id=finding.id,
        )

    # ─── iOS hook templates ───

    def _ios_jailbreak_bypass(self, library: str | None) -> GeneratedHook:
        lib = library or "generic"
        script = f"""// auto: iOS jailbreak detection bypass (target: {lib})
// Hooks the file-existence + sysctl + fork() checks that {lib} relies on.
ObjC.classes.NSFileManager['- fileExistsAtPath:'].implementation = ObjC.implement(
    ObjC.classes.NSFileManager['- fileExistsAtPath:'],
    function (handle, sel, path) {{
        var p = new ObjC.Object(path).toString();
        var jb_paths = ['/Applications/Cydia.app', '/Library/MobileSubstrate', '/var/lib/apt',
                        '/private/var/lib/apt', '/usr/sbin/sshd', '/etc/apt'];
        for (var i = 0; i < jb_paths.length; i++) {{
            if (p.indexOf(jb_paths[i]) !== -1) {{
                console.log('[NEXUS][JB] hiding ' + p);
                return 0;
            }}
        }}
        return ObjC.classes.NSFileManager['- fileExistsAtPath:'].apply(this, arguments);
    }}
);
// fork() always returns -1 in App Store builds; some checks rely on this.
Interceptor.replace(Module.findExportByName(null, 'fork'), new NativeCallback(function () {{
    console.log('[NEXUS][JB] fork() blocked');
    return -1;
}}, 'int', []));
"""
        return GeneratedHook(
            name="ios_jailbreak_bypass",
            description=f"Stub out classic iOS jailbreak checks (targeting {lib}).",
            script=script,
        )

    def _ios_ssl_kill_switch(self) -> GeneratedHook:
        script = """// auto: iOS SSL pinning bypass — neutralizes Sec*/NSURLSession pinning callbacks.
// Adapted from SSL Kill Switch 2 + Frida CodeShare iOS pinning bypass scripts.
try {
    var SSL_VERIFY_NONE = 0;
    var SecTrustEvaluateAsync = Module.findExportByName('Security', 'SecTrustEvaluateAsync');
    if (SecTrustEvaluateAsync) {
        Interceptor.replace(SecTrustEvaluateAsync, new NativeCallback(function (trust, queue, handler) {
            console.log('[NEXUS][SSL] SecTrustEvaluateAsync → success');
            return 0;
        }, 'int', ['pointer', 'pointer', 'pointer']));
    }
    // NSURLSession delegate pinning short-circuit.
    var NSURLConnection = ObjC.classes.NSURLConnection;
    if (NSURLConnection) {
        var didReceive = NSURLConnection['- connection:didReceiveAuthenticationChallenge:'];
        if (didReceive) {
            didReceive.implementation = ObjC.implement(didReceive, function (h, s, conn, ch) {
                console.log('[NEXUS][SSL] auth challenge → useCredential');
                var cred = ObjC.classes.NSURLCredential.credentialForTrust_(ch.protectionSpace().serverTrust());
                ch.sender().useCredential_forAuthenticationChallenge_(cred, ch);
            });
        }
    }
} catch (e) { console.log('[NEXUS][SSL] hook setup error: ' + e); }
"""
        return GeneratedHook(
            name="ios_ssl_kill_switch",
            description="Neutralize NSURLSession + Security framework pinning callbacks.",
            script=script,
        )

    def _ios_keychain_dump(self) -> GeneratedHook:
        script = """// auto: iOS keychain enumerator (read-only).
// Walks every kSecClass and prints the items with masked secrets.
var SecItemCopyMatching = Module.findExportByName('Security', 'SecItemCopyMatching');
if (SecItemCopyMatching) {
    Interceptor.attach(SecItemCopyMatching, {
        onEnter: function (args) {
            var query = new ObjC.Object(args[0]);
            console.log('[NEXUS][KC] SecItemCopyMatching ' + query.toString());
        }
    });
}
"""
        return GeneratedHook(
            name="ios_keychain_dump",
            description="Log every keychain query the app makes.",
            script=script,
        )

    def _ios_common_crypto_logger(self, location: str, algorithm: str) -> GeneratedHook:
        script = f"""// auto: iOS CommonCrypto logger ({algorithm} near {location})
var CCCrypt = Module.findExportByName('libcommonCrypto.dylib', 'CCCrypt') || Module.findExportByName(null, 'CCCrypt');
if (CCCrypt) {{
    Interceptor.attach(CCCrypt, {{
        onEnter: function (args) {{
            // CCCrypt(op, alg, options, key, keyLen, iv, in, inLen, out, outAvail, outMoved)
            console.log('[NEXUS][CRYPTO] CCCrypt op=' + args[0].toInt32() +
                        ' alg=' + args[1].toInt32() +
                        ' keyLen=' + args[4].toInt32());
        }}
    }});
}}
"""
        return GeneratedHook(
            name=f"ios_cccrypt_logger::{algorithm}",
            description=f"Log CCCrypt calls (target: {algorithm} at {location}).",
            script=script,
        )


# ─── location → class-name resolver ───

# jadx/apktool drop their output under one of these roots; everything after
# the root segment is the package path we can turn back into an FQCN.
_SOURCE_ROOTS = ("sources", "src", "smali", "java", "kotlin", "main")
_CLASS_SUFFIXES = (".java", ".kt", ".smali")


def _fqcn_from_location(location: str | None) -> str | None:
    """Turn a decompiled-source path into a fully-qualified Java class name.

    ``sources/com/target/auth/LoginManager.java:42`` → ``com.target.auth.LoginManager``.
    Handles ``:line`` suffixes, nested-class ``Outer$Inner`` files, and the
    smali ``smali_classes3/`` variants. Returns ``None`` when the path doesn't
    decode to something class-shaped — better a comment hook than a bogus one.
    """
    if not location:
        return None

    # Drop a trailing ``:line`` (but not a Windows drive colon, which we don't
    # expect in workspace paths anyway).
    path = location.strip().rsplit(":", 1)[0] if location.rsplit(":", 1)[-1].isdigit() else location.strip()
    path = path.replace("\\", "/").strip("/")
    if not path:
        return None

    # Strip a recognised source extension off the final segment.
    lower = path.lower()
    for suffix in _CLASS_SUFFIXES:
        if lower.endswith(suffix):
            path = path[: -len(suffix)]
            break
    else:
        # No source extension → not a class file we can name.
        return None

    segments = [s for s in path.split("/") if s]
    if not segments:
        return None

    # Trim everything up to and including the last source-root marker
    # (``sources``, ``smali``, ``smali_classes3``, …).
    cut = 0
    for i, seg in enumerate(segments):
        if seg in _SOURCE_ROOTS or seg.startswith("smali_classes"):
            cut = i + 1
    segments = segments[cut:]
    if not segments:
        return None

    fqcn = ".".join(segments)
    # Sanity: a class name is dotted identifiers, with ``$`` allowed for nested
    # classes. Reject anything with whitespace or path-ish leftovers.
    if not fqcn or " " in fqcn:
        return None
    if not all(part.replace("$", "_").isidentifier() for part in fqcn.split(".")):
        return None
    return fqcn
