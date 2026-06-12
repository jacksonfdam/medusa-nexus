"""Ghidra engine — the NSA's gift that keeps decompiling. Headless mode only.

Real Ghidra runs `analyzeHeadless` on every `.so` (Android) and Mach-O
binary (iOS). Out of the box we don't ship Ghidra — but we can still scan
native binaries for revealing strings the same way Ghidra's post-script
would have surfaced them, on **both platforms**.

Format autodetection: ELF (`\\x7fELF`) → Android-flavoured patterns,
Mach-O magic (FE ED FA CE/CF or CA FE BA BE) → iOS-flavoured patterns.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import cast

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.attack_surface import CryptoOperation
from mnexus.models.finding import Finding, FindingCategory, Severity

# Bundled Ghidra headless post-script (Jython). Copied into the workspace at
# run time so it's reachable both for a local Ghidra and the containerised one.
_GHIDRA_POSTSCRIPT = Path(__file__).parent / "ghidra_scripts" / "nexus_dump.py"

# Patterns shared by both formats — compiled cryptography libs reuse the same
# C symbol names whether the host is Android NDK or iOS.
_NATIVE_PATTERNS = {
    "openssl":    re.compile(rb"OpenSSL [0-9]"),
    "boringssl":  re.compile(rb"BoringSSL"),
    "libsodium":  re.compile(rb"libsodium"),
    "aes":        re.compile(rb"\bAES_[a-z]+\b"),
    "rsa":        re.compile(rb"\bRSA_[a-z]+\b"),
    "ptrace":     re.compile(rb"\bptrace\b"),
    "antiframe":  re.compile(rb"frida|gadget|gum-js"),
    "magisk":     re.compile(rb"magisk|supersu"),
    "rootcheck":  re.compile(rb"/system/xbin/su|/sbin/magisk"),
}

# iOS-specific binary signals — only meaningful in Mach-O context.
_IOS_NATIVE_PATTERNS = {
    "common_crypto":     re.compile(rb"_CCCrypt|_CCDigest|_CCHmac"),
    "kSecAttrAccess":    re.compile(rb"kSecAttrAccessible(?:When|After|Always)\w*"),
    "url_session":       re.compile(rb"NSURLSession(?:Configuration)?"),
    "set_pinning_flags": re.compile(rb"SSLContextSetSessionOption|SSLSetTrustedRoots"),
    "wkwebview":         re.compile(rb"WKWebView|WKWebsiteDataStore"),
    "nslog_secret":      re.compile(rb"NSLog.*?(password|token|secret|api[_-]?key)", re.IGNORECASE),
    "pt_deny_attach":    re.compile(rb"PT_DENY_ATTACH"),
    "jb_paths":          re.compile(rb"/Applications/Cydia\.app|/var/lib/cydia|/private/var/lib/apt"),
    "jb_classes":        re.compile(rb"IOSSecuritySuite|tsProtector|JailProtect"),
    "fork_check":        re.compile(rb"_fork|sysctl"),
}


_MACHO_MAGIC = (
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
)


def _binary_format(blob: bytes) -> str:
    """Return 'elf', 'macho', or 'unknown'."""
    if not blob:
        return "unknown"
    if blob[:4] == b"\x7fELF":
        return "elf"
    if blob[:4] in _MACHO_MAGIC:
        return "macho"
    return "unknown"


class GhidraEngine(BaseEngine):
    """Drives `analyzeHeadless` against every `.so` shipped in the APK.

    With a built-in string-scanner fallback when Ghidra isn't installed.
    """

    @property
    def name(self) -> str:
        return "ghidra"

    @property
    def capabilities(self) -> list[str]:
        return ["disassemble", "decompile_native", "find_jni", "analyze_crypto"]

    async def health_check(self) -> EngineStatus:
        if not self.config.ghidra_path or not self.config.ghidra_path.exists():
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="ghidra missing — using ELF string scanner fallback",
            )
        headless = self.config.ghidra_path / "support" / "analyzeHeadless"
        if not headless.exists():
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=str(self.config.ghidra_path),
                message="analyzeHeadless not found under support/. Broken install?",
            )
        return EngineStatus(
            name=self.name,
            installed=True,
            version=self._ghidra_version(),
            path=str(self.config.ghidra_path),
            message="ready to dissect native blobs",
        )

    def _ghidra_version(self) -> str:
        """Best-effort real version from `application.properties`.

        Falls back to ``"headless"`` when unreadable — e.g. the containerised
        shim, where the actual install lives inside Docker, not on this path.
        """
        if not self.config.ghidra_path:
            return "headless"
        props = self.config.ghidra_path / "Ghidra" / "application.properties"
        try:
            for line in props.read_text(encoding="utf-8").splitlines():
                if line.startswith("application.version="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
        return "headless"

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Read every native binary in the APK or IPA; emit findings.

        APKs ship `.so` ELF blobs under `lib/<abi>/`. IPAs ship the main
        Mach-O binary at `Payload/<App>.app/<CFBundleExecutable>` plus any
        `Payload/<App>.app/Frameworks/*.framework/<Name>` mach-o blobs. We
        autodetect format from magic bytes — no extension reliance.
        """
        findings: list[Finding] = []
        crypto_ops: list[CryptoOperation] = []
        jb_detected = False
        jb_library: str | None = None

        try:
            with zipfile.ZipFile(context.apk_path) as zf:
                # Pull candidate paths from both layouts.
                candidates = [
                    n for n in zf.namelist()
                    if (n.startswith("lib/") and n.endswith(".so"))
                    or (n.startswith("Payload/") and (n.endswith(".framework/") or "/Frameworks/" in n or _looks_like_main_macho(n)))
                ]
                # Mach-O binaries don't always have an extension — open and sniff.
                for n in candidates:
                    if n.endswith("/"):
                        continue
                    try:
                        data = zf.read(n)
                    except Exception:  # noqa: BLE001
                        continue
                    fmt = _binary_format(data)
                    if fmt == "elf":
                        self._scan_elf(n, data, findings, crypto_ops)
                    elif fmt == "macho":
                        result = self._scan_macho(n, data, findings, crypto_ops)
                        if result.get("jb_detected"):
                            jb_detected = True
                            jb_library = jb_library or cast("str | None", result.get("jb_library"))
                    # else: not a native binary, skip silently.
        except Exception:  # noqa: BLE001
            return findings

        if context.extras is None:
            context.extras = {}
        context.extras.setdefault("static", {})
        context.extras["static"]["ghidra"] = {
            "crypto_operations": crypto_ops,
            "jailbreak_detection_detected": jb_detected,
            "jailbreak_detection_library": jb_library,
        }

        # Collapse duplicate findings: when the same pattern hits across N
        # native libs (very common for `ptrace`, `frida`, etc.) we get N
        # separate Findings with near-identical title/description. Group by
        # (severity, category, normalised-title) and merge their location
        # + evidence into one entry per signal.
        return _collapse_native_duplicates(findings)

    def _scan_elf(self, name: str, data: bytes, findings: list[Finding], crypto_ops: list[CryptoOperation]) -> None:
        """Android-flavoured native scan — ELF .so file."""
        for key, pat in _NATIVE_PATTERNS.items():
            if not pat.search(data):
                continue
            if key in ("aes", "rsa"):
                crypto_ops.append(CryptoOperation(
                    location=name, algorithm=("AES" if key == "aes" else "RSA"),
                    key_source="unknown",
                ))
            elif key == "antiframe":
                findings.append(Finding(
                    title=f"Anti-Frida tripwire in {Path(name).name}",
                    description=("The native lib references `frida`/`gadget` strings — likely an anti-instrumentation "
                                 "check that compares running process names or scans /proc."),
                    severity=Severity.MEDIUM,
                    category=FindingCategory.OBFUSCATION,
                    source_engine=self.name,
                    evidence="frida|gadget|gum-js",
                    location=name,
                    cwe_id="CWE-693",
                    masvs="MSTG-RESILIENCE-4",
                    remediation="Document the check in your threat model. Frida users will bypass it; rely on layered defenses (root attestation + server-side validation).",
                ))
            elif key == "rootcheck":
                findings.append(Finding(
                    title=f"Root-detection paths in {Path(name).name}",
                    description="Native code looks for `/system/xbin/su` or magisk paths — typical RootBeer-style check moved into native.",
                    severity=Severity.LOW,
                    category=FindingCategory.OBFUSCATION,
                    source_engine=self.name,
                    evidence="/system/xbin/su, /sbin/magisk",
                    location=name,
                    masvs="MSTG-RESILIENCE-1",
                ))
            elif key == "ptrace":
                findings.append(Finding(
                    title=f"`ptrace` reference in {Path(name).name}",
                    description="Anti-debug ptrace self-attach pattern observed.",
                    severity=Severity.LOW,
                    category=FindingCategory.OBFUSCATION,
                    source_engine=self.name,
                    evidence="ptrace",
                    location=name,
                    masvs="MSTG-RESILIENCE-2",
                ))

    def _scan_macho(self, name: str, data: bytes, findings: list[Finding], crypto_ops: list[CryptoOperation]) -> dict[str, object]:
        """iOS-flavoured native scan — Mach-O main binary or framework."""
        out: dict[str, object] = {"jb_detected": False, "jb_library": None}
        # Shared signals first (crypto libs / anti-frida).
        for key, pat in _NATIVE_PATTERNS.items():
            if not pat.search(data):
                continue
            if key in ("aes", "rsa"):
                crypto_ops.append(CryptoOperation(
                    location=name, algorithm=("AES" if key == "aes" else "RSA"),
                    key_source="unknown",
                ))
            elif key == "antiframe":
                findings.append(Finding(
                    title=f"Anti-Frida tripwire in {Path(name).name}",
                    description="The Mach-O image references `frida`/`gadget` strings — likely a runtime check.",
                    severity=Severity.MEDIUM,
                    category=FindingCategory.OBFUSCATION,
                    source_engine=self.name,
                    evidence="frida|gadget|gum-js",
                    location=name,
                    cwe_id="CWE-693",
                    masvs="MSTG-RESILIENCE-4",
                    platform_hint="ios",
                    remediation="Frida users will bypass it. Layered defenses (server-side attestation) buy you more.",
                ))

        # iOS-specific signals.
        for key, pat in _IOS_NATIVE_PATTERNS.items():
            if not pat.search(data):
                continue
            if key == "common_crypto":
                crypto_ops.append(CryptoOperation(location=name, algorithm="CommonCrypto", key_source="unknown"))
            elif key == "kSecAttrAccess":
                # Find the specific accessibility constant referenced.
                m = pat.search(data)
                token = m.group(0).decode("utf-8", errors="replace") if m else ""
                if "Always" in token:
                    findings.append(Finding(
                        title=f"Keychain accessibility set to {token}",
                        description=("`kSecAttrAccessibleAlways[ThisDeviceOnly]` keeps secrets readable when the "
                                     "device is locked — and on older iOS, even after a passcode wipe."),
                        severity=Severity.MEDIUM,
                        category=FindingCategory.STORAGE,
                        source_engine=self.name,
                        evidence=token,
                        location=name,
                        cwe_id="CWE-312",
                        masvs="MSTG-STORAGE-2",
                        platform_hint="ios",
                        remediation="Switch to `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` (or stricter — `…AfterFirstUnlock` only when running in the background).",
                    ))
            elif key == "nslog_secret":
                findings.append(Finding(
                    title=f"`NSLog` references potential secret in {Path(name).name}",
                    description="A format string near `NSLog` mentions password/token/secret/api_key — likely live logging of credentials.",
                    severity=Severity.HIGH,
                    category=FindingCategory.PRIVACY,
                    source_engine=self.name,
                    evidence="NSLog(...secret|token|password|api_key...)",
                    location=name,
                    cwe_id="CWE-532",
                    masvs="MSTG-STORAGE-3",
                    platform_hint="ios",
                    remediation="Strip every NSLog of sensitive values from release builds. Wrap with `#if DEBUG`. Audit os_log too — `OS_LOG_TYPE_DEFAULT` strings are still device-readable.",
                ))
            elif key == "pt_deny_attach":
                findings.append(Finding(
                    title="`PT_DENY_ATTACH` anti-debug present",
                    description="Calls `ptrace(PT_DENY_ATTACH)` to refuse debugger attachments. Bypassed easily with a Frida hook on `ptrace`.",
                    severity=Severity.LOW,
                    category=FindingCategory.OBFUSCATION,
                    source_engine=self.name,
                    evidence="PT_DENY_ATTACH",
                    location=name,
                    masvs="MSTG-RESILIENCE-2",
                    platform_hint="ios",
                ))
            elif key == "jb_paths":
                out["jb_detected"] = True
                out["jb_library"] = "custom"
            elif key == "jb_classes":
                out["jb_detected"] = True
                # Pick the first matching class as the library hint.
                m = pat.search(data)
                if m:
                    out["jb_library"] = m.group(0).decode("utf-8", errors="replace").lower()
            elif key == "set_pinning_flags":
                findings.append(Finding(
                    title=f"Custom SSL pinning callbacks in {Path(name).name}",
                    description="`SSLContextSetSessionOption`/`SSLSetTrustedRoots` indicate hand-rolled certificate pinning.",
                    severity=Severity.INFO,
                    category=FindingCategory.NETWORK,
                    source_engine=self.name,
                    evidence="SSLContextSetSessionOption | SSLSetTrustedRoots",
                    location=name,
                    masvs="MSTG-NETWORK-4",
                    platform_hint="ios",
                ))

        if out["jb_detected"]:
            findings.append(Finding(
                title=f"Jailbreak-detection markers in {Path(name).name}",
                description=(f"Library: {out['jb_library'] or 'custom'}. The binary references typical "
                             "jailbreak file paths or detection class names."),
                severity=Severity.LOW,
                category=FindingCategory.OBFUSCATION,
                source_engine=self.name,
                evidence=str(out["jb_library"] or "/Applications/Cydia.app, …"),
                location=name,
                masvs="MSTG-RESILIENCE-1",
                platform_hint="ios",
            ))
        return out

    async def analyze_native_lib(self, so_path: Path) -> dict[str, object]:
        """Scan one native binary (ELF or Mach-O) and return findings + symbols.

        Used by ``/v1/projects/{id}/native/analyze`` — the analyst picks a
        specific .so / framework from the Native tab and gets a detailed
        per-binary view. Goes deeper than the ingest fan-out:

          * Pattern matches against ``_NATIVE_PATTERNS`` (ELF) and
            ``_IOS_NATIVE_PATTERNS`` (Mach-O). Same rules as ``execute()``
            but emits findings inline.
          * JNI export detection — ELF dynamic symbol strings starting
            with ``Java_`` reveal which Java classes the lib bridges,
            i.e. the exact attack surface for a Frida ``-l`` script.
          * Hardcoded URL/secret strings — ``http(s)://…`` + ``AIza[A-Za-z0-9_-]{30,}``.

        Returns ``{"format": "elf"|"macho", "size": N, "findings": [...],
        "jni_exports": [...], "hardcoded_urls": [...], "hardcoded_keys": [...]}``.

        Always returns a dict; ``{"error": "..."}`` for unreadable files
        instead of raising — the API layer wraps that into a clean 404.
        """
        if not so_path.exists():
            return {"error": f"file not found: {so_path}"}
        try:
            data = so_path.read_bytes()
        except OSError as exc:
            return {"error": f"read failed: {exc}"}
        if not data:
            return {"error": "empty file"}

        fmt = _binary_format(data)
        findings: list[Finding] = []
        crypto_ops: list[CryptoOperation] = []
        name = so_path.name

        if fmt == "elf":
            self._scan_elf(name, data, findings, crypto_ops)
        elif fmt == "macho":
            self._scan_macho(name, data, findings, crypto_ops)
        else:
            return {"error": f"unknown binary format (first 4 bytes: {data[:4]!r})"}

        # JNI exports — only meaningful for ELF (Android JNI).
        jni_exports: list[str] = []
        if fmt == "elf":
            jni_exports = _extract_jni_exports(data)

        result: dict[str, object] = {
            "format": fmt,
            "name": name,
            "size": len(data),
            "findings": [f.model_dump(mode="json") for f in findings],
            "jni_exports": jni_exports,
            "hardcoded_urls": _extract_hardcoded_urls(data),
            "hardcoded_keys": _extract_aiza_keys(data),
            "crypto_operations": [c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c.__dict__) for c in crypto_ops],
            "engine_mode": "scanner",
        }

        # ── Additive deepening with real Ghidra headless, when available. ──
        # Symbol-table truth beats regex byte-matching. This NEVER regresses:
        # if Ghidra is absent or the run fails, `_run_headless` returns {} and
        # the byte-scan result above stands on its own. Slow (full auto-analysis
        # per binary) — which is why it lives here, in the on-demand per-binary
        # view, not in the ingest fan-out (`execute`).
        deep = await self._run_headless(so_path)
        if deep:
            funcs = cast("list[str]", deep.get("functions") or [])
            imports = cast("list[str]", deep.get("imports") or [])
            strings = cast("list[str]", deep.get("strings") or [])
            jni = cast("list[str]", deep.get("jni_exports") or [])
            result["engine_mode"] = "headless"
            result["ghidra"] = {
                "language": deep.get("language"),
                "function_count": len(funcs),
                "functions": funcs[:500],
                "imports": imports,
                "strings": strings[:200],
            }
            # Ghidra's symbol-derived JNI exports supersede the regex guess.
            if jni:
                result["jni_exports"] = sorted(set(jni))[:200]

        return result

    async def _run_headless(self, target: Path) -> dict[str, object]:
        """Run real Ghidra `analyzeHeadless` on one native binary; return its dump.

        Best-effort and side-effect-free on failure — returns ``{}`` on any
        problem so the caller keeps its byte-scan findings. Works identically
        against a local install and the containerised Ghidra: every path passed
        lives under ``config.workspace`` (the compose bind-mount), so the
        ``ghidra-docker`` shim's host→/workspace translation covers them all.
        """
        ghidra = self.config.ghidra_path
        if not ghidra or not (ghidra / "support" / "analyzeHeadless").exists():
            return {}

        ws = self.config.workspace
        scripts_dir = ws / ".ghidra" / "scripts"
        proj_dir = ws / ".ghidra" / "proj"
        out_dir = ws / ".ghidra" / "out"
        try:
            for d in (scripts_dir, proj_dir, out_dir):
                d.mkdir(parents=True, exist_ok=True)
            # Ship the post-script into the workspace so the container sees it.
            shutil.copy2(_GHIDRA_POSTSCRIPT, scripts_dir / _GHIDRA_POSTSCRIPT.name)
        except OSError:
            return {}

        token = f"{target.stem}-{abs(hash(str(target))) & 0xFFFFFF:06x}"
        out_json = out_dir / f"{token}.json"
        out_json.unlink(missing_ok=True)

        cmd = [
            str(ghidra / "support" / "analyzeHeadless"),
            str(proj_dir), f"nexus_{token}",
            "-import", str(target),
            "-scriptPath", str(scripts_dir),
            "-postScript", _GHIDRA_POSTSCRIPT.name, str(out_json),
            "-deleteProject", "-overwrite",
        ]
        try:
            await self._run(cmd)
            if not out_json.exists():
                return {}
            parsed = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return {}
        finally:
            out_json.unlink(missing_ok=True)

        return {str(k): v for k, v in parsed.items()} if isinstance(parsed, dict) else {}

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")


