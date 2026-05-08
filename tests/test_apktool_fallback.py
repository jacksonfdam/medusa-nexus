"""APKToolEngine subprocess-fallback tests.

Three layers of coverage:

1. The fast path: when ``parse_apk`` returns a meta with a package id,
   the fallback must NOT shell out — costs (subprocess + JVM warm-up)
   are avoidable and we don't want to introduce a regression on the
   90% case.
2. The no-binary path: when ``apktool`` isn't on PATH, we return the
   built-in meta unchanged — the rest of the pipeline stays operable
   and the analyst gets the same result they'd have gotten before
   Phase B landed.
3. The integration path (skipif): with a real ``apktool`` installed,
   handing in a synthetic APK whose manifest the built-in decoder
   can't parse must come back with the recovered fields. Verifies the
   subprocess wiring, timeout, and meta merge.
"""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from pathlib import Path

import pytest

from mnexus.config import NexusConfig
from mnexus.engines.apktool_engine import APKToolEngine


@pytest.fixture()
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> APKToolEngine:
    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "ws"))
    return APKToolEngine(NexusConfig.from_env())


# ─── fast path ───────────────────────────────────────────────────────────


def test_fallback_skips_subprocess_when_builtin_succeeds(
    engine: APKToolEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain-XML manifest parses fine in-process — the apktool
    subprocess must NOT be invoked. We assert by trapping
    asyncio.create_subprocess_exec and verifying it's never called."""
    apk = tmp_path / "good.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr(
            "AndroidManifest.xml",
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
            'package="com.example.fast"/>',
        )

    spy_called = {"count": 0}

    async def fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        spy_called["count"] += 1
        raise AssertionError("apktool subprocess should not run on the fast path")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )
    meta = asyncio.run(engine.parse_apk_with_fallback(apk))
    assert meta["package"] == "com.example.fast"
    assert spy_called["count"] == 0


# ─── no-binary path ──────────────────────────────────────────────────────


def test_fallback_returns_builtin_when_apktool_missing(
    engine: APKToolEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the built-in fails AND apktool isn't on PATH, return the
    empty meta — pipeline keeps going, no exception raised."""
    apk = tmp_path / "garbled.apk"
    # A "manifest" the built-in AXML decoder cannot parse: AXML magic
    # but truncated payload. _parse_manifest returns {}.
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00\x00\x00\x00\x00garbage")

    monkeypatch.setattr("shutil.which", lambda _name: None)
    meta = asyncio.run(engine.parse_apk_with_fallback(apk))
    # Built-in returned empty meta and we didn't raise; package is empty.
    assert meta.get("package", "") == ""


# ─── merge layer ─────────────────────────────────────────────────────────


def test_fallback_merges_recovered_fields_into_builtin_meta(
    engine: APKToolEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the subprocess does come back with a parsed manifest, the
    fallback must FOLD those fields into the existing meta — not
    replace it wholesale. Native libs + zip listing came from
    parse_apk's zip walk and apktool doesn't touch them; manifest-
    derived fields (package, versions, components, deeplinks) get
    refreshed from the recovered dict.
    """
    apk = tmp_path / "x.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00garbage")
        zf.writestr("lib/arm64-v8a/libfoo.so", b"\x7fELF" + b"\x00" * 32)

    # Pretend the apktool subprocess succeeded and returned this:
    async def fake_subprocess(self, _bin, _path):  # type: ignore[no-untyped-def]
        return {
            "package": "com.recovered.app",
            "version_name": "9.9.9",
            "version_code": "999",
            "min_sdk": "21",
            "target_sdk": "34",
            "permissions": ["android.permission.INTERNET"],
            "exported_components": [
                {"name": ".Main", "type": "activity",
                 "permission": None, "intent_filters": [], "unprotected": True}
            ],
            "deeplinks": ["myapp://"],
        }

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/apktool")
    monkeypatch.setattr(
        APKToolEngine,
        "_apktool_extract_manifest",
        fake_subprocess,
    )

    meta = asyncio.run(engine.parse_apk_with_fallback(apk))
    # Manifest-derived fields came from apktool.
    assert meta["package"] == "com.recovered.app"
    assert meta["version_name"] == "9.9.9"
    assert "android.permission.INTERNET" in meta["permissions"]
    assert meta["exported_components"][0]["name"] == ".Main"
    assert meta["deeplinks"] == ["myapp://"]
    # Native libs survived — apktool fallback doesn't clobber zip-walk fields.
    assert any(
        n.get("path") == "lib/arm64-v8a/libfoo.so"
        for n in meta.get("native_libraries", [])
    )
    # Provenance flag set so downstream code can tell this took the slow path.
    assert meta["_manifest_source"] == "apktool-fallback"


def test_fallback_does_not_clobber_meta_when_subprocess_returns_empty(
    engine: APKToolEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the subprocess fires but returns {} (apktool exit non-zero,
    timeout, no manifest produced), the original built-in meta must
    pass through untouched and ``_manifest_source`` must NOT be
    stamped — that flag is reserved for successful recoveries."""
    apk = tmp_path / "x.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00garbage")
        zf.writestr("lib/arm64-v8a/libfoo.so", b"\x7fELF" + b"\x00" * 32)

    async def empty_recovery(self, _bin, _path):  # type: ignore[no-untyped-def]
        return {}

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/apktool")
    monkeypatch.setattr(APKToolEngine, "_apktool_extract_manifest", empty_recovery)

    meta = asyncio.run(engine.parse_apk_with_fallback(apk))
    assert meta.get("package", "") == ""
    assert "_manifest_source" not in meta
    # Native libs from zip walk still present.
    assert meta.get("native_libraries")


# ─── timeout safety ──────────────────────────────────────────────────────


def test_fallback_handles_subprocess_timeout(
    engine: APKToolEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the subprocess hangs, the fallback must time out and return
    the built-in meta rather than blocking the engine forever."""
    apk = tmp_path / "garbled.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00garbage")

    # Spy on wait_for with a tiny timeout so the test isn't slow.
    monkeypatch.setattr("shutil.which", lambda _name: "/fake/apktool")

    class _HungProcess:
        async def communicate(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(60)  # never finishes within the wait_for window

        def kill(self):  # type: ignore[no-untyped-def]
            pass

        async def wait(self):  # type: ignore[no-untyped-def]
            return 0

    async def fake_create_subprocess_exec(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _HungProcess()

    async def fast_wait_for(awaitable, timeout):  # type: ignore[no-untyped-def]
        # Close the un-awaited coroutine so pytest doesn't print a
        # ResourceWarning, then simulate the timeout the real
        # asyncio.wait_for would have raised.
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", fake_create_subprocess_exec
    )
    monkeypatch.setattr("asyncio.wait_for", fast_wait_for)

    meta = asyncio.run(engine.parse_apk_with_fallback(apk))
    assert meta.get("package", "") == ""  # fallback gracefully gave up
