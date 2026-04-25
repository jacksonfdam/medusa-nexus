"""JADX engine — the only decompiler that doesn't apologize.

Real JADX (Skylot) decompiles the APK to Java source. Out-of-the-box we don't
have it — but we can still derive useful findings by scanning DEX byte strings
for the same signals JADX-based detection would surface: hardcoded crypto
keys, weak crypto constants, WebView misuse patterns.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import zipfile
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.attack_surface import CryptoOperation
from mnexus.models.finding import Finding, FindingCategory, Severity


# Patterns we can recognize from raw DEX byte content. DEX is essentially a
# packed format, but string constants survive intact and are scannable.
_PATTERNS = {
    "weak_cipher_ecb":   re.compile(rb"AES/ECB/(?:NoPadding|PKCS5Padding)"),
    "weak_cipher_cbc":   re.compile(rb"AES/CBC/(?:NoPadding|PKCS5Padding)"),
    "des":               re.compile(rb"\bDES(?:ede)?(?:/[A-Za-z]+)*\b"),
    "md5":               re.compile(rb"\bMD5\b"),
    "sha1":              re.compile(rb"\bSHA-?1\b"),
    "static_iv":         re.compile(rb"new IvParameterSpec\(new byte\[16\]\)"),
    "javascript_iface":  re.compile(rb"addJavascriptInterface"),
    "set_js_enabled":    re.compile(rb"setJavaScriptEnabled"),
    "set_allow_files":   re.compile(rb"setAllowFileAccess(?:FromFileURLs)?"),
    "rawquery":          re.compile(rb"\.rawQuery\("),
    "system_print":      re.compile(rb"Log\.[deiwv]\("),
    # Hardcoded secret heuristics — generic shape, manual review needed.
    "google_api_key":    re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),
    "aws_access_key":    re.compile(rb"AKIA[0-9A-Z]{16}"),
    "jwt_token":         re.compile(rb"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+"),
    "private_key_pem":   re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "secretkeyspec":     re.compile(rb"SecretKeySpec"),
    "trustmanager":      re.compile(rb"X509TrustManager"),
    "okhttp_pinner":     re.compile(rb"CertificatePinner"),
    "rootbeer":          re.compile(rb"com/scottyab/rootbeer/RootBeer"),
}


class JADXEngine(BaseEngine):
    """Static analysis over decompiled (or raw DEX) bytes."""

    @property
    def name(self) -> str:
        return "jadx"

    @property
    def capabilities(self) -> list[str]:
        return ["decompile", "search", "xref"]

    async def health_check(self) -> EngineStatus:
        path = shutil.which(self.config.jadx_path)
        if not path:
            return EngineStatus(
                name=self.name,
                installed=False,
                version=None,
                path=None,
                message="jadx missing — using DEX-string scanner fallback",
            )
        out = await self._run([path, "--version"])
        return EngineStatus(name=self.name, installed=True, version=out.strip() or "?", path=path, message="ready to decompile")

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Scan DEX bytes for classic Java-side smells."""
        findings: list[Finding] = []
        crypto_ops: list[CryptoOperation] = []
        ssl_pinning_detected = False
        ssl_pinning_library: str | None = None
        root_detection_detected = False
        root_detection_library: str | None = None

        try:
            with zipfile.ZipFile(context.apk_path) as zf:
                dex_blobs = [zf.read(n) for n in zf.namelist() if n.startswith("classes") and n.endswith(".dex")]
        except Exception:  # noqa: BLE001
            dex_blobs = []

        for blob in dex_blobs:
            for key, pat in _PATTERNS.items():
                hits = pat.findall(blob)
                if not hits:
                    continue
                if key == "weak_cipher_ecb":
                    findings.append(_finding(
                        title="AES/ECB cipher mode in use",
                        desc="ECB leaks plaintext patterns. Identical blocks → identical ciphertext.",
                        sev=Severity.HIGH, cat=FindingCategory.CRYPTO, src=self.name,
                        evidence=hits[0].decode("ascii", errors="replace"), loc="classes.dex (DEX strings)",
                        cwe="CWE-327", masvs="MSTG-CRYPTO-3",
                        rem=("Switch to AES/GCM or AES/CBC with random IV per message + HMAC. "
                             "Use Android Keystore for the key."),
                    ))
                    crypto_ops.append(CryptoOperation(location="classes.dex", algorithm=hits[0].decode("ascii", errors="replace"), key_source="unknown"))
                elif key == "weak_cipher_cbc":
                    crypto_ops.append(CryptoOperation(location="classes.dex", algorithm=hits[0].decode("ascii", errors="replace"), key_source="unknown", iv_source=None))
                elif key == "des":
                    findings.append(_finding(
                        title="Legacy DES/3DES algorithm referenced",
                        desc="DES is broken; 3DES is deprecated. Either should be removed.",
                        sev=Severity.HIGH, cat=FindingCategory.CRYPTO, src=self.name,
                        evidence=hits[0].decode("ascii", errors="replace"), loc="classes.dex",
                        cwe="CWE-326", masvs="MSTG-CRYPTO-4",
                        rem="Replace with AES/GCM. There is no production reason to ship DES on Android in 2026.",
                    ))
                elif key == "md5":
                    findings.append(_finding(
                        title="MD5 hashing referenced",
                        desc="MD5 has been broken for decades — collision attacks exist.",
                        sev=Severity.MEDIUM, cat=FindingCategory.CRYPTO, src=self.name,
                        evidence="MD5", loc="classes.dex", cwe="CWE-327", masvs="MSTG-CRYPTO-4",
                        rem="Use SHA-256 or stronger. For passwords, use bcrypt/scrypt/Argon2.",
                    ))
                elif key == "sha1":
                    findings.append(_finding(
                        title="SHA-1 hashing referenced",
                        desc="SHA-1 collisions are practical (SHAttered).",
                        sev=Severity.LOW, cat=FindingCategory.CRYPTO, src=self.name,
                        evidence="SHA-1", loc="classes.dex", cwe="CWE-327",
                    ))
                elif key == "static_iv":
                    findings.append(_finding(
                        title="Static (zero) IV with AES",
                        desc="`new IvParameterSpec(new byte[16])` is a 16-byte zero IV. Catastrophic for AES/CBC.",
                        sev=Severity.CRITICAL, cat=FindingCategory.CRYPTO, src=self.name,
                        evidence="new IvParameterSpec(new byte[16])", loc="classes.dex",
                        cwe="CWE-329", masvs="MSTG-CRYPTO-3",
                        rem=("Generate a fresh random IV per message via `SecureRandom`. "
                             "Prepend the IV to ciphertext when transmitting. Switch to AES/GCM for AEAD."),
                    ))
                elif key == "javascript_iface":
                    findings.append(_finding(
                        title="WebView.addJavascriptInterface() detected",
                        desc=("`addJavascriptInterface()` exposes a Java object to JS. Without `@JavascriptInterface` "
                              "annotations and a hardened method allowlist, attacker JS can call arbitrary public methods."),
                        sev=Severity.HIGH, cat=FindingCategory.WEBVIEW, src=self.name,
                        evidence="addJavascriptInterface", loc="classes.dex",
                        cwe="CWE-79", masvs="MSTG-PLATFORM-7",
                        rem=("Restrict the bridge to vetted methods marked `@JavascriptInterface`. Validate every "
                             "argument. Don't load untrusted URLs in the same WebView."),
                    ))
                elif key == "set_js_enabled":
                    # Soft signal — common but pair it with addJavascriptInterface for the real risk.
                    pass
                elif key == "rawquery":
                    findings.append(_finding(
                        title="SQLite rawQuery() — possible SQL injection surface",
                        desc="`rawQuery()` with concatenated arguments is the canonical SQLi pattern.",
                        sev=Severity.MEDIUM, cat=FindingCategory.STORAGE, src=self.name,
                        evidence=".rawQuery(", loc="classes.dex",
                        cwe="CWE-89",
                        rem="Switch to parameterized queries via `query()` with `selectionArgs`.",
                    ))
                elif key == "google_api_key":
                    findings.append(_finding(
                        title="Hardcoded Google API key shipped in APK",
                        desc=f"Detected `{hits[0].decode('ascii')[:20]}…` in DEX strings.",
                        sev=Severity.HIGH, cat=FindingCategory.STORAGE, src=self.name,
                        evidence=hits[0].decode("ascii", errors="replace"), loc="classes.dex",
                        cwe="CWE-798",
                        rem=("Restrict the key by package + SHA-1 in the Google Cloud console. Rotate it. "
                             "Move secret-bearing keys to a backend you own."),
                    ))
                elif key == "aws_access_key":
                    findings.append(_finding(
                        title="Hardcoded AWS access key",
                        desc=f"Detected `{hits[0].decode('ascii')}` in DEX strings.",
                        sev=Severity.CRITICAL, cat=FindingCategory.STORAGE, src=self.name,
                        evidence=hits[0].decode("ascii", errors="replace"), loc="classes.dex",
                        cwe="CWE-798",
                        rem=("Rotate immediately via IAM. Replace with Cognito Identity Pools or STS — never ship "
                             "long-lived AWS credentials in a mobile binary."),
                    ))
                elif key == "private_key_pem":
                    findings.append(_finding(
                        title="PEM-formatted private key bundled in APK",
                        desc="A `-----BEGIN ... PRIVATE KEY-----` block is present in DEX bytes.",
                        sev=Severity.CRITICAL, cat=FindingCategory.CRYPTO, src=self.name,
                        evidence="-----BEGIN [...]PRIVATE KEY-----", loc="classes.dex",
                        cwe="CWE-798",
                        rem=("Move private keys to Android Keystore (StrongBox where available). The current key is "
                             "compromised the moment any user installs the APK — rotate."),
                    ))
                elif key == "okhttp_pinner":
                    ssl_pinning_detected = True
                    ssl_pinning_library = "okhttp"
                elif key == "trustmanager":
                    if not ssl_pinning_detected:
                        ssl_pinning_detected = True
                        ssl_pinning_library = "trustmanager"
                elif key == "rootbeer":
                    root_detection_detected = True
                    root_detection_library = "rootbeer"
                elif key == "secretkeyspec":
                    crypto_ops.append(CryptoOperation(location="classes.dex", algorithm="AES (SecretKeySpec)", key_source="unknown"))

        # Stash extras for the orchestrator to fold into AttackSurface.
        if context.extras is None:
            context.extras = {}
        context.extras.setdefault("static", {})
        context.extras["static"]["jadx"] = {
            "crypto_operations": crypto_ops,
            "ssl_pinning_detected": ssl_pinning_detected,
            "ssl_pinning_library": ssl_pinning_library,
            "root_detection_detected": root_detection_detected,
            "root_detection_library": root_detection_library,
        }
        return findings

    async def decompile(self, apk_path: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not shutil.which(self.config.jadx_path):
            raise RuntimeError("jadx not on PATH; the built-in DEX scanner does not produce source")
        await self._run(
            [self.config.jadx_path, "--deobf", "--show-bad-code", "--output-dir",
             str(output_dir), str(apk_path)]
        )
        return output_dir

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")


def _finding(*, title: str, desc: str, sev: Severity, cat: FindingCategory,
             src: str, evidence: str, loc: str | None = None, cwe: str | None = None,
             owasp: str | None = None, masvs: str | None = None, rem: str | None = None) -> Finding:
    """Helper — builds a Finding with the required defaults baked in."""
    if sev in (Severity.CRITICAL, Severity.HIGH) and not rem:
        rem = "See OWASP MASTG section for this control. Apply the recommended platform mitigation."
    return Finding(
        title=title, description=desc, severity=sev, category=cat,
        source_engine=src, evidence=evidence, location=loc,
        cwe_id=cwe, owasp_mobile=owasp, masvs=masvs, remediation=rem,
    )
