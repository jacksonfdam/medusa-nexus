"""APKTool engine — resource whisperer. Decodes manifest + resources.

Real APKs ship a binary-encoded AndroidManifest.xml (AXML). The `apktool`
CLI is the canonical decoder, but we also keep a *built-in* fallback so the
ingest pipeline produces useful data even on a fresh machine without apktool
installed. The fallback understands:

  - the APK as a zip (file listing, sizes)
  - plain XML manifests (test fixtures, debug builds with stripped binary AXML)
  - binary AXML manifests (real release APKs) — minimal parser at the bottom

It populates `context.extras["apk_meta"]` so the downstream engines can read
the parsed bits without re-opening the zip.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.attack_surface import ExportedComponent, NativeLibrary
from mnexus.models.finding import Finding, FindingCategory, Severity


_ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

# SDK signatures we recognize purely from package-prefix presence in the APK.
_SDK_SIGNATURES = [
    ("Firebase",       ("com/google/firebase/", "google-services")),
    ("Crashlytics",    ("com/google/firebase/crashlytics/", "io/fabric/sdk/")),
    ("OkHttp",         ("okhttp3/", "okhttp/")),
    ("Retrofit",       ("retrofit2/",)),
    ("Glide",          ("com/bumptech/glide/",)),
    ("Picasso",        ("com/squareup/picasso/",)),
    ("Adjust",         ("com/adjust/sdk/",)),
    ("AppsFlyer",      ("com/appsflyer/",)),
    ("Facebook SDK",   ("com/facebook/",)),
    ("Branch",         ("io/branch/",)),
    ("Gson",           ("com/google/gson/",)),
    ("Dagger",         ("dagger/",)),
    ("Kotlin",         ("kotlin/",)),
    ("RxJava",         ("io/reactivex/", "rx/")),
    ("Mixpanel",       ("com/mixpanel/",)),
    ("Stripe",         ("com/stripe/",)),
    ("Realm",          ("io/realm/",)),
    ("RootBeer",       ("com/scottyab/rootbeer/",)),
    ("SafetyNet",      ("com/google/android/gms/safetynet/",)),
    ("WebKit (WebView)",("android/webkit/",)),
]


class APKToolEngine(BaseEngine):
    """Wraps `apktool d` for manifest parsing + resource inspection.

    With a built-in zip + AXML fallback so the pipeline never returns empty
    when apktool isn't on the host PATH.
    """

    @property
    def name(self) -> str:
        return "apktool"

    @property
    def capabilities(self) -> list[str]:
        return ["decode", "manifest", "resources"]

    async def health_check(self) -> EngineStatus:
        path = shutil.which(self.config.apktool_path)
        if not path:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="apktool missing — using built-in zip+AXML fallback",
            )
        out = await self._run([path, "--version"])
        return EngineStatus(name=self.name, installed=True, version=out.strip() or "?", path=path, message="ready to decode")

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Parse the APK's manifest + zip listing, populate context.extras, emit findings."""
        meta = await self.parse_apk_with_fallback(context.apk_path)
        if context.extras is None:
            context.extras = {}
        context.extras["apk_meta"] = meta

        findings: list[Finding] = []

        # Risky declared flags.
        if meta.get("debuggable") == "true":
            findings.append(Finding(
                title="Application is debuggable in shipped manifest",
                description=("`android:debuggable=\"true\"` ships a release build that "
                             "any USB-connected attacker can attach to with `run-as` "
                             "and dump memory."),
                severity=Severity.HIGH,
                category=FindingCategory.CODE,
                source_engine=self.name,
                evidence='AndroidManifest.xml: <application android:debuggable="true">',
                location="AndroidManifest.xml",
                cwe_id="CWE-489",
                owasp_mobile="M10",
                masvs="MSTG-CODE-2",
                remediation=(
                    "Remove `android:debuggable` from the release manifest, or set it to false. "
                    "Trust the build type (release vs debug) — never override at the AndroidManifest level."
                ),
            ))
        if meta.get("allow_backup") == "true":
            findings.append(Finding(
                title="App allows ADB backup of its private data",
                description="`android:allowBackup=\"true\"` lets `adb backup` export the app's data dir.",
                severity=Severity.MEDIUM,
                category=FindingCategory.STORAGE,
                source_engine=self.name,
                evidence='AndroidManifest.xml: <application android:allowBackup="true">',
                location="AndroidManifest.xml",
                cwe_id="CWE-200",
                masvs="MSTG-STORAGE-8",
                remediation="Set android:allowBackup=\"false\" or, if backup is required, define a fullBackupContent rule that excludes secrets.",
            ))
        # Cleartext traffic — Android 9+ defaults to false, but apps can opt back in.
        if meta.get("uses_cleartext_traffic") == "true":
            findings.append(Finding(
                title="App permits cleartext HTTP",
                description="`android:usesCleartextTraffic=\"true\"` — TLS isn't enforced for outbound traffic.",
                severity=Severity.HIGH,
                category=FindingCategory.NETWORK,
                source_engine=self.name,
                evidence='AndroidManifest.xml: <application android:usesCleartextTraffic="true">',
                location="AndroidManifest.xml",
                cwe_id="CWE-319",
                masvs="MSTG-NETWORK-2",
                remediation=(
                    "Drop the attribute (default is false on API 28+) and audit any networkSecurityConfig "
                    "for `cleartextTrafficPermitted=\"true\"` overrides."
                ),
            ))

        # Exported components without permission.
        for comp in meta.get("exported_components", []):
            if comp.get("unprotected") and comp.get("type") != "activity":
                # Activities are commonly LAUNCHER-exported on purpose; flag only services/receivers/providers.
                findings.append(Finding(
                    title=f"Exported {comp['type']} without permission: {comp['name']}",
                    description=(
                        f"`<{comp['type']}>` is `android:exported=\"true\"` with no `android:permission` "
                        "guarding it. Any installed app can invoke it."
                    ),
                    severity=Severity.HIGH if comp["type"] == "provider" else Severity.MEDIUM,
                    category=FindingCategory.IPC,
                    source_engine=self.name,
                    evidence=f"<{comp['type']} android:name=\"{comp['name']}\" android:exported=\"true\">",
                    location="AndroidManifest.xml",
                    cwe_id="CWE-926",
                    masvs="MSTG-PLATFORM-4",
                    remediation=(
                        f"Add `android:permission=\"<your.signature.PERM>\"` to the `<{comp['type']}>`, or set "
                        "`android:exported=\"false\"` if the component is internal-only."
                    ),
                ))

        # Native libs in the APK.
        for lib in meta.get("native_libraries", []):
            if "x86" in lib["arch"] and lib["arch"] != "x86_64":
                # Just informational — most modern APKs drop x86.
                continue

        # Risky permissions — combos worth a note.
        perms = set(meta.get("permissions", []))
        bad_combos = [
            ({"android.permission.RECORD_AUDIO", "android.permission.INTERNET"},
             "Audio recording + internet — covert recording surface.", Severity.MEDIUM),
            ({"android.permission.READ_SMS", "android.permission.INTERNET"},
             "SMS read + internet — credential interception risk.", Severity.HIGH),
            ({"android.permission.WRITE_EXTERNAL_STORAGE"},
             "Legacy WRITE_EXTERNAL_STORAGE — scoped storage on Q+ may render this stale and dangerous.",
             Severity.LOW),
        ]
        for combo, msg, sev in bad_combos:
            if combo.issubset(perms):
                findings.append(Finding(
                    title=f"Sensitive permission set: {' + '.join(sorted(combo))}",
                    description=msg,
                    severity=sev,
                    category=FindingCategory.PRIVACY,
                    source_engine=self.name,
                    evidence="AndroidManifest.xml <uses-permission> declarations",
                    location="AndroidManifest.xml",
                    cwe_id="CWE-250",
                    remediation=(
                        "Audit at runtime — only request these permissions when the user invokes the relevant feature. "
                        "Document the use-case in the privacy policy. Scope storage permissions on Android Q+."
                    ) if sev in (Severity.CRITICAL, Severity.HIGH) else None,
                ))

        return findings

    # ─── public helpers ───────────────────────────────────────────────────

    def parse_apk(self, apk_path: Path) -> dict[str, Any]:
        """Open the APK, parse manifest + zip listing into structured metadata."""
        meta: dict[str, Any] = {
            "package": "", "version_name": "", "version_code": "",
            "min_sdk": "", "target_sdk": "",
            "debuggable": "", "allow_backup": "", "uses_cleartext_traffic": "",
            "permissions": [], "exported_components": [], "deeplinks": [],
            "native_libraries": [], "sdk_fingerprint": {},
            "dex_files": [], "all_files": [],
        }
        if not apk_path.exists():
            return meta
        try:
            with zipfile.ZipFile(apk_path) as zf:
                names = zf.namelist()
                meta["all_files"] = names
                meta["dex_files"] = [n for n in names if n.startswith("classes") and n.endswith(".dex")]

                # Native libs
                for n in names:
                    if not n.startswith("lib/") or not n.endswith(".so"):
                        continue
                    parts = n.split("/")
                    if len(parts) < 3:
                        continue
                    meta["native_libraries"].append({
                        "path": n,
                        "arch": parts[1],
                        "size_bytes": zf.getinfo(n).file_size,
                    })

                # Manifest
                manifest_blob = b""
                if "AndroidManifest.xml" in names:
                    manifest_blob = zf.read("AndroidManifest.xml")
                if manifest_blob:
                    parsed = _parse_manifest(manifest_blob)
                    meta.update(parsed)

                # SDK fingerprint — scan the file list for known package prefixes.
                # Real release APKs have classes inside .dex blobs; for those we'll
                # also scan the dex bytes for /com/google/firebase/ etc.
                fp: dict[str, str] = {}
                for sdk_name, prefixes in _SDK_SIGNATURES:
                    for prefix in prefixes:
                        if any(prefix in n for n in names):
                            fp[sdk_name] = "detected (zip listing)"
                            break
                if not fp and meta["dex_files"]:
                    # Light heuristic: peek into the first dex blob for the markers.
                    try:
                        dex_bytes = zf.read(meta["dex_files"][0])
                        for sdk_name, prefixes in _SDK_SIGNATURES:
                            for prefix in prefixes:
                                if prefix.encode("utf-8") in dex_bytes or prefix.replace("/", ".").encode("utf-8") in dex_bytes:
                                    fp[sdk_name] = "detected (dex strings)"
                                    break
                    except Exception:  # noqa: BLE001
                        pass
                meta["sdk_fingerprint"] = fp
        except zipfile.BadZipFile:
            return meta

        return meta

    async def extract_manifest(self, apk_path: Path) -> dict[str, str]:
        """Fast path for the upload flow — just package + version.

        Routes through :meth:`parse_apk_with_fallback` so callers
        benefit from the apktool-binary fallback transparently when
        the built-in AXML decoder hits an entry layout it doesn't
        cover (Android 14+ compact entries, custom obfuscation, …).
        """
        meta = await self.parse_apk_with_fallback(apk_path)
        if not meta.get("package"):
            return {}
        return {
            "package": meta.get("package", ""),
            "version_name": meta.get("version_name", "") or "unknown",
            "version_code": meta.get("version_code", "") or "",
            "min_sdk": meta.get("min_sdk", "") or "",
            "target_sdk": meta.get("target_sdk", "") or "",
        }

    async def parse_apk_with_fallback(self, apk_path: Path) -> dict[str, Any]:
        """``parse_apk`` + opt-in apktool-binary fallback.

        The built-in :meth:`parse_apk` is best-effort — its ``_decode_axml``
        covers the typical AXML layouts but loses on a long tail of
        modern apps (Android 14+ compact entries, obfuscated string
        pools, manifests stamped with custom plugin tags). When the
        built-in returns a meta with no ``package`` field AND the
        ``apktool`` binary is on PATH, we shell out to it to extract a
        plain-XML manifest and re-merge the recovered fields.

        Costs a few seconds per fallback (apktool's first-run JVM
        warm-up + resource decode) but only pays it when the cheap path
        actually failed. No-ops cleanly when apktool isn't installed —
        the analyst gets the same empty meta they'd have gotten before
        and the rest of the pipeline still runs.
        """
        meta = self.parse_apk(apk_path)
        if meta.get("package"):
            return meta
        apktool_bin = shutil.which(self.config.apktool_path)
        if not apktool_bin:
            return meta
        recovered = await self._apktool_extract_manifest(apktool_bin, apk_path)
        if not recovered:
            return meta
        # Fold the recovered structured fields into meta. Native libs +
        # zip listing came from parse_apk's zip walk and stay as is —
        # apktool doesn't touch them. Manifest-derived fields (package,
        # versions, sdk levels, components, deeplinks, permissions,
        # debuggable / allow_backup / cleartext flags) get refreshed.
        for key, value in recovered.items():
            if value:
                meta[key] = value
        meta["_manifest_source"] = "apktool-fallback"
        return meta

    async def _apktool_extract_manifest(
        self, apktool_bin: str, apk_path: Path
    ) -> dict[str, Any]:
        """Run ``apktool d -s -f -o <tmp> <apk>`` and re-parse the
        resulting plain-XML AndroidManifest. Returns ``{}`` on any
        failure (timeout, non-zero exit, no manifest emitted, parse
        failure)."""
        import tempfile

        with tempfile.TemporaryDirectory(prefix="mnexus-apktool-") as tmp:
            out_dir = Path(tmp) / "decoded"
            cmd = [
                apktool_bin, "d",
                "-s",            # skip sources (resources only — we just want the manifest)
                "-f",            # overwrite if out_dir already exists
                "-o", str(out_dir),
                str(apk_path),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError:
                return {}
            try:
                _stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=120.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {}
            if proc.returncode != 0:
                return {}
            manifest_path = out_dir / "AndroidManifest.xml"
            if not manifest_path.is_file():
                return {}
            try:
                blob = manifest_path.read_bytes()
            except OSError:
                return {}
            return _parse_manifest(blob)

    async def decode(self, apk_path: Path, output_dir: Path) -> Path:
        """Full apktool decode — only available when the binary is installed."""
        output_dir.mkdir(parents=True, exist_ok=True)
        if not shutil.which(self.config.apktool_path):
            raise RuntimeError("apktool binary not on PATH; only the built-in fallback is available")
        await self._run([self.config.apktool_path, "d", "-f", "-o", str(output_dir), str(apk_path)])
        return output_dir

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")


# ─── manifest parsing ────────────────────────────────────────────────────

def _parse_manifest(blob: bytes) -> dict[str, Any]:
    """Parse AndroidManifest.xml from raw bytes — plain XML or AXML.

    Returns the same shape regardless of input format. Empty fields on any
    parse failure (caller decides what to do).
    """
    text: str | None = None
    if blob.startswith(b"<?xml") or blob.lstrip().startswith(b"<"):
        try:
            text = blob.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = None
    elif blob[:4] == b"\x03\x00\x08\x00":
        # Binary AXML — convert to a synthetic XML string.
        try:
            text = _decode_axml(blob)
        except Exception:  # noqa: BLE001
            text = None

    if not text:
        return {}
    try:
        import xml.etree.ElementTree as ET
        # Some manifests have leading garbage; trim to first '<'.
        i = text.find("<")
        if i > 0:
            text = text[i:]
        root = ET.fromstring(text)
    except Exception:  # noqa: BLE001
        return {}

    out: dict[str, Any] = {
        "package": root.get("package") or "",
        "version_name": root.get(f"{_ANDROID_NS}versionName") or "",
        "version_code": root.get(f"{_ANDROID_NS}versionCode") or "",
    }

    uses_sdk = root.find("uses-sdk")
    if uses_sdk is not None:
        out["min_sdk"] = uses_sdk.get(f"{_ANDROID_NS}minSdkVersion") or ""
        out["target_sdk"] = uses_sdk.get(f"{_ANDROID_NS}targetSdkVersion") or ""

    out["permissions"] = [el.get(f"{_ANDROID_NS}name") for el in root.findall("uses-permission") if el.get(f"{_ANDROID_NS}name")]

    app = root.find("application")
    if app is not None:
        out["debuggable"] = app.get(f"{_ANDROID_NS}debuggable") or ""
        out["allow_backup"] = app.get(f"{_ANDROID_NS}allowBackup") or ""
        out["uses_cleartext_traffic"] = app.get(f"{_ANDROID_NS}usesCleartextTraffic") or ""

        components: list[dict[str, Any]] = []
        deeplinks: list[str] = []
        for tag in ("activity", "service", "receiver", "provider"):
            for el in app.findall(tag):
                name = el.get(f"{_ANDROID_NS}name") or ""
                exported = (el.get(f"{_ANDROID_NS}exported") or "").lower() == "true"
                permission = el.get(f"{_ANDROID_NS}permission") or ""
                filters = []
                # collect deep links from intent filters
                for itf in el.findall("intent-filter"):
                    actions = [a.get(f"{_ANDROID_NS}name", "") for a in itf.findall("action")]
                    categories = [c.get(f"{_ANDROID_NS}name", "") for c in itf.findall("category")]
                    schemes = []
                    for d in itf.findall("data"):
                        scheme = d.get(f"{_ANDROID_NS}scheme")
                        host = d.get(f"{_ANDROID_NS}host")
                        if scheme:
                            schemes.append(f"{scheme}://{host or '*'}")
                    filters.append({"actions": actions, "categories": categories, "schemes": schemes})
                    deeplinks.extend(schemes)
                # An <activity> with a deep-link filter is implicitly exported.
                effectively_exported = exported or any(f["schemes"] for f in filters)
                if effectively_exported:
                    components.append({
                        "name": name,
                        "type": tag,
                        "permission": permission or None,
                        "intent_filters": filters,
                        "unprotected": effectively_exported and not permission,
                    })
        out["exported_components"] = components
        out["deeplinks"] = sorted(set(d for d in deeplinks if d))

    return out


# ─── minimal binary AXML parser ────────────────────────────────────────
# Reference: android.googlesource.com/platform/frameworks/base — chunk-based
# format: header (8 bytes) + StringPool + ResourceMap (optional) + XML chunks.
# Spec is well-known; this implementation handles enough of it to extract
# package, versions, application flags, permissions, components, intent
# filters. Real apktool / aapt do more — we don't need that fidelity.

import struct


def _decode_axml(blob: bytes) -> str:
    """Convert binary AXML to plain XML text. Best-effort; raises on garbage."""
    if blob[0:4] != b"\x03\x00\x08\x00":
        raise ValueError("not AXML")
    # file header: type/u16, headerSize/u16, fileSize/u32
    file_size = struct.unpack_from("<I", blob, 4)[0]
    if file_size > len(blob):
        raise ValueError("truncated AXML")

    pos = 8
    strings: list[str] = []
    resource_ids: list[int] = []  # noqa: F841 - kept for completeness
    out: list[str] = []
    ns_map: dict[str, str] = {}

    while pos + 8 <= file_size:
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", blob, pos)
        if chunk_size <= 0 or pos + chunk_size > file_size:
            break
        end = pos + chunk_size

        if chunk_type == 0x0001:  # ResStringPool_type
            strings = _parse_string_pool(blob, pos)
        elif chunk_type == 0x0180:  # ResXMLTree_resourceMap_type
            count = (chunk_size - header_size) // 4
            resource_ids = list(struct.unpack_from(f"<{count}I", blob, pos + header_size))
        elif chunk_type == 0x0100:  # XML start namespace
            prefix_idx, uri_idx = struct.unpack_from("<II", blob, pos + 16)
            if 0 <= prefix_idx < len(strings) and 0 <= uri_idx < len(strings):
                ns_map[strings[uri_idx]] = strings[prefix_idx]
        elif chunk_type == 0x0101:  # XML end namespace
            pass
        elif chunk_type == 0x0102:  # XML start element
            ns_idx, name_idx = struct.unpack_from("<II", blob, pos + 16)
            attribute_start, attribute_size, attribute_count = struct.unpack_from("<HHH", blob, pos + 24)
            tag_ns = strings[ns_idx] if 0 <= ns_idx < len(strings) else ""
            tag = strings[name_idx] if 0 <= name_idx < len(strings) else "?"
            attrs: list[str] = []
            attr_pos = pos + 16 + attribute_start
            for _ in range(attribute_count):
                a_ns_idx, a_name_idx, a_raw_value, _typed_size, a_typed_type, a_typed_data = struct.unpack_from("<IIIHBxI", blob, attr_pos)
                attr_pos += attribute_size
                a_ns = strings[a_ns_idx] if 0 <= a_ns_idx < len(strings) else ""
                a_name = strings[a_name_idx] if 0 <= a_name_idx < len(strings) else "?"
                a_value = _typed_attr_string(strings, a_raw_value, a_typed_type, a_typed_data)
                prefix = ns_map.get(a_ns)
                qname = f"{prefix}:{a_name}" if prefix else a_name
                attrs.append(f'{qname}="{_xml_escape(a_value)}"')
            ns_decls = ""
            if not out:  # only emit namespace decls on the root
                for uri, prefix in ns_map.items():
                    ns_decls += f' xmlns:{prefix}="{uri}"'
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            out.append(f"<{tag}{ns_decls}{attr_str}>")
        elif chunk_type == 0x0103:  # XML end element
            ns_idx, name_idx = struct.unpack_from("<II", blob, pos + 16)
            tag = strings[name_idx] if 0 <= name_idx < len(strings) else "?"
            out.append(f"</{tag}>")
        elif chunk_type == 0x0104:  # XML CDATA
            pass

        pos = end

    return "".join(out)


def _parse_string_pool(blob: bytes, pos: int) -> list[str]:
    chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", blob, pos)  # noqa: F841
    string_count, _style_count, flags, strings_start, _styles_start = struct.unpack_from("<IIIII", blob, pos + 8)
    is_utf8 = bool(flags & 0x100)
    offsets = list(struct.unpack_from(f"<{string_count}I", blob, pos + header_size))
    base = pos + strings_start
    strings: list[str] = []
    for off in offsets:
        p = base + off
        if is_utf8:
            # u8 string: 1-2 byte length prefix (utf-16 chars), 1-2 byte length (utf-8 bytes), null-terminated
            _u16_len, p = _u8_len(blob, p)
            byte_len, p = _u8_len(blob, p)
            try:
                strings.append(blob[p:p + byte_len].decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                strings.append("")
        else:
            char_len, p = _u16_len(blob, p)
            strings.append(blob[p:p + char_len * 2].decode("utf-16-le", errors="replace"))
    return strings


def _u8_len(blob: bytes, p: int) -> tuple[int, int]:
    b = blob[p]
    if b & 0x80:
        return ((b & 0x7F) << 8) | blob[p + 1], p + 2
    return b, p + 1


def _u16_len(blob: bytes, p: int) -> tuple[int, int]:
    b0, b1 = blob[p], blob[p + 1]
    if b0 & 0x80:
        # 4-byte length
        b2, b3 = blob[p + 2], blob[p + 3]
        return (((b0 & 0x7F) << 8) | b1) << 16 | (b2 << 8) | b3, p + 4
    return (b0 << 8) | b1, p + 2


def _typed_attr_string(strings: list[str], raw_value: int, typed_type: int, typed_data: int) -> str:
    # 0x03 STRING — typed_data indexes into the string pool
    if typed_type == 0x03 and 0 <= typed_data < len(strings):
        return strings[typed_data]
    if 0 <= raw_value < len(strings) and strings[raw_value]:
        return strings[raw_value]
    if typed_type == 0x12:  # boolean
        return "true" if typed_data != 0 else "false"
    if typed_type == 0x10:  # int dec
        return str(typed_data if typed_data < 0x80000000 else typed_data - 0x100000000)
    if typed_type == 0x11:  # int hex
        return f"0x{typed_data:x}"
    return f"@{typed_type:#x}/{typed_data}"


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;"))


# ─── helpers used by orchestrator after fan-out ───────────────────────

def attack_surface_from_meta(meta: dict[str, Any]) -> tuple[list[ExportedComponent], list[NativeLibrary], list[str], list[str], dict[str, str]]:
    """Translate the dict produced by parse_apk() into model objects.

    Returns (exported_components, native_libraries, deeplinks, permissions, sdk_fp).
    """
    exported = [
        ExportedComponent(
            name=c["name"],
            component_type=c["type"],
            permission=c.get("permission"),
            intent_filters=c.get("intent_filters") or [],
            unprotected=bool(c.get("unprotected")),
        )
        for c in meta.get("exported_components", [])
    ]
    natives = [
        NativeLibrary(
            path=n["path"],
            arch=n["arch"],
            size_bytes=int(n.get("size_bytes") or 0),
        )
        for n in meta.get("native_libraries", [])
    ]
    return (
        exported,
        natives,
        list(meta.get("deeplinks") or []),
        list(meta.get("permissions") or []),
        dict(meta.get("sdk_fingerprint") or {}),
    )