# Patterns used by analyze_native_lib's standalone API. Kept here (not
# at module top) because they're a closed set used only by the
# per-binary scanner — no need to expose to other modules.
_JNI_EXPORT_PATTERN = re.compile(rb"Java_[A-Za-z0-9_$]{4,}")
_HTTP_URL_PATTERN = re.compile(rb"https?://[A-Za-z0-9._~:/?#@!$&\'()*+,;=%-]{6,200}")
_AIZA_KEY_PATTERN = re.compile(rb"AIza[0-9A-Za-z_-]{30,}")


def _extract_jni_exports(data: bytes) -> list[str]:
    """Strings starting with ``Java_<class>_<method>`` from an ELF binary.

    JNI exports are mangled per the Java ↔ C calling convention:
    package separators are ``_``, ``_1`` etc. Decoding them back to
    the Java name would be nice-to-have but the raw string is enough
    to feed a Frida ``Interceptor.attach`` script.
    """
    matches = {m.group(0).decode("utf-8", errors="replace") for m in _JNI_EXPORT_PATTERN.finditer(data)}
    return sorted(matches)[:200]  # cap so a 50MB blob doesn't explode the response


def _extract_hardcoded_urls(data: bytes) -> list[str]:
    """``http(s)://…`` strings in the binary. Useful for surface discovery."""
    out: set[str] = set()
    for m in _HTTP_URL_PATTERN.finditer(data):
        # Trim trailing punctuation that's clearly outside the URL.
        url = m.group(0).rstrip(b"\\'\"; .,)").decode("utf-8", errors="replace")
        out.add(url)
    return sorted(out)[:100]


