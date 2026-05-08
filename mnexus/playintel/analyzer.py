"""Analyzer — orchestrates one full APK reconnaissance run.

Pipeline:

1. Resolve a :class:`DownloadInfo` from the source (Play / local file /
   direct URL). Source is opaque to the analyzer.
2. For each download target (base APK + each split + any additional
   files), open a zip reader (:class:`LocalZip` or :class:`RemoteZip`),
   run :func:`scan_zip` over its whitelisted entries, and fold the
   per-target :class:`ScanZipResult` into a single :class:`ScanReport`.
3. For each unique :class:`FirebaseConfig` recovered, run the active
   probes (RTDB, Firestore, Cloud Storage). Add the outcomes to the
   report as ``vulnerabilities``.
4. Persist any ``saved_files`` into ``<workspace>/secrets/<package>/``
   so the analyst has the bearing blobs for offline review.

The analyzer is the right module to call from a CLI command, an HTTP
endpoint, or a test fixture. The :class:`mnexus.engines.PlayIntelEngine`
wrapper consumes its output and emits :class:`Finding` objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from mnexus.playintel.apk_source import APKSource, DownloadInfo
from mnexus.playintel.firebase_config import FirebaseConfig
from mnexus.playintel.firebase_probes import (
    FirestoreResult,
    RealtimeDBResult,
    StorageResult,
    check_firestore,
    check_realtime_db,
    check_storage_bucket,
)
from mnexus.playintel.scan_report import ScanReport
from mnexus.playintel.zip_entry_scanner import scan_zip

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AnalysisOutcome:
    """Top-level result of one APK analysis run."""

    package_name: str
    download_info: DownloadInfo
    report: ScanReport
    rtdb_results: list[RealtimeDBResult] = field(default_factory=list)
    firestore_results: list[FirestoreResult] = field(default_factory=list)
    storage_results: list[StorageResult] = field(default_factory=list)
    saved_files_dir: Path | None = None


def analyze_package(
    source: APKSource,
    package_name: str,
    *,
    workspace: Path,
    run_active_probes: bool = True,
) -> AnalysisOutcome:
    """End-to-end analysis of one Android package.

    ``workspace`` is the directory under which ``secrets/<package>/``
    is created when bearing files need to be persisted. Pass
    ``run_active_probes=False`` for a pure static-only scan (no
    outbound traffic to Firebase / GCP).
    """
    info = source.get_download_info(package_name)
    log.info(
        "playintel: analyzing %s (base=%dB, splits=%d, extras=%d)",
        package_name,
        info.base_size,
        len(info.splits),
        len(info.additional_files),
    )

    report = ScanReport()

    # Base APK.
    with source.open_base(info) as zr:
        report.add(scan_zip(zr, prefix="ROOT"))

    # Splits (config splits, language splits, ABI splits).
    for split in info.splits:
        try:
            with source.open_split(info, split) as zr:
                report.add(scan_zip(zr, prefix=split.name))
        except Exception as exc:  # noqa: BLE001 — best-effort per split
            log.warning("playintel: split %s failed: %s", split.name, exc)

    # Run active probes once per unique Firebase project ID.
    rtdb: list[RealtimeDBResult] = []
    firestore: list[FirestoreResult] = []
    storage: list[StorageResult] = []
    if run_active_probes:
        rtdb, firestore, storage = _run_active_probes(report)

    # Persist saved files.
    saved_dir: Path | None = None
    saved_files = report.get_saved_files()
    if saved_files:
        saved_dir = workspace / "secrets" / package_name
        saved_dir.mkdir(parents=True, exist_ok=True)
        for path, content in saved_files.items():
            safe_name = path.replace("/", "_")
            (saved_dir / safe_name).write_bytes(content)

    return AnalysisOutcome(
        package_name=package_name,
        download_info=info,
        report=report,
        rtdb_results=rtdb,
        firestore_results=firestore,
        storage_results=storage,
        saved_files_dir=saved_dir,
    )


def _run_active_probes(
    report: ScanReport,
) -> tuple[list[RealtimeDBResult], list[FirestoreResult], list[StorageResult]]:
    """Probe RTDB / Firestore / Storage for each unique Firebase config.

    De-duplicates by project ID before probing so we don't hit the
    same project N times when an APK ships the same config in multiple
    locations (resources.arsc + google-services.json + flavour-specific
    XML).
    """
    seen: set[str] = set()
    rtdb_results: list[RealtimeDBResult] = []
    firestore_results: list[FirestoreResult] = []
    storage_results: list[StorageResult] = []

    for cfg in report.get_firebase_configs():
        if not cfg.project_id or cfg.project_id in seen:
            continue
        seen.add(cfg.project_id)

        for db_url in cfg.realtime_db_candidates:
            r = check_realtime_db(db_url)
            rtdb_results.append(r)
            if r.vulnerable:
                report.add_vulnerability(
                    f"Realtime Database public access: {db_url} "
                    f"(read={r.public_read}, write={r.public_write})"
                )
                # Stop probing alternates once we have a hit.
                break

        fs = check_firestore(cfg.project_id, api_key=cfg.api_key)
        firestore_results.append(fs)
        if fs.vulnerable:
            report.add_vulnerability(
                f"Firestore world-readable: project={cfg.project_id} "
                f"(collections={fs.sample_document_count})"
            )

        if cfg.storage_bucket:
            st = check_storage_bucket(cfg.storage_bucket)
            storage_results.append(st)
            if st.vulnerable:
                report.add_vulnerability(
                    f"Cloud Storage bucket world-listable: {cfg.storage_bucket} "
                    f"(objects={st.object_count})"
                )

    return rtdb_results, firestore_results, storage_results


def unique_firebase_configs(report: ScanReport) -> list[FirebaseConfig]:
    """De-duplicate Firebase configs by project ID, keeping the
    first-seen instance. Used by the engine when emitting findings.
    """
    seen: set[str] = set()
    unique: list[FirebaseConfig] = []
    for cfg in report.get_firebase_configs():
        if not cfg.project_id or cfg.project_id in seen:
            continue
        seen.add(cfg.project_id)
        unique.append(cfg)
    return unique
