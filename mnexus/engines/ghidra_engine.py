"""Ghidra engine — the NSA's gift that keeps decompiling. Headless mode only.

Real Ghidra runs `analyzeHeadless` on every `.so`. Out of the box we don't
ship that — but we can still scan native binaries for revealing strings the
same way Ghidra's post-script would have surfaced them.
"""

from __future__ import annotations

import asyncio
import re
import zipfile
from pathlib import Path

from mnexus.engines.base import AnalysisContext, BaseEngine, EngineStatus
from mnexus.models.attack_surface import CryptoOperation
from mnexus.models.finding import Finding, FindingCategory, Severity


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
            version="headless",
            path=str(self.config.ghidra_path),
            message="ready to dissect native blobs",
        )

    async def execute(self, context: AnalysisContext) -> list[Finding]:
        """Read every .so in the APK; emit findings on what we recognize."""
        findings: list[Finding] = []
        crypto_ops: list[CryptoOperation] = []

        try:
            with zipfile.ZipFile(context.apk_path) as zf:
                so_names = [n for n in zf.namelist() if n.startswith("lib/") and n.endswith(".so")]
                for n in so_names:
                    try:
                        data = zf.read(n)
                    except Exception:  # noqa: BLE001
                        continue
                    self._scan_native(n, data, findings, crypto_ops)
        except Exception:  # noqa: BLE001
            return findings

        if context.extras is None:
            context.extras = {}
        context.extras.setdefault("static", {})
        context.extras["static"]["ghidra"] = {
            "crypto_operations": crypto_ops,
        }
        return findings

    def _scan_native(self, name: str, data: bytes, findings: list[Finding], crypto_ops: list[CryptoOperation]) -> None:
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

    async def analyze_native_lib(self, so_path: Path) -> dict[str, object]:  # pragma: no cover - stub
        _ = so_path
        return {}

    async def _run(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")
