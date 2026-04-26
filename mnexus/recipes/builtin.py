"""In-tree Frida recipes — work without any external setup."""

from __future__ import annotations

# ─── iOS recipes ─────────────────────────────────────────────────────────

_IOS_SSL_KILL_SWITCH = """// ios_ssl_kill_switch — neutralizes Sec*/NSURLSession pinning callbacks.
// Adapted from SSL Kill Switch 2 + Frida CodeShare iOS pinning bypass scripts.
//
// Hooks:
//   - SecTrustEvaluateAsync     → always returns 0 (success)
//   - SSLSetSessionOption       → kSSLSessionOptionBreakOnServerAuth = false
//   - NSURLConnection delegate  → useCredential on every challenge
//
// Run with: frida -U -f <bundle.id> -l ios_ssl_kill_switch.js --no-pause

try {
    var SEC = 'Security';
    function replace(name, fn, signature) {
        var addr = Module.findExportByName(SEC, name);
        if (!addr) return;
        Interceptor.replace(addr, new NativeCallback(fn, signature[0], signature[1]));
        console.log('[NEXUS][SSL] hooked ' + name);
    }

    // SecTrustEvaluateAsync(SecTrustRef, dispatch_queue_t, SecTrustWithErrorCallback)
    replace('SecTrustEvaluateAsync',
        function (trust, queue, handler) { return 0; },
        ['int', ['pointer', 'pointer', 'pointer']]);

    // SecTrustEvaluate(SecTrustRef, SecTrustResultType*) → kSecTrustResultProceed
    var SecTrustEvaluate = Module.findExportByName(SEC, 'SecTrustEvaluate');
    if (SecTrustEvaluate) {
        Interceptor.replace(SecTrustEvaluate, new NativeCallback(function (trust, resultRef) {
            Memory.writeU32(resultRef, 1);  // kSecTrustResultProceed
            return 0;
        }, 'int', ['pointer', 'pointer']));
        console.log('[NEXUS][SSL] hooked SecTrustEvaluate');
    }

    // NSURLConnection / NSURLSession delegate
    if (ObjC.available) {
        var NSURLCredential = ObjC.classes.NSURLCredential;
        function neuter(klass, sel) {
            var m = ObjC.classes[klass] && ObjC.classes[klass][sel];
            if (!m) return;
            m.implementation = ObjC.implement(m, function (h, s, conn, ch) {
                var cred = NSURLCredential.credentialForTrust_(ch.protectionSpace().serverTrust());
                ch.sender().useCredential_forAuthenticationChallenge_(cred, ch);
            });
            console.log('[NEXUS][SSL] hooked ' + klass + ' ' + sel);
        }
        neuter('NSURLConnection',         '- connection:didReceiveAuthenticationChallenge:');
        neuter('NSURLSession',            '- URLSession:didReceiveChallenge:completionHandler:');
        neuter('NSURLSessionDelegate',    '- URLSession:didReceiveChallenge:completionHandler:');
        neuter('NSURLSessionTaskDelegate','- URLSession:task:didReceiveChallenge:completionHandler:');
    }
} catch (e) {
    console.log('[NEXUS][SSL] setup error: ' + e);
}
"""

_IOS_JAILBREAK_BYPASS = """// ios_jailbreak_bypass — covers tsProtector / JailProtect / Shadow / IOSSecuritySuite.
//
// Hooks:
//   - NSFileManager fileExistsAtPath:               → false on /Applications/Cydia.app, /var/lib/apt, etc.
//   - access(2), stat(2), lstat(2)                  → -1 on the same paths
//   - fork()                                        → -1 (App Store builds can't fork)
//   - canOpenURL: cydia://, sileo://, zbra://       → false
//   - dyld image scanning                           → drop tweak/substrate names
//
// Hostile to most off-the-shelf jailbreak detectors. Bring your own bypass
// for hand-rolled checks.

var JB_PATHS = [
    '/Applications/Cydia.app', '/Applications/Sileo.app', '/Applications/Zebra.app',
    '/Library/MobileSubstrate', '/Library/MobileSubstrate/MobileSubstrate.dylib',
    '/var/lib/apt', '/var/lib/cydia', '/private/var/lib/apt', '/private/var/lib/cydia',
    '/usr/sbin/sshd', '/usr/bin/ssh', '/etc/apt', '/bin/bash', '/usr/libexec/sftp-server',
    '/private/var/stash', '/private/var/tmp/cydia.log',
];

if (ObjC.available) {
    var NSFM = ObjC.classes.NSFileManager['- fileExistsAtPath:'];
    NSFM.implementation = ObjC.implement(NSFM, function (h, s, path) {
        var p = new ObjC.Object(path).toString();
        for (var i = 0; i < JB_PATHS.length; i++) {
            if (p.indexOf(JB_PATHS[i]) !== -1) {
                console.log('[NEXUS][JB] -fileExistsAtPath: hiding ' + p);
                return 0;
            }
        }
        return ObjC.classes.NSFileManager['- fileExistsAtPath:'].apply(this, arguments);
    });

    // -[UIApplication canOpenURL:]
    var canOpen = ObjC.classes.UIApplication['- canOpenURL:'];
    if (canOpen) {
        canOpen.implementation = ObjC.implement(canOpen, function (h, s, url) {
            var u = new ObjC.Object(url).toString();
            if (/^(cydia|sileo|zbra|undecimus)/.test(u)) {
                console.log('[NEXUS][JB] -canOpenURL: hiding ' + u);
                return 0;
            }
            return ObjC.classes.UIApplication['- canOpenURL:'].apply(this, arguments);
        });
    }
}

// access / stat / lstat / fork — POSIX layer
['access', 'stat', 'lstat', 'fopen'].forEach(function (fn) {
    var addr = Module.findExportByName(null, fn);
    if (!addr) return;
    Interceptor.attach(addr, {
        onEnter: function (args) {
            try {
                var path = args[0].readUtf8String();
                for (var i = 0; i < JB_PATHS.length; i++) {
                    if (path && path.indexOf(JB_PATHS[i]) !== -1) {
                        console.log('[NEXUS][JB] ' + fn + '("' + path + '") blocked');
                        this.blocked = true;
                        return;
                    }
                }
            } catch (e) {}
        },
        onLeave: function (retval) {
            if (this.blocked) {
                if (fn === 'fopen') retval.replace(ptr(0));
                else retval.replace(-1);
            }
        }
    });
});

var fork = Module.findExportByName(null, 'fork');
if (fork) {
    Interceptor.replace(fork, new NativeCallback(function () {
        console.log('[NEXUS][JB] fork() blocked');
        return -1;
    }, 'int', []));
}
"""

