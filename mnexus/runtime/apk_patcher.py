"""APK patcher — apktool + apksigner + zipalign wrapped for the Network/Runtime UX.

The original product plan called this the "Stheno wrapper" — but Stheno
(ch0pin/Stheno) is actually a runtime intent monitor, not a patcher.
What we actually need is what every Android pen-tester reaches for first:
disassemble → flip a manifest flag → reassemble → sign. apktool +
apksigner do the work; this module is the orchestration so the UI can
expose it as one button.

Supported patches:

  * ``debuggable``         Flip ``android:debuggable`` to true on the
                           ``<application>`` element. Enables jdb attach
                           + a bunch of crash-helper logging.
  * ``cleartext_traffic``  Flip ``android:usesCleartextTraffic`` to true.
                           Useful for HTTP-only test endpoints.
  * ``user_ca_trust``      Inject ``res/xml/network_security_config.xml``
                           with ``<trust-anchors><certificates src="user"/>``
                           and point the manifest at it. Lets the app
                           accept user-installed CAs again (the Android 7+
                           default broke that). Pinning still bites.

Each patch is idempotent — re-running over an already-patched APK is a
no-op for that patch.

Tool detection is runtime, not import-time: if ``apktool`` or
``apksigner`` aren't on PATH, the patcher operates in *preview* mode —
it shows the analyst what would change without producing an APK.
``setup.sh`` lists what's missing; the API surfaces it as a warning.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from mnexus.config import NexusConfig

log = logging.getLogger(__name__)

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ET.register_namespace("android", ANDROID_NS)


SUPPORTED_PATCHES = ("debuggable", "cleartext_traffic", "user_ca_trust")


# A permissive network security config — trusts user CAs + system CAs
# at the same time. We don't override the default for individual
# domains; analysts can add per-domain pinning manually later.
_NSC_XML = """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
        </trust-anchors>
    </base-config>
