"""source_reader — resolve + read decompiled classes straight off disk.

Focus: the fqcn resolver picks the right file across the real jadx
``sources/`` layout and the flatter test layout, folds inner classes into
their outer file, honours smali splits, and — critically — refuses to walk
out of the project subtree when handed a hostile fqcn.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mnexus.intelligence.source_reader import (
    read_class_source,
    resolve_class_file,
    search_classes,
)

_PID = "PRJ-DEADBEEF"


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """A minimal decompiled workspace: jadx sources/ + a smali split."""
    base = tmp_path / _PID
    _write(base, "jadx/sources/com/target/auth/LoginManager.java",
           "package com.target.auth;\npublic class LoginManager {\n  void go(){}\n}\n")
    # Inner class Outer$Inner folds into Outer.java (jadx behaviour).
    _write(base, "jadx/sources/com/target/ui/Outer.java",
           "package com.target.ui;\nclass Outer { class Inner {} }\n")
    _write(base, "apktool/smali/com/target/auth/LoginManager.smali",
           ".class public Lcom/target/auth/LoginManager;\n")
    _write(base, "apktool/smali_classes2/com/target/pay/Wallet.smali",
           ".class public Lcom/target/pay/Wallet;\n")
    return tmp_path


# ─── resolve ───────────────────────────────────────────────────────────


def test_resolves_java_under_sources(ws: Path) -> None:
    resolved = resolve_class_file(ws, _PID, "com.target.auth.LoginManager", "java")
    assert resolved is not None
    path, lang = resolved
    assert path.name == "LoginManager.java"
    assert lang == "java"


def test_resolves_flat_jadx_layout(tmp_path: Path) -> None:
    # Some layouts (and the /find test fixtures) drop the class straight
    # under jadx/ with no sources/ prefix. The resolver must still find it.
    _write(tmp_path / _PID, "jadx/com/target/Config.java", "class Config {}\n")
    resolved = resolve_class_file(tmp_path, _PID, "com.target.Config", "java")
    assert resolved is not None
    assert resolved[0].name == "Config.java"


def test_inner_class_folds_into_outer_file(ws: Path) -> None:
    resolved = resolve_class_file(ws, _PID, "com.target.ui.Outer$Inner", "java")
    assert resolved is not None
    assert resolved[0].name == "Outer.java"


def test_resolves_smali_across_splits(ws: Path) -> None:
    a = resolve_class_file(ws, _PID, "com.target.auth.LoginManager", "smali")
    b = resolve_class_file(ws, _PID, "com.target.pay.Wallet", "smali")
    assert a is not None
    assert a[0].suffix == ".smali"
    assert b is not None
    assert "smali_classes2" in b[0].as_posix()


def test_missing_class_returns_none(ws: Path) -> None:
    assert resolve_class_file(ws, _PID, "com.target.Ghost", "java") is None


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../../etc/passwd",
        "..%2f..%2fetc",
        "/etc/shadow",
        "com.target..secret",
        "com target space",
        "",
    ],
)
def test_hostile_fqcn_is_rejected(ws: Path, hostile: str) -> None:
    assert resolve_class_file(ws, _PID, hostile, "java") is None
    assert resolve_class_file(ws, _PID, hostile, "smali") is None


def test_symlink_escape_is_confined(tmp_path: Path) -> None:
    # A symlink inside the jadx tree that points outside must not let a
    # resolved path escape the project root.
    secret = tmp_path / "outside" / "Secret.java"
    secret.parent.mkdir(parents=True)
    secret.write_text("TOP SECRET", encoding="utf-8")
    jadx = tmp_path / _PID / "jadx" / "sources" / "com" / "evil"
    jadx.mkdir(parents=True)
    link = jadx / "Secret.java"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")
    # The confinement check resolves the symlink target; it lands outside
    # <ws>/<pid>/jadx and is rejected.
    assert resolve_class_file(tmp_path, _PID, "com.evil.Secret", "java") is None


# ─── read ──────────────────────────────────────────────────────────────


def test_read_returns_body(ws: Path) -> None:
    src = read_class_source(ws, _PID, "com.target.auth.LoginManager", "java")
    assert src is not None
    assert "class LoginManager" in src.text
    assert src.file.endswith("LoginManager.java")
    assert src.lang == "java"
    assert src.truncated is False


def test_read_truncates_large_class(ws: Path) -> None:
    src = read_class_source(ws, _PID, "com.target.auth.LoginManager", "java", max_bytes=10)
    assert src is not None
    assert src.truncated is True
    assert len(src.text) == 10


def test_read_smali(ws: Path) -> None:
    src = read_class_source(ws, _PID, "com.target.pay.Wallet", "smali")
    assert src is not None
    assert src.lang == "smali"
    assert ".class" in src.text


# ─── search ──────────────────────────────────────────────────────────────


def test_search_by_keyword(ws: Path) -> None:
    hits = search_classes(ws, _PID, "auth", fmt="java")
    assert [h.fqcn for h in hits] == ["com.target.auth.LoginManager"]


def test_search_empty_lists_all(ws: Path) -> None:
    fqcns = {h.fqcn for h in search_classes(ws, _PID, "", fmt="java")}
    assert fqcns == {"com.target.auth.LoginManager", "com.target.ui.Outer"}


def test_search_smali_spans_splits(ws: Path) -> None:
    fqcns = {h.fqcn for h in search_classes(ws, _PID, "target", fmt="smali")}
    assert fqcns == {"com.target.auth.LoginManager", "com.target.pay.Wallet"}


def test_search_limit(ws: Path) -> None:
    assert len(search_classes(ws, _PID, "", fmt="java", limit=1)) == 1