_IOS_KEYCHAIN_DUMP = """// ios_keychain_dump — enumerate every keychain query the app makes.
//
// Hooks SecItem* family, prints the query attributes and the data length.
// Read-only — does not modify or exfiltrate. Pair with `frida-trace` for
// deeper context.

var SEC = 'Security';
function trace(name) {
    var addr = Module.findExportByName(SEC, name);
    if (!addr) return;
    Interceptor.attach(addr, {
        onEnter: function (args) {
            var q = ObjC.available ? new ObjC.Object(args[0]) : '<no objc>';
            console.log('[NEXUS][KC] ' + name + ' query=' + q);
        },
        onLeave: function (retval) {
            console.log('[NEXUS][KC]   → status=' + retval.toInt32());
        }
    });
}
['SecItemCopyMatching', 'SecItemAdd', 'SecItemUpdate', 'SecItemDelete'].forEach(trace);
"""

# ─── Android recipes (the always-there auto recipe matches what main.py
#     used to inline; we keep that constant in the same place to keep the
#     recipes endpoint deterministic across reloads). ─────────────────────

_ANDROID_CIPHER_KEY_LEAK = """// cipher_key_leak — log every SecretKeySpec ctor + Cipher.doFinal.
Java.perform(function () {
    var KS = Java.use('javax.crypto.spec.SecretKeySpec');
    KS.$init.overload('[B', 'java.lang.String').implementation = function (k, alg) {
        console.log('[NEXUS][CRYPTO] key len=' + k.length + ' algo=' + alg);
        return this.$init(k, alg);
    };
    var Cipher = Java.use('javax.crypto.Cipher');
    Cipher.doFinal.overload('[B').implementation = function (input) {
        var out = this.doFinal(input);
        console.log('[NEXUS][CRYPTO] doFinal in=' + input.length + ' out=' + out.length);
        return out;
    };
});
"""


BUILTIN_RECIPES = [
    {
        "name": "ios_ssl_kill_switch",
        "origin": "builtin",
        "category": "SSL",
        "platform": "ios",
        "description": "Neutralize NSURLSession + Security framework pinning callbacks. Adapted from SSL Kill Switch 2.",
        "compatibility": "ios 13+ · jailbroken or with Frida gadget",
        "script": _IOS_SSL_KILL_SWITCH,
    },
    {
        "name": "ios_jailbreak_bypass",
        "origin": "builtin",
        "category": "RESILIENCE",
        "platform": "ios",
        "description": "Hide the classic jailbreak markers from in-app detection (file/access/canOpenURL/fork).",
        "compatibility": "ios 13+ · jailbroken or with Frida gadget",
        "script": _IOS_JAILBREAK_BYPASS,
    },
    {
        "name": "ios_keychain_dump",
        "origin": "builtin",
        "category": "STORAGE",
        "platform": "ios",
        "description": "Log every SecItem* call — copy/add/update/delete — with the query attributes.",
        "compatibility": "ios 13+ · jailbroken or with Frida gadget",
        "script": _IOS_KEYCHAIN_DUMP,
    },
    {
        "name": "cipher_key_leak",
        "origin": "builtin",
        "category": "CRYPTO",
        "platform": "android",
        "description": "Logs SecretKeySpec ctor args + Cipher.doFinal in/out. Bring popcorn.",
        "compatibility": "android · frida ≥ 16",
        "script": _ANDROID_CIPHER_KEY_LEAK,
    },
]
