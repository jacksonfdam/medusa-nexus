"""BurpEngine probe planning — which URLs get tried for each key style."""

from __future__ import annotations

import pytest

from mnexus.config import NexusConfig
from mnexus.engines.burp_engine import BurpEngine


@pytest.fixture
def engine() -> BurpEngine:
    return BurpEngine(NexusConfig(burp_url="http://127.0.0.1:8090"))


def test_empty_key_probes_burp_rest_api_only(engine: BurpEngine) -> None:
    plan = engine._probe_plan("http://127.0.0.1:8090", "")
    assert plan == [("burp-rest-api", "http://127.0.0.1:8090/burp/versions")]


def test_none_sentinel_probes_burp_rest_api_only(engine: BurpEngine) -> None:
    plan = engine._probe_plan("http://127.0.0.1:8090", "none")
    assert plan == [("burp-rest-api", "http://127.0.0.1:8090/burp/versions")]


def test_no_auth_sentinel_also_falls_back_to_pro_probe(engine: BurpEngine) -> None:
    plan = engine._probe_plan("http://127.0.0.1:8090", "no-auth")
    assert plan == [
        ("burp-rest-api", "http://127.0.0.1:8090/burp/versions"),
        ("pro-fallback", "http://127.0.0.1:8090/no-auth/v0.1/"),
    ]


def test_real_key_probes_pro_first_then_burp_rest_api(engine: BurpEngine) -> None:
    plan = engine._probe_plan("http://127.0.0.1:1337", "abc-123-key")
    assert plan == [
        ("pro", "http://127.0.0.1:1337/abc-123-key/v0.1/"),
        ("burp-rest-api", "http://127.0.0.1:1337/burp/versions"),
    ]
