"""IPATool engine — iOS analog to APKToolEngine. Built-in, no external deps.

An `.ipa` is a zip with `Payload/<App>.app/`. Inside the .app:
  - `Info.plist`            — bundle metadata (binary plist on real builds).
  - `embedded.mobileprovision` — CMS-wrapped XML plist with signing data.
  - The Mach-O main executable (binary, named in `CFBundleExecutable`).
  - `Frameworks/*.framework/` — embedded shared libs.
  - assets, .nib, .car etc — ignored here.

We parse Info.plist + entitlements + provisioning profile + framework list
without shelling out to anything. Findings cover the OWASP MASTG-iOS controls
that are observable from static metadata alone. Deeper Mach-O scanning is the
GhidraEngine's job (it now handles both ELF and Mach-O).
"""

from __future__ import annotations

import plistlib
import re
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.attack_surface import NativeLibrary
from mnexus.models.finding import Finding, FindingCategory, Severity


# ─── Mach-O magic numbers ────────────────────────────────────────────────
_MACHO_MAGIC = (
    b"\xfe\xed\xfa\xce",  # MH_MAGIC      32-bit BE
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64   64-bit BE
    b"\xce\xfa\xed\xfe",  # MH_CIGAM      32-bit LE
    b"\xcf\xfa\xed\xfe",  # MH_CIGAM_64   64-bit LE
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC     fat / universal
    b"\xbe\xba\xfe\xca",  # FAT_CIGAM
)


