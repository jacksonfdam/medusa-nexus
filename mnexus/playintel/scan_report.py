"""Scan report — aggregate findings, configs, and saved-file blobs.

A scan emits four kinds of output:

1. :class:`SecretMatch` — credential hits (confirmed + suspected).
2. :class:`FirebaseConfig` — recovered project identifiers, ready for
   active probes.
3. ``vulnerabilities`` — string findings produced by the active probes
   (``"Realtime DB world-readable …"``).
4. ``saved_files`` — the raw bytes of any zip entry that contained a
   confirmed credential or a Firebase config, keyed by APK-relative
   path. The engine persists these to disk so analysts can re-inspect
   them without re-streaming the APK.

:class:`ScanZipResult` is the per-zip output (one APK can have splits +
additional files; each split scans into its own result, which is then
folded into a single :class:`ScanReport`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from mnexus.playintel.firebase_config import FirebaseConfig
from mnexus.playintel.secret_detector import SecretMatch


@dataclass(slots=True)
class ScanZipResult:
    """Output of scanning one zip archive (one APK split)."""

    techs: dict[str, str] = field(default_factory=dict)
    """Technology label → location of the file that proved it."""

    secrets: list[SecretMatch] = field(default_factory=list)
    firebase_configs: list[FirebaseConfig] = field(default_factory=list)
    saved_files: dict[str, bytes] = field(default_factory=dict)
    interesting_files: list[str] = field(default_factory=list)


class ScanReport:
    """Thread-safe aggregator. One per APK package, fed by N split scans."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.techs: dict[str, list[str]] = {}
        self.secrets: list[SecretMatch] = []
        self.firebase_configs: list[FirebaseConfig] = []
        self.vulnerabilities: list[str] = []
        self.saved_files: dict[str, bytes] = {}
        self.interesting_files: list[str] = []

    # ─── mutators ─────────────────────────────────────────────────────

    def add(self, result: ScanZipResult) -> None:
        """Fold one :class:`ScanZipResult` into this report."""
        with self._lock:
            for tech, loc in result.techs.items():
                self.techs.setdefault(tech, []).append(loc)
            self.secrets.extend(result.secrets)
            self.firebase_configs.extend(result.firebase_configs)
            self.interesting_files.extend(result.interesting_files)
            for path, content in result.saved_files.items():
                self.saved_files[path] = content

    def add_vulnerability(self, message: str) -> None:
        """Record a finding from an active probe."""
        with self._lock:
            self.vulnerabilities.append(message)

    def add_firebase_config(self, cfg: FirebaseConfig) -> None:
        with self._lock:
            self.firebase_configs.append(cfg)

    # ─── accessors ────────────────────────────────────────────────────

    def get_firebase_configs(self) -> list[FirebaseConfig]:
        with self._lock:
            return list(self.firebase_configs)

    def has_tech(self, tech: str) -> bool:
        with self._lock:
            return tech in self.techs

    def get_saved_files(self) -> dict[str, bytes]:
        with self._lock:
            return dict(self.saved_files)

    def confirmed_secrets(self) -> list[SecretMatch]:
        with self._lock:
            return [s for s in self.secrets if not s.suspected]

    def suspected_secrets(self) -> list[SecretMatch]:
        with self._lock:
            return [s for s in self.secrets if s.suspected]
