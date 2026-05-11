"""Recursive Medusa module walk + slug-aware load.

Medusa organises modules hierarchically (modules/<category>/<name>.med).
The /v1/recipes endpoint must walk the whole tree, and load_medusa_module
must accept both the bare stem and the fully-qualified <category>/<name>.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with a tmp workspace + a fake Medusa checkout.

    The fake checkout matches the real Medusa layout:
      modules/scratchpad.med
      modules/encryption/cipher_1.med
      modules/encryption/cipher_2.med
      modules/JNICalls/FindClass.med
      modules/clipboard/clipboard.med
    """
    medusa = tmp_path / "medusa"
    (medusa / "modules" / "encryption").mkdir(parents=True)
    (medusa / "modules" / "JNICalls").mkdir(parents=True)
    (medusa / "modules" / "clipboard").mkdir(parents=True)

    (medusa / "modules" / "scratchpad.med").write_text(
        "// scratchpad: write Frida snippets here while you debug\n"
        "Java.perform(function () { /* … */ });\n"
    )
    (medusa / "modules" / "encryption" / "cipher_1.med").write_text(
        "// Cipher hook — log SecretKeySpec ctor args\n"
        "Java.perform(function () { /* AES */ });\n"
    )
    (medusa / "modules" / "encryption" / "cipher_2.med").write_text(
        "//=========================================\n"
        "// Cipher2 — doFinal instrumentation\n"
        "//=========================================\n"
        "Java.perform(function () { /* … */ });\n"
    )
    (medusa / "modules" / "JNICalls" / "FindClass.med").write_text(
        "// Trace every FindClass call\n"
        "Interceptor.attach(/* … */);\n"
    )
    (medusa / "modules" / "clipboard" / "clipboard.med").write_text(
        "Interceptor.attach(/* no header */);\n"
    )

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_MEDUSA_PATH", str(medusa))

    import importlib
    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        yield c


def test_recipes_endpoint_walks_full_tree(isolated_client: TestClient) -> None:
    """All 5 fake modules show up — not just scratchpad.med at the top level."""
    recipes = isolated_client.get("/v1/recipes").json()
    medusa_recipes = [r for r in recipes if r["origin"] == "medusa"]
    names = {r["name"] for r in medusa_recipes}
    assert "scratchpad" in names                       # top-level
    assert "encryption/cipher_1" in names              # nested
    assert "encryption/cipher_2" in names              # nested + banner-comment header
    assert "JNICalls/FindClass" in names               # different category casing
    assert "clipboard/clipboard" in names              # no header → falls back


def test_recipes_carry_parent_dir_as_category(isolated_client: TestClient) -> None:
    by_name = {r["name"]: r for r in isolated_client.get("/v1/recipes").json() if r["origin"] == "medusa"}
    assert by_name["encryption/cipher_1"]["category"] == "ENCRYPTION"
    assert by_name["JNICalls/FindClass"]["category"] == "JNICALLS"
    # Top-level files keep the heuristic.
    assert by_name["scratchpad"]["category"] == "MISC"


def test_recipes_pull_blurb_from_leading_comment(isolated_client: TestClient) -> None:
    by_name = {r["name"]: r for r in isolated_client.get("/v1/recipes").json() if r["origin"] == "medusa"}
    assert "scratchpad" in by_name["scratchpad"]["description"].lower()
    assert "cipher hook" in by_name["encryption/cipher_1"]["description"].lower()
    # Banner-style headers (// === / // —) should be skipped; the real description wins.
    assert "doFinal" in by_name["encryption/cipher_2"]["description"]
    # No leading comment → filename fallback (no crash).
    assert by_name["clipboard/clipboard"]["description"]


def test_recipe_script_endpoint_resolves_fully_qualified_slug(isolated_client: TestClient) -> None:
    r = isolated_client.get("/v1/recipes/encryption%2Fcipher_1/script")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "SecretKeySpec" in body["script"]


def test_recipe_script_endpoint_resolves_bare_stem(isolated_client: TestClient) -> None:
    """Bare stem still works — the engine recurses to find a match."""
    r = isolated_client.get("/v1/recipes/scratchpad/script")
    assert r.status_code == 200
    body = r.json()
    assert "scratchpad" in body["script"].lower()


def test_load_medusa_module_returns_full_text(tmp_path: Path) -> None:
    """Direct unit test on FridaEngine.load_medusa_module."""
    from mnexus.config import NexusConfig
    from mnexus.engines.frida_engine import FridaEngine

    medusa = tmp_path / "med"
    (medusa / "modules" / "encryption").mkdir(parents=True)
    target = medusa / "modules" / "encryption" / "cipher_1.med"
    target.write_text("// header\npayload();")

    cfg = NexusConfig(medusa_path=medusa)
    engine = FridaEngine(cfg)

    # Fully-qualified.
    assert "payload()" in engine.load_medusa_module("encryption/cipher_1")
    # With extension.
    assert "payload()" in engine.load_medusa_module("encryption/cipher_1.med")
    # Bare stem.
    assert "payload()" in engine.load_medusa_module("cipher_1")


def test_load_medusa_module_handles_ambiguous_stem(tmp_path: Path) -> None:
    """Two modules sharing a stem return one of them (deterministic) + log."""
    from mnexus.config import NexusConfig
    from mnexus.engines.frida_engine import FridaEngine

    medusa = tmp_path / "med"
    (medusa / "modules" / "a").mkdir(parents=True)
    (medusa / "modules" / "b").mkdir(parents=True)
    (medusa / "modules" / "a" / "init.med").write_text("from a")
    (medusa / "modules" / "b" / "init.med").write_text("from b")

    cfg = NexusConfig(medusa_path=medusa)
    engine = FridaEngine(cfg)
    out = engine.load_medusa_module("init")
    assert out in {"from a", "from b"}  # picks first sorted; both are valid


def test_load_medusa_module_raises_when_missing(tmp_path: Path) -> None:
    from mnexus.config import NexusConfig
    from mnexus.engines.frida_engine import FridaEngine

    medusa = tmp_path / "med"
    (medusa / "modules").mkdir(parents=True)
    cfg = NexusConfig(medusa_path=medusa)
    engine = FridaEngine(cfg)
    with pytest.raises(FileNotFoundError):
        engine.load_medusa_module("not_there")