class IPAToolEngine(BaseEngine):
    """Reads an IPA + parses every static-detectable iOS metadata source."""

    @property
    def name(self) -> str:
        return "ipatool"

    @property
    def capabilities(self) -> list[str]:
        return ["ipa_decode", "info_plist", "entitlements", "provisioning"]

    async def health_check(self) -> EngineStatus:
        return EngineStatus(
            name=self.name,
            installed=True,
            version="builtin",
            path="(built-in zip + plistlib parser)",
            message="ready — no external deps",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Parse the IPA's metadata and emit static iOS findings."""
        meta = self.parse_ipa(context.apk_path)
        if context.extras is None:
            context.extras = {}
        context.extras["ipa_meta"] = meta

        findings: list[Finding] = []

        # ─── ATS / cleartext / arbitrary-loads ─────────────────────────
        ats = meta.get("app_transport_security") or {}
        if ats.get("NSAllowsArbitraryLoads") is True:
            findings.append(Finding(
                title="App Transport Security disabled (NSAllowsArbitraryLoads=true)",
                description=(
                    "`Info.plist` declares `NSAppTransportSecurity.NSAllowsArbitraryLoads = true`. "
                    "Apple's TLS-by-default policy is fully bypassed — every NSURLSession can talk plain HTTP "
                    "to any host."
                ),
                severity=Severity.HIGH,
                category=FindingCategory.NETWORK,
                source_engine=self.name,
                evidence="NSAppTransportSecurity.NSAllowsArbitraryLoads = true",
                location="Info.plist",
                cwe_id="CWE-319",
                masvs="MSTG-NETWORK-2",
                platform_hint="ios",
                remediation=(
                    "Remove the global override. If specific hosts genuinely need cleartext, scope them via "
                    "`NSExceptionDomains` with `NSIncludesSubdomains` and `NSExceptionAllowsInsecureHTTPLoads` "
                    "set per-host, and document each exception."
                ),
            ))
        for host, domain_cfg in (ats.get("NSExceptionDomains") or {}).items():
            if not isinstance(domain_cfg, dict):
                continue
            if domain_cfg.get("NSExceptionAllowsInsecureHTTPLoads"):
                findings.append(Finding(
                    title=f"ATS exception allows cleartext to {host}",
                    description=f"`NSExceptionDomains.{host}.NSExceptionAllowsInsecureHTTPLoads = true`.",
                    severity=Severity.MEDIUM,
                    category=FindingCategory.NETWORK,
                    source_engine=self.name,
                    evidence=f"NSExceptionDomains.{host}.NSExceptionAllowsInsecureHTTPLoads = true",
                    location="Info.plist",
                    cwe_id="CWE-319",
                    masvs="MSTG-NETWORK-2",
                    platform_hint="ios",
                ))

        # ─── Debuggable signing ────────────────────────────────────────
        ents = meta.get("entitlements") or {}
        if ents.get("get-task-allow") is True:
            findings.append(Finding(
                title="App is signed with `get-task-allow` (debuggable)",
                description=(
                    "The embedded provisioning profile grants `get-task-allow`, which permits attaching a "
                    "debugger to the running process. Apple won't accept this on the App Store, so it usually "
                    "means an enterprise build leaked or a developer build was distributed by mistake."
                ),
                severity=Severity.HIGH,
                category=FindingCategory.CODE,
                source_engine=self.name,
                evidence="entitlements: get-task-allow = true",
                location="embedded.mobileprovision",
                cwe_id="CWE-489",
                masvs="MSTG-CODE-2",
                platform_hint="ios",
                remediation="Re-sign the build with a distribution profile (`get-task-allow=false`).",
            ))

        # ─── Provisioning profile expiry ───────────────────────────────
        prov = meta.get("provisioning_profile") or {}
        if expiry := prov.get("expires_at"):
            try:
                expires = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
                now = datetime.now(UTC)
                if expires < now:
                    findings.append(Finding(
                        title="Embedded provisioning profile is expired",
                        description=f"Profile expired at {expiry}. Installs will fail on real devices.",
                        severity=Severity.LOW,
                        category=FindingCategory.CODE,
                        source_engine=self.name,
                        evidence=f"ExpirationDate = {expiry}",
                        location="embedded.mobileprovision",
                        platform_hint="ios",
                    ))
            except (ValueError, TypeError):
                pass

        # ─── URL schemes — soft signal unless openly broad ─────────────
        for scheme in meta.get("url_schemes") or []:
            if scheme.lower() in ("http", "https", "file"):
                findings.append(Finding(
                    title=f"App registers a high-risk URL scheme: {scheme}",
                    description=(
                        f"`{scheme}://` is a system-reserved scheme. Registering it can hijack browser navigation "
                        "or claim file access from other apps. Universal Links are the modern, validated alternative."
                    ),
                    severity=Severity.MEDIUM,
                    category=FindingCategory.IPC,
                    source_engine=self.name,
                    evidence=f"CFBundleURLTypes → CFBundleURLSchemes contains '{scheme}'",
                    location="Info.plist",
                    masvs="MSTG-PLATFORM-3",
                    platform_hint="ios",
                ))

        # ─── App Extensions — surface area worth knowing ───────────────
        if meta.get("contains_app_extensions"):
            findings.append(Finding(
                title=f"App ships {len(meta['app_extensions'])} extension(s)",
                description="Extensions widen the attack surface (NSExtensionPrincipalClass, sharedContainer paths).",
                severity=Severity.INFO,
                category=FindingCategory.IPC,
                source_engine=self.name,
                evidence=", ".join(meta["app_extensions"][:5]),
                location="Payload/*.appex/Info.plist",
                platform_hint="ios",
            ))

        # ─── Native frameworks → AttackSurface.native_libraries ────────
        # (the orchestrator picks these up via context.extras)

        return findings

    # ─── public helpers ─────────────────────────────────────────────────

    def parse_ipa(self, ipa_path: Path) -> dict[str, Any]:
        """Open the IPA, parse all static metadata into a structured dict."""
        meta: dict[str, Any] = {
            "bundle_id": "",
            "version_name": "",
            "version_code": "",
            "min_os": "",
            "executable": "",
            "platform": "ios",
            "url_schemes": [],
            "app_transport_security": {},
            "permissions": [],          # iOS Privacy keys (NSCameraUsageDescription etc.)
            "exported_components": [],  # always [] on iOS — kept for shape compat
            "deeplinks": [],            # union of url_schemes + universal links
            "entitlements": {},
            "provisioning_profile": {},
            "native_libraries": [],     # embedded frameworks + main binary
            "frameworks": [],
            "sdk_fingerprint": {},
            "app_extensions": [],
            "contains_app_extensions": False,
            "all_files": [],
            "dex_files": [],            # always [] on iOS — kept for shape compat
        }
        if not ipa_path.exists():
            return meta
        try:
            with zipfile.ZipFile(ipa_path) as zf:
                names = zf.namelist()
                meta["all_files"] = names

                # Locate the main .app bundle: Payload/<X>.app/.
                app_dirs = sorted(
                    {n.split("/")[1] for n in names if n.startswith("Payload/") and ".app/" in n}
                )
                if not app_dirs:
                    return meta
                app_root = f"Payload/{app_dirs[0]}/"
                meta["app_bundle"] = app_dirs[0]

                # Info.plist (binary or XML).
                info_path = app_root + "Info.plist"
                if info_path in names:
                    info = _read_plist(zf.read(info_path))
                    if info:
                        meta["bundle_id"] = info.get("CFBundleIdentifier", "") or ""
                        meta["version_name"] = info.get("CFBundleShortVersionString", "") or ""
                        meta["version_code"] = str(info.get("CFBundleVersion", "") or "")
                        meta["min_os"] = info.get("MinimumOSVersion", "") or ""
                        meta["executable"] = info.get("CFBundleExecutable", "") or ""
                        meta["app_transport_security"] = info.get("NSAppTransportSecurity") or {}
                        # CFBundleURLTypes is a list of dicts containing CFBundleURLSchemes.
                        url_schemes: list[str] = []
                        for url_type in info.get("CFBundleURLTypes") or []:
                            if not isinstance(url_type, dict):
                                continue
                            url_schemes.extend(url_type.get("CFBundleURLSchemes") or [])
                        meta["url_schemes"] = sorted({s for s in url_schemes if s})
                        # iOS Privacy keys → "permissions" for shape compat with Android UI
                        privacy = [k for k in info.keys() if k.startswith("NS") and k.endswith("UsageDescription")]
                        meta["permissions"] = privacy

                # Embedded provisioning profile (CMS-wrapped XML plist).
                prov_path = app_root + "embedded.mobileprovision"
                if prov_path in names:
                    meta["provisioning_profile"] = _parse_provisioning(zf.read(prov_path))
                    meta["entitlements"] = (meta["provisioning_profile"] or {}).get("entitlements") or {}

                # Frameworks and Mach-O binaries inside the bundle.
                # Path shape: Payload/<App>.app/Frameworks/<X>.framework/<X>
                fw_root = app_root + "Frameworks/"
                for n in names:
                    if not n.startswith(fw_root):
                        continue
                    parts = n.split("/")
                    # parts: ["Payload", "App.app", "Frameworks", "X.framework", ...optional sub]
                    if len(parts) < 4:
                        continue
                    fw_dir = parts[3]
                    if not fw_dir.endswith(".framework"):
                        continue
                    if fw_dir not in [f["name"] for f in meta["frameworks"]]:
                        meta["frameworks"].append({
                            "name": fw_dir,
                            "path": "/".join(parts[:4]) + "/",
                        })

                # Mach-O scan: main binary + every framework's binary, recorded
                # as native_libraries so they show up under "Frameworks" in the UI.
                main_bin_path = app_root + meta["executable"] if meta["executable"] else ""
                if main_bin_path and main_bin_path in names:
                    meta["native_libraries"].append({
                        "path": main_bin_path,
                        "arch": _detect_macho_arch(zf.read(main_bin_path)),
                        "size_bytes": zf.getinfo(main_bin_path).file_size,
                    })
                for fw in meta["frameworks"]:
                    fw_name = fw["name"][:-len(".framework")]
                    fw_bin = fw["path"] + fw_name
                    if fw_bin in names:
                        meta["native_libraries"].append({
                            "path": fw_bin,
                            "arch": _detect_macho_arch(zf.read(fw_bin)),
                            "size_bytes": zf.getinfo(fw_bin).file_size,
                        })

                # PlugIns/.appex bundles → app extensions.
                pi_root = app_root + "PlugIns/"
                ext_names: set[str] = set()
                for n in names:
                    if n.startswith(pi_root) and ".appex/" in n:
                        ext_names.add(n[len(pi_root):].split("/")[0])
                meta["app_extensions"] = sorted(ext_names)
                meta["contains_app_extensions"] = bool(ext_names)

                # SDK fingerprint via framework names + main binary strings.
                fp: dict[str, str] = {}
                for fw in meta["frameworks"]:
                    name = fw["name"][:-len(".framework")]
                    if name in _IOS_SDK_NAMES:
                        fp[_IOS_SDK_NAMES[name]] = "embedded framework"
                # Heuristic class strings in the main binary.
                if main_bin_path and main_bin_path in names:
                    try:
                        head = zf.read(main_bin_path)[:512_000]  # 500 KB peek
                        for needle, label in _IOS_BINARY_SIGNATURES:
                            if needle in head and label not in fp:
                                fp[label] = "main binary string"
                    except Exception:  # noqa: BLE001
                        pass
                meta["sdk_fingerprint"] = fp

                # Deep-links: URL schemes + universal-link associated domains.
                associated = (meta["entitlements"] or {}).get("com.apple.developer.associated-domains") or []
                ulinks = [a for a in associated if isinstance(a, str) and a.startswith("applinks:")]
                meta["deeplinks"] = sorted(set(meta["url_schemes"]) | {a[len("applinks:"):] for a in ulinks})

        except zipfile.BadZipFile:
            return meta

        return meta

    async def extract_manifest(self, ipa_path: Path) -> dict[str, str]:
        """Fast path for upload flow — bundle id + version. Mirrors APKToolEngine.

        Same return shape as APKToolEngine.extract_manifest so the upload
        endpoint can call either depending on file suffix.
        """
        meta = self.parse_ipa(ipa_path)
        if not meta.get("bundle_id"):
            return {}
        return {
            "package": meta["bundle_id"],
            "version_name": meta.get("version_name") or "unknown",
            "version_code": meta.get("version_code") or "",
            "min_sdk": meta.get("min_os") or "",
            "target_sdk": "",
        }


def attack_surface_from_ipa_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Translate parse_ipa() output into AttackSurface kwargs.

    Returns a partial dict the orchestrator can splat into AttackSurface(**kw).
    """
    natives = [
        NativeLibrary(
            path=n["path"],
            arch=n["arch"],
            size_bytes=int(n.get("size_bytes") or 0),
        )
        for n in meta.get("native_libraries", [])
    ]
    # Entitlements → list of strings, one per entitlement key. Some values are
    # lists themselves (associated domains, app groups); flatten to readable
    # `key=value` strings.
    ents_dict = meta.get("entitlements") or {}
    ent_lines: list[str] = []
    for k, v in ents_dict.items():
        if isinstance(v, list):
            ent_lines.append(f"{k} = [{', '.join(str(x) for x in v)}]")
        else:
            ent_lines.append(f"{k} = {v}")

    # Note: `api_endpoints`, `crypto_operations`, and SSL/jailbreak flags are
    # NOT set here — the orchestrator owns those, merging them across engines.
    return {
        "exported_components": [],   # iOS has no manifest components
        "deeplinks": list(meta.get("deeplinks") or []),
        "native_libraries": natives,
        "permissions": list(meta.get("permissions") or []),
        "sdk_fingerprint": dict(meta.get("sdk_fingerprint") or {}),
        "entitlements": ent_lines,
        "url_schemes": list(meta.get("url_schemes") or []),
        "app_transport_security": dict(meta.get("app_transport_security") or {}),
        "provisioning_profile": meta.get("provisioning_profile") or None,
    }


# ─── plist parsing ───────────────────────────────────────────────────────

def _read_plist(blob: bytes) -> dict[str, Any] | None:
    """Parse XML or binary plist via stdlib `plistlib`."""
    try:
        return plistlib.loads(blob)
    except Exception:  # noqa: BLE001
        return None


def _parse_provisioning(blob: bytes) -> dict[str, Any]:
    """Pull the embedded plist out of a CMS-signed `embedded.mobileprovision`.

    Real provisioning files are CMS-wrapped (PKCS#7) — the plist sits between
    `<?xml` and `</plist>`. We grep that out instead of pulling in
    `cryptography` for a one-line read.
    """
    start = blob.find(b"<?xml")
    end = blob.find(b"</plist>")
    if start == -1 or end == -1:
        return {}
    plist_blob = blob[start:end + len(b"</plist>")]
    data = _read_plist(plist_blob) or {}
    out: dict[str, Any] = {}
    out["app_id_name"] = data.get("AppIDName", "")
    out["team_id"] = (data.get("TeamIdentifier") or [""])[0] if isinstance(data.get("TeamIdentifier"), list) else (data.get("TeamIdentifier") or "")
    out["team_name"] = data.get("TeamName", "")
    out["created_at"] = str(data.get("CreationDate", "") or "")
    out["expires_at"] = str(data.get("ExpirationDate", "") or "")
    out["distribution_type"] = (
        "enterprise" if data.get("ProvisionsAllDevices") else
        "ad-hoc" if data.get("ProvisionedDevices") else
        "app-store" if data.get("ProvisionsAllDevices") is None and not data.get("Entitlements", {}).get("get-task-allow") else
        "development"
    )
    out["entitlements"] = data.get("Entitlements") or {}
    return out


# ─── Mach-O detection ────────────────────────────────────────────────────

def _detect_macho_arch(blob: bytes) -> str:
    if len(blob) < 8:
        return "unknown"
    head = blob[:4]
    if head not in _MACHO_MAGIC:
        return "unknown"
    if head in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        return "fat (universal)"
    # 64-bit big or little endian — magic last byte determines.
    if head in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
        # cputype is at offset 4 (4 bytes); 0x0100000C = ARM64
        cputype = struct.unpack("<I", blob[4:8])[0] if head[0] == 0xCF else struct.unpack(">I", blob[4:8])[0]
        if cputype & 0x01000000 and cputype & 0x0C:
            return "arm64"
        if cputype == 0x07:
            return "x86"
        if cputype & 0x01000000 and cputype & 0x07:
            return "x86_64"
        return f"unknown(0x{cputype:x})"
    return "32-bit"


# ─── Heuristic SDK fingerprints ──────────────────────────────────────────

_IOS_SDK_NAMES = {
    "Firebase": "Firebase",
    "FirebaseCore": "Firebase",
    "FirebaseAnalytics": "Firebase",
    "Crashlytics": "Crashlytics",
    "FirebaseCrashlytics": "Crashlytics",
    "Adjust": "Adjust",
    "AppsFlyerLib": "AppsFlyer",
    "Branch": "Branch",
    "FBSDKCoreKit": "Facebook SDK",
    "FBAEMKit": "Facebook SDK",
    "Sentry": "Sentry",
    "SentryPrivate": "Sentry",
    "Mixpanel": "Mixpanel",
    "Stripe": "Stripe",
    "StripePayments": "Stripe",
    "Realm": "Realm",
    "RealmSwift": "Realm",
    "Alamofire": "Alamofire",
    "OkHttp": "OkHttp",
    "GRDB": "GRDB",
}

_IOS_BINARY_SIGNATURES = [
    (b"NSURLSession",                 "NSURLSession"),
    (b"_CCCrypt",                     "CommonCrypto"),
    (b"kSecAttrAccessible",           "Keychain"),
    (b"WKWebView",                    "WKWebView"),
    (b"SFSafariViewController",       "SafariViewController"),
    (b"_NSLog",                       "NSLog"),
    (b"PT_DENY_ATTACH",               "anti-debug"),
    (b"frida-server",                 "frida-detection"),
]
