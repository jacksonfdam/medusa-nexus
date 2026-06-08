"""Stack multiple Medusa recipes in one FridaSession.

The session class already accepts a list of (name, source) pairs, but
the start endpoint resolves only auto-hooks. This file pins:

  * /dynamic/start accepts a `recipes` form field with built-in and
    Medusa-disk recipe names
  * Built-ins are resolved from BUILTIN_RECIPES; disk recipes go
    through FridaEngine.load_medusa_module
  * Each recipe source is wrapped in an IIFE so per-recipe globals
    don't collide (e.g. two pinning bypass recipes both declaring
    `var CP = …` won't blow up)
  * Unknown recipe names produce a clean 400
"""

from __future__ import annotations

import importlib
import io

import pytest
from fastapi.testclient import TestClient


_RECIPE_PINNING_SRC = "Java.perform(function () { console.log('pinning bypass'); });"
_RECIPE_CRYPTO_SRC = "Java.perform(function () { console.log('crypto logger'); });"


@pytest.fixture
def stacking_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Real Moxy-free TestClient with frida monkeypatched + a tiny
    on-disk Medusa modules tree so the recipe lookup resolves."""
    from mnexus.runtime import frida_session as fs

    class _FakeScript:
        def __init__(self, source: str) -> None:
            self.source = source
            self.handlers: dict = {}
            self.loaded = False

        def on(self, name, handler):
            self.handlers[name] = handler

        def load(self):
            self.loaded = True

        def unload(self):
            self.loaded = False

    class _FakeSession:
        def __init__(self):
            self.scripts: list[_FakeScript] = []

        def create_script(self, source: str) -> _FakeScript:
            s = _FakeScript(source)
            self.scripts.append(s)
            return s

        def detach(self):
            pass

    class _FakeDevice:
        id = "usb-stub"

        def __init__(self):
            self.spawned = []

        def spawn(self, args):
            self.spawned.append(args[0])
            return 9999

        def attach(self, pid):
            return _FakeSession()

        def resume(self, pid):
            pass

        def kill(self, pid):
            pass

        def get_process(self, package):
            raise RuntimeError("not running")

    device = _FakeDevice()

    class _FakeManager:
        def get_usb_device(self, timeout=2):  # noqa: ARG002
            return device

        def get_device(self, did, timeout=2):  # noqa: ARG002
            return device

    class _FakeFrida:
        @staticmethod
        def get_device_manager():
            return _FakeManager()

    monkeypatch.setattr(fs, "frida", _FakeFrida)
    monkeypatch.setattr(fs, "FRIDA_AVAILABLE", True)
    fs.session_registry.clear()

    # Lay down a Medusa modules dir with two recipes the test can request.
    medusa = tmp_path / "medusa"
    (medusa / "modules" / "ssl").mkdir(parents=True)
    (medusa / "modules" / "ssl" / "pinning_bypass.med").write_text(_RECIPE_PINNING_SRC)
    (medusa / "modules" / "crypto").mkdir()
    (medusa / "modules" / "crypto" / "logger.med").write_text(_RECIPE_CRYPTO_SRC)

    monkeypatch.setenv("MNEXUS_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("MNEXUS_DB_PATH", str(tmp_path / "nexus.sqlite3"))
    monkeypatch.setenv("MNEXUS_MEDUSA_PATH", str(medusa))

    from mnexus.api import main as api_main
    importlib.reload(api_main)
    with TestClient(api_main.app) as c:
        r = c.post(
            "/v1/apks/upload",
            files={"file": ("target.apk", io.BytesIO(b"PK\x03\x04stub"), "application/vnd.android.package-archive")},
            data={"package": "com.target.app", "version": "1.0"},
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        yield c, pid, device


# ─── happy paths ──────────────────────────────────────────────────────


def test_start_loads_multiple_recipes_in_one_session(stacking_client) -> None:
    client, pid, device = stacking_client
    r = client.post(
        f"/v1/projects/{pid}/dynamic/start",
        data={"hooks": "", "recipes": "ssl/pinning_bypass,crypto/logger", "spawn": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Both recipes appear as separate scripts in the session.
    names = body["scripts"]
    assert "recipe::ssl/pinning_bypass" in names
    assert "recipe::crypto/logger" in names

    # Each recipe source must be wrapped in an IIFE — verify by digging
    # into the FakeSession's captured scripts via the session_registry.
    from mnexus.runtime import session_registry
    sess = session_registry[body["session_id"]]
    pinning_script = next(s for s in sess.scripts if s.name == "recipe::ssl/pinning_bypass")
    assert "(function ()" in pinning_script.source
    assert "Java.perform" in pinning_script.source  # the original body survived
    assert "try {" in pinning_script.source
    # IIFE wraps with a catch that fires send({channel:'error',...})
    assert "channel: 'error'" in pinning_script.source


def test_start_supports_builtin_recipes_alongside_disk_recipes(stacking_client) -> None:
    client, pid, device = stacking_client
    # Pick a built-in recipe name we know exists.
    builtins = client.get("/v1/recipes").json()
    builtin_names = [r["name"] for r in builtins if r["origin"] == "builtin"]
    assert builtin_names, "BUILTIN_RECIPES catalogue is empty?"
    builtin = builtin_names[0]

    r = client.post(
        f"/v1/projects/{pid}/dynamic/start",
        data={"hooks": "", "recipes": f"{builtin},ssl/pinning_bypass"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert f"recipe::{builtin}" in body["scripts"]
    assert "recipe::ssl/pinning_bypass" in body["scripts"]


def test_start_recipes_only_no_hooks_works(stacking_client) -> None:
    client, pid, _ = stacking_client
    r = client.post(
        f"/v1/projects/{pid}/dynamic/start",
        data={"hooks": "", "recipes": "ssl/pinning_bypass"},
    )
    assert r.status_code == 200
    assert r.json()["scripts"] == ["recipe::ssl/pinning_bypass"]


# ─── error paths ──────────────────────────────────────────────────────


def test_start_400_on_unknown_recipe(stacking_client) -> None:
    client, pid, _ = stacking_client
    r = client.post(
        f"/v1/projects/{pid}/dynamic/start",
        data={"hooks": "", "recipes": "ghost/missing"},
    )
    assert r.status_code == 400
    assert "ghost" in r.text or "unknown" in r.text.lower()


def test_iife_wrapper_isolates_recipe_globals() -> None:
    """Unit test on the wrapper helper itself."""
    from mnexus.api.main import _wrap_in_iife

    wrapped = _wrap_in_iife("ssl/pinning_bypass", "var CP = Java.use('okhttp3.CertificatePinner');")
    # Variable declaration is inside an IIFE — no top-level pollution.
    assert wrapped.startswith("(function ()")
    assert wrapped.rstrip().endswith("})();")
    # Original body is in there.
    assert "var CP = Java.use('okhttp3.CertificatePinner');" in wrapped
    # try/catch surrounds it.
    assert "try {" in wrapped
    assert "catch (e)" in wrapped
    # Catch path emits an error event tagged with the recipe name so
    # the SSE consumer knows which recipe blew up.
    assert "ssl/pinning_bypass" in wrapped