</network-security-config>
"""


@dataclass
class PatchResult:
    """What ``APKPatcher.patch`` returns — preview or real."""
    apk_path: Path
    patched_path: Path | None
    patches_applied: list[str] = field(default_factory=list)
    patches_skipped: list[tuple[str, str]] = field(default_factory=list)  # (name, why)
    warnings: list[str] = field(default_factory=list)
    preview: bool = False
    keystore_path: Path | None = None

    def model_dump(self) -> dict:
        """JSON-safe view for the API response."""
        return {
            "apk_path":         str(self.apk_path),
            "patched_path":     str(self.patched_path) if self.patched_path else None,
            "patches_applied":  list(self.patches_applied),
            "patches_skipped":  [{"name": n, "reason": r} for n, r in self.patches_skipped],
            "warnings":         list(self.warnings),
            "preview":          self.preview,
            "keystore_path":    str(self.keystore_path) if self.keystore_path else None,
        }


class APKPatcherError(RuntimeError):
    """Raised when a patch can't be applied for a non-environmental reason
    (e.g. apktool decode succeeded but the manifest XML is malformed)."""


class APKPatcher:
    """Stateless orchestrator — instantiated per request."""

    def __init__(self, config: NexusConfig) -> None:
        self.config = config

    # ─── public API ──────────────────────────────────────────────────

    async def patch(
        self,
        apk_path: Path,
        patches: Iterable[str],
        *,
        out_dir: Path | None = None,
    ) -> PatchResult:
        """Apply ``patches`` to ``apk_path`` and return the patched APK.

        Tool detection happens first — if ``apktool`` is missing we
        return a preview-only result with the patches the analyst
        wanted listed under ``patches_applied`` so the UI can show
        'this is what the patch would do'.
        """
        patches = list(patches)
        unknown = [p for p in patches if p not in SUPPORTED_PATCHES]
        if unknown:
            raise APKPatcherError(f"unknown patches: {unknown!r} — supported: {SUPPORTED_PATCHES}")
        if not patches:
            raise APKPatcherError("at least one patch is required")
        if not apk_path.exists():
            raise APKPatcherError(f"apk does not exist: {apk_path}")

        apktool = shutil.which(self.config.apktool_path) or shutil.which("apktool")
        if apktool is None:
            return PatchResult(
                apk_path=apk_path,
                patched_path=None,
                patches_applied=list(patches),
                warnings=[
                    "apktool is not on PATH — patcher running in preview mode.",
                    "Install via `brew install apktool` (macOS) or `apt-get install apktool` (Linux).",
                ],
                preview=True,
            )

        out_dir = out_dir or self.config.workspace / "patched"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Work inside a temp directory so a half-finished patch doesn't
        # leave debris around. Move the result into ``out_dir`` once
        # we're done.
        with tempfile.TemporaryDirectory(prefix="mnexus-patch-") as tmp:
            work = Path(tmp)
            decoded = work / "decoded"
            await self._apktool_decode(apktool, apk_path, decoded)

            applied: list[str] = []
            skipped: list[tuple[str, str]] = []
            for name in patches:
                ok, reason = self._apply_patch(name, decoded)
                if ok:
                    applied.append(name)
                else:
                    skipped.append((name, reason))

            if not applied:
                return PatchResult(
                    apk_path=apk_path,
                    patched_path=None,
                    patches_applied=[],
                    patches_skipped=skipped,
                    warnings=["no patches applied — see patches_skipped for reasons"],
                )

            unsigned = work / "patched-unsigned.apk"
            await self._apktool_rebuild(apktool, decoded, unsigned)

            # Sign + align if the build-tools are around. Otherwise return
            # the unsigned APK with a clear warning.
            patched = out_dir / f"{apk_path.stem}-patched.apk"
            warnings: list[str] = []
            keystore = self._ensure_debug_keystore()
            signed = await self._sign_or_warn(unsigned, patched, keystore, warnings)
            if not signed:
                shutil.copy(unsigned, patched)

        return PatchResult(
            apk_path=apk_path,
            patched_path=patched,
            patches_applied=applied,
            patches_skipped=skipped,
            warnings=warnings,
            keystore_path=keystore if signed else None,
        )

    # ─── internals ───────────────────────────────────────────────────

    async def _apktool_decode(self, apktool: str, apk: Path, out: Path) -> None:
        rc = await self._run_subprocess([apktool, "d", "-f", "-o", str(out), str(apk)])
        if rc != 0:
            raise APKPatcherError(f"apktool decode failed for {apk.name}")

    async def _apktool_rebuild(self, apktool: str, decoded: Path, out: Path) -> None:
        rc = await self._run_subprocess([apktool, "b", "-o", str(out), str(decoded)])
        if rc != 0:
            raise APKPatcherError("apktool rebuild failed — see logs above")

    def _apply_patch(self, name: str, decoded: Path) -> tuple[bool, str]:
        """Dispatch one patch. Returns (ok, reason-if-skipped)."""
        manifest = decoded / "AndroidManifest.xml"
        if not manifest.exists():
            return False, "decoded tree has no AndroidManifest.xml — apktool output is corrupt"
        if name == "debuggable":
            return self._patch_flag(manifest, "debuggable", "true")
        if name == "cleartext_traffic":
            return self._patch_flag(manifest, "usesCleartextTraffic", "true")
        if name == "user_ca_trust":
            return self._patch_user_ca_trust(manifest, decoded)
        return False, "unknown patch (dispatch error)"

    def _patch_flag(self, manifest: Path, attr: str, value: str) -> tuple[bool, str]:
        """Set ``android:<attr>="<value>"`` on ``<application>``."""
        try:
            tree = ET.parse(manifest)
        except ET.ParseError as exc:
            return False, f"AndroidManifest.xml parse failed: {exc}"
        root = tree.getroot()
        app = root.find("application")
        if app is None:
            return False, "no <application> element in manifest"
        attr_full = f"{{{ANDROID_NS}}}{attr}"
        if app.get(attr_full) == value:
            return True, "already set — no-op"
        app.set(attr_full, value)
        tree.write(manifest, encoding="utf-8", xml_declaration=True)
        return True, ""

    def _patch_user_ca_trust(self, manifest: Path, decoded: Path) -> tuple[bool, str]:
        """Drop an NSC xml + point ``android:networkSecurityConfig`` at it."""
        xml_dir = decoded / "res" / "xml"
        xml_dir.mkdir(parents=True, exist_ok=True)
        nsc_path = xml_dir / "network_security_config.xml"
        nsc_path.write_text(_NSC_XML)

        try:
            tree = ET.parse(manifest)
        except ET.ParseError as exc:
            return False, f"AndroidManifest.xml parse failed: {exc}"
        root = tree.getroot()
        app = root.find("application")
        if app is None:
            return False, "no <application> element in manifest"
        attr_full = f"{{{ANDROID_NS}}}networkSecurityConfig"
        already = app.get(attr_full)
        if already == "@xml/network_security_config":
            return True, "already pointing at @xml/network_security_config — no-op"
        app.set(attr_full, "@xml/network_security_config")
        tree.write(manifest, encoding="utf-8", xml_declaration=True)
        return True, ""

    def _ensure_debug_keystore(self) -> Path:
        """Get-or-create the per-user debug keystore.

        Sits at ``~/.mnexus/tools/patcher/debug.keystore``. Generated on
        first call via ``keytool``; subsequent runs reuse it so patched
        APKs upgrade in place across runs (same package + same signing
        cert = no UNINSTALL_FAILED_REPLACE_COULDNT_DELETE).
        """
        ks_path = Path(self.config.workspace).parent / "tools" / "patcher" / "debug.keystore"
        ks_path.parent.mkdir(parents=True, exist_ok=True)
        if ks_path.exists():
            return ks_path
        keytool = shutil.which("keytool")
        if keytool is None:
            return ks_path  # caller will note 'no keytool' in warnings
        # Quiet, non-interactive keystore generation.
        cmd = [
            keytool, "-genkey", "-v",
            "-keystore", str(ks_path),
            "-storepass", "android",
            "-keypass", "android",
            "-alias", "mnexus-patcher",
            "-keyalg", "RSA",
            "-keysize", "2048",
            "-validity", "10000",
            "-dname", "CN=MedusaNexus Patcher, OU=Research, O=mnexus, L=Stockholm, S=SE, C=SE",
        ]
        subprocess.run(cmd, check=False, capture_output=True)
        return ks_path

    async def _sign_or_warn(
        self,
        unsigned: Path,
        signed_out: Path,
        keystore: Path,
        warnings: list[str],
    ) -> bool:
        """Best-effort sign. Returns True if the signed APK is at ``signed_out``."""
        if not keystore.exists():
            warnings.append("debug keystore missing — install JDK so `keytool` is available.")
            return False

        apksigner = shutil.which("apksigner")
        zipalign = shutil.which("zipalign")
        aligned = unsigned

        if zipalign is not None:
            aligned = unsigned.with_suffix(".aligned.apk")
            rc = await self._run_subprocess([zipalign, "-p", "4", str(unsigned), str(aligned)])
            if rc != 0:
                warnings.append("zipalign returned non-zero — falling back to unaligned APK.")
                aligned = unsigned
        else:
            warnings.append(
                "zipalign not on PATH — APK ships unaligned. "
                "Some devices reject this; install Android build-tools."
            )

        if apksigner is not None:
            rc = await self._run_subprocess([
                apksigner, "sign",
                "--ks", str(keystore),
                "--ks-pass", "pass:android",
                "--key-pass", "pass:android",
                "--out", str(signed_out),
                str(aligned),
            ])
            if rc == 0:
                return True
            warnings.append("apksigner returned non-zero — APK may be unsigned.")
            return False

        # Fallback: jarsigner (legacy v1 only — Android 11+ rejects this).
        jarsigner = shutil.which("jarsigner")
        if jarsigner is None:
            warnings.append(
                "apksigner AND jarsigner both missing — install Android build-tools "
                "for `apksigner`. The unsigned APK is at the returned path."
            )
            return False
        shutil.copy(aligned, signed_out)
        rc = await self._run_subprocess([
            jarsigner, "-keystore", str(keystore),
            "-storepass", "android", "-keypass", "android",
            str(signed_out), "mnexus-patcher",
        ])
        if rc != 0:
            warnings.append("jarsigner returned non-zero — APK may be unsigned.")
            return False
        warnings.append(
            "Signed with jarsigner (v1 only). Android 11+ will reject. "
            "Install apksigner for v2/v3 signatures."
        )
        return True

    async def _run_subprocess(self, cmd: list[str]) -> int:
        """Run a CLI command, capture output, return exit code."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.warning(
                "patcher subprocess failed: %s\nstdout: %s\nstderr: %s",
                " ".join(cmd), stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        return proc.returncode or 0