def _extract_aiza_keys(data: bytes) -> list[str]:
    """Google-API-key-shaped strings. Easy to false-positive; we still
    surface them — every match is worth a manual look."""
    out: set[str] = set()
    for m in _AIZA_KEY_PATTERN.finditer(data):
        out.add(m.group(0).decode("utf-8", errors="replace"))
    return sorted(out)[:50]


def _looks_like_main_macho(name: str) -> bool:
    """Path heuristic: Payload/X.app/X (no extension, executable) or framework binary."""
    if not name.startswith("Payload/"):
        return False
    parts = name.split("/")
    # Payload/Foo.app/Foo  — main binary
    if len(parts) == 3 and parts[1].endswith(".app") and not parts[2].endswith((".plist", ".png", ".jpg", ".car", ".nib", ".strings", ".storyboardc")):
        return True
    # Payload/Foo.app/Frameworks/Bar.framework/Bar
    return (
        "/Frameworks/" in name
        and len(parts) >= 5
        and parts[-1].split(".")[-1] not in ("plist", "nib", "strings")
    )


def _collapse_native_duplicates(findings: list[Finding]) -> list[Finding]:
    """Group findings by (severity, category, normalised-title-prefix) and merge.

    The same pattern (anti-Frida, ptrace, root paths, …) often hits in every
    .so / framework. Without this, a single APK can ship 8 nearly-identical
    "Anti-Frida tripwire in liba.so / libb.so / …" rows. We collapse those
    into one Finding whose location is the comma-joined list of files.
    """
    grouped: dict[tuple[Severity, FindingCategory, str], Finding] = {}
    extras: dict[tuple[Severity, FindingCategory, str], list[str]] = {}

    for f in findings:
        # Normalise: drop trailing "in <filename>" so libraries with the
        # same signal collapse into one bucket.
        title_key = f.title.split(" in ")[0].strip().lower()
        key = (f.severity, f.category, title_key)
        first = grouped.get(key)
        if first is None:
            grouped[key] = f
            extras[key] = [f.location] if f.location else []
            continue
        if f.location and f.location not in extras[key]:
            extras[key].append(f.location)

    # Apply the merged location string. Pydantic models are immutable by
    # default — copy with model_copy.
    out: list[Finding] = []
    for key, f in grouped.items():
        locs = extras[key]
        if len(locs) <= 1:
            out.append(f)
            continue
        merged_location = f"{locs[0]} (+ {len(locs) - 1} more)"
        evidence = f.evidence + " · also: " + ", ".join(Path(loc).name for loc in locs[1:])
        out.append(f.model_copy(update={
            "location": merged_location,
            "evidence": evidence[:500],  # cap for sanity
            "title": f.title.split(" in ")[0] + f" — across {len(locs)} native binaries",
        }))
    return out
