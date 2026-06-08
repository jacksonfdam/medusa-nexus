"""GhidraEngine.analyze_native_lib + /v1/projects/{id}/native/analyze.

We craft tiny ELF files (the 32-bit ELF header + a payload section
containing patterns) so the test exercises the scanner without
shipping a real .so fixture in the repo.

Coverage:
  * analyze_native_lib emits findings for ELF + the new JNI / URL /
    AIza-key extractors
  * unknown binary format → {"error": …}, no crash
  * missing file → {"error": …}, no exception
  * Endpoint /native/analyze pulls a binary out of the project's
    APK + 404s when the lib name doesn't exist in the zip
"""

from __future__ import annotations

import asyncio
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from mnexus.config import NexusConfig
from mnexus.engines.ghidra_engine import (
    GhidraEngine,
    _extract_aiza_keys,
    _extract_hardcoded_urls,
    _extract_jni_exports,
)


def _stub_elf(payload: bytes) -> bytes:
    """Tiny ELF header + payload — enough for _binary_format to detect
    the format and for the pattern scanners to find strings."""
    # 16-byte e_ident: magic + class(2=64) + data(1=LE) + version(1) + pad
    e_ident = b"\x7fELF" + b"\x02\x01\x01" + b"\x00" * 9
    # Then 48 bytes of zeroed header fields — sufficient for our scanner
    # which only sniffs the leading 4 magic bytes.
    header_tail = b"\x00" * 48
    return e_ident + header_tail + payload


# ─── helper unit tests ────────────────────────────────────────────────


def test_extract_jni_exports_finds_mangled_symbols() -> None:
    data = b"\x00Java_com_target_app_Crypto_encrypt\x00noise\x00Java_x_y_Z\x00"
    out = _extract_jni_exports(data)
    assert "Java_com_target_app_Crypto_encrypt" in out
    assert "Java_x_y_Z" in out


def test_extract_jni_exports_caps_at_200() -> None:
    """Pathological case — million Java_ patterns. Returned list stays bounded."""
    data = b"\x00".join(f"Java_a_b_c{i}".encode() for i in range(500))
    out = _extract_jni_exports(data)
    assert len(out) <= 200


def test_extract_hardcoded_urls_strips_trailing_punctuation() -> None:
    data = b'string before "https://api.example.com/v1/me"; trailing'
    out = _extract_hardcoded_urls(data)
    assert "https://api.example.com/v1/me" in out


def test_extract_hardcoded_urls_handles_both_schemes() -> None:
    data = b"prefix http://insecure.example.com/x and https://secure.example.com/y suffix"
    out = _extract_hardcoded_urls(data)
    assert "http://insecure.example.com/x" in out
    assert "https://secure.example.com/y" in out


def test_extract_aiza_keys_finds_keys_and_caps() -> None:
    key1 = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    key2 = "AIza" + ("9" * 35)
    data = (key1 + " random " + key2).encode()
    out = _extract_aiza_keys(data)
    assert key1 in out
    assert key2 in out


# ─── analyze_native_lib direct ───────────────────────────────────────


@pytest.fixture
def ghidra(tmp_path) -> GhidraEngine:
    cfg = NexusConfig(workspace=tmp_path / "workspace")
    return GhidraEngine(cfg)


def test_analyze_native_lib_on_elf_extracts_jni_and_findings(ghidra, tmp_path) -> None:
    payload = b"".join([
        b"\x00Java_com_target_Crypto_encrypt\x00",
        b"frida-gum-js-loop",        # triggers antiframe pattern → HIGH finding
        b"\x00https://api.target.com/v1/login\x00",
        b"\x00AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi\x00",
        b"\x00",
    ])
    elf = tmp_path / "libcrypto.so"
    elf.write_bytes(_stub_elf(payload))

    result = asyncio.new_event_loop().run_until_complete(ghidra.analyze_native_lib(elf))
    assert result["format"] == "elf"
    assert "Java_com_target_Crypto_encrypt" in result["jni_exports"]
    assert "https://api.target.com/v1/login" in result["hardcoded_urls"]
    assert any("AIzaSy" in k for k in result["hardcoded_keys"])
    # The antiframe pattern in _scan_elf raises a HIGH finding.
    titles = " ".join(f["title"] for f in result["findings"])
    assert "Anti-Frida" in titles or "frida" in titles.lower()


def test_analyze_native_lib_unknown_format_returns_error(ghidra, tmp_path) -> None:
    blob = tmp_path / "not-a-binary.so"
    blob.write_bytes(b"not even close to an ELF magic byte set")
    result = asyncio.new_event_loop().run_until_complete(ghidra.analyze_native_lib(blob))
    assert "error" in result
    assert "unknown binary format" in result["error"]


def test_analyze_native_lib_missing_file_returns_error(ghidra, tmp_path) -> None:
    result = asyncio.new_event_loop().run_until_complete(
        ghidra.analyze_native_lib(tmp_path / "nope.so")
    )
    assert "error" in result
    assert "not found" in result["error"]


def test_analyze_native_lib_empty_file_returns_error(ghidra, tmp_path) -> None:
    empty = tmp_path / "empty.so"
    empty.write_bytes(b"")
    result = asyncio.new_event_loop().run_until_complete(ghidra.analyze_native_lib(empty))
    assert "error" in result
    assert "empty" in result["error"]


# ─── /v1/projects/{id}/native/analyze endpoint ────────────────────────


@pytest.fixture
def native_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Upload an APK that contains a real ELF .so so the endpoint can
    pull it out and analyse it."""
    import importlib
    import io
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))

    # Build a zip-like APK with a stub ELF inside lib/arm64-v8a/.
    payload = b"".join([
        b"Java_com_target_Foo_bar\x00",
        b"https://api.target.com/x\x00",
        b"AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi\x00",
    ])
    elf_bytes = _stub_elf(payload)
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("lib/arm64-v8a/libcrypto.so", elf_bytes)
    apk_bytes = zip_buf.getvalue()

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", BytesIO(apk_bytes), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid


def test_native_analyze_endpoint_round_trips_elf(native_client) -> None:
    client, pid = native_client
    r = client.get(f"/v1/projects/{pid}/native/analyze", params={"lib": "lib/arm64-v8a/libcrypto.so"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "elf"
    assert body["lib"] == "lib/arm64-v8a/libcrypto.so"
    assert "Java_com_target_Foo_bar" in body["jni_exports"]
    assert "https://api.target.com/x" in body["hardcoded_urls"]
    assert any("AIzaSy" in k for k in body["hardcoded_keys"])


def test_native_analyze_endpoint_404s_on_missing_lib(native_client) -> None:
    client, pid = native_client
    r = client.get(f"/v1/projects/{pid}/native/analyze", params={"lib": "lib/x86/ghost.so"})
    assert r.status_code == 404
    assert "ghost.so" in r.text or "binary not in" in r.text
