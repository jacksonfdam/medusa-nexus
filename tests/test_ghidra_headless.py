"""GhidraEngine analyzeHeadless deepening — the `_run` wiring.

We can't run a real Ghidra here, so we mock `_run` to play the role of the
`nexus_dump.py` post-script: it parses the analyzeHeadless argv, finds the
output path, and writes the JSON a real headless run would have produced.

What this pins down (the host-side logic, end to end):
  * deepening merges the dump into the result (engine_mode → "headless")
  * Ghidra's symbol-table JNI exports SUPERSEDE the regex byte-scan guess
  * any failure (no ghidra_path, _run raises, no output file) falls back to
    the byte-scanner with ZERO regression
  * health_check reports the real version from application.properties
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from mnexus.config import NexusConfig
from mnexus.engines.ghidra_engine import GhidraEngine


def _stub_elf(payload: bytes) -> bytes:
    """64-bit ELF header (only the 4 magic bytes are sniffed) + payload."""
    return b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 9 + b"\x00" * 48 + payload


def _fake_install(root: Path) -> Path:
    """Minimal fake Ghidra install: just enough for the existence gate."""
    headless = root / "support" / "analyzeHeadless"
    headless.parent.mkdir(parents=True, exist_ok=True)
    headless.write_text("#!/bin/sh\n")
    headless.chmod(0o755)
    return root


def _out_path_from_cmd(cmd: list[str]) -> Path:
    """analyzeHeadless argv: ... -postScript nexus_dump.py <OUT.json> ..."""
    i = cmd.index("nexus_dump.py")
    return Path(cmd[i + 1])


@pytest.fixture
def engine(tmp_path: Path) -> GhidraEngine:
    cfg = NexusConfig(
        ghidra_path=_fake_install(tmp_path / "ghidra"),
        workspace=tmp_path / "workspace",
    )
    return GhidraEngine(cfg)


async def test_headless_merges_and_supersedes_jni(
    engine: GhidraEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The byte payload carries a DIFFERENT Java_ export than the dump, so a
    # passing assertion proves Ghidra's symbols won — not the regex.
    elf = tmp_path / "libcrypto.so"
    elf.write_bytes(_stub_elf(b"\x00Java_regex_only_Probe\x00"))

    dump = {
        "language": "AARCH64:LE:64:v8A",
        "functions": ["sub_1000", "Java_com_target_Crypto_encrypt", "ptrace_stub"],
        "jni_exports": ["Java_com_target_Crypto_encrypt"],
        "imports": ["dlopen", "ptrace", "CCCrypt"],
        "strings": ["api.target.com", "secret_token"],
    }

    async def fake_run(self: GhidraEngine, cmd: list[str]) -> str:
        _out_path_from_cmd(cmd).write_text(json.dumps(dump))
        return "nexus_dump: ok"

    monkeypatch.setattr(GhidraEngine, "_run", fake_run)

    result = await engine.analyze_native_lib(elf)

    assert result["engine_mode"] == "headless"
    jni = cast("list[str]", result["jni_exports"])
    assert jni == ["Java_com_target_Crypto_encrypt"]  # superseded the regex guess
    assert "Java_regex_only_Probe" not in jni
    ghidra = cast("dict[str, object]", result["ghidra"])
    assert ghidra["language"] == "AARCH64:LE:64:v8A"
    assert ghidra["function_count"] == 3
    assert "dlopen" in cast("list[str]", ghidra["imports"])
    assert "api.target.com" in cast("list[str]", ghidra["strings"])


async def test_headless_failure_falls_back_to_scanner(
    engine: GhidraEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elf = tmp_path / "lib.so"
    elf.write_bytes(_stub_elf(b"\x00Java_com_target_Foo_bar\x00"))

    async def boom(self: GhidraEngine, cmd: list[str]) -> str:
        raise OSError("analyzeHeadless exploded")

    monkeypatch.setattr(GhidraEngine, "_run", boom)

    result = await engine.analyze_native_lib(elf)

    # No regression: byte-scan still answers, with its regex-derived export.
    assert result["engine_mode"] == "scanner"
    assert "ghidra" not in result
    assert "Java_com_target_Foo_bar" in cast("list[str]", result["jni_exports"])


async def test_no_ghidra_path_stays_scanner(tmp_path: Path) -> None:
    cfg = NexusConfig(workspace=tmp_path / "workspace")  # ghidra_path unset
    eng = GhidraEngine(cfg)
    elf = tmp_path / "lib.so"
    elf.write_bytes(_stub_elf(b"\x00Java_a_b_c\x00"))

    result = await eng.analyze_native_lib(elf)

    assert result["engine_mode"] == "scanner"
    assert "ghidra" not in result


async def test_health_check_reports_real_version(tmp_path: Path) -> None:
    root = _fake_install(tmp_path / "ghidra")
    props = root / "Ghidra" / "application.properties"
    props.parent.mkdir(parents=True, exist_ok=True)
    props.write_text("application.name=Ghidra\napplication.version=11.1.2\n")

    eng = GhidraEngine(NexusConfig(ghidra_path=root, workspace=tmp_path / "ws"))
    status = await eng.health_check()

    assert status.installed is True
    assert status.version == "11.1.2"
