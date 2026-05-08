"""Device fingerprint + checkin-request builder tests."""

from __future__ import annotations

from mnexus.playintel.device_props import (
    DEFAULT_DEVICE_PROPS,
    build_checkin_request,
    build_user_agent,
    parse_properties_file,
)
from mnexus.playintel.protobuf_codec import (
    find_path,
    get_int,
    get_string,
    iter_fields,
)


def test_default_props_contain_required_keys() -> None:
    """A handful of keys are mandatory for the protocol — assert they exist."""
    required = {
        "Build.MODEL",
        "Build.DEVICE",
        "Build.VERSION.SDK_INT",
        "GSF.version",
        "Vending.versionString",
        "Vending.version",
        "Locales",
        "TimeZone",
    }
    assert required.issubset(DEFAULT_DEVICE_PROPS.keys())


def test_user_agent_has_finsky_signature() -> None:
    ua = build_user_agent()
    assert ua.startswith("Android-Finsky/")
    # The Aurora-style UA encodes a handful of fields the Play backend uses
    # for compatibility checks.
    for needle in ("api=3", "versionCode=", "sdk=33", "device=lynx", "model=Pixel 7a"):
        assert needle in ua, f"missing {needle!r} in UA: {ua}"


def test_parse_properties_file_handles_comments_and_blank_lines() -> None:
    blob = (
        "# header comment\n"
        "\n"
        "Key.A = value-a\n"
        "Key.B=value-b\n"
        "  Key.C  =  value c with spaces  \n"
        "# trailing\n"
    )
    parsed = parse_properties_file(blob)
    assert parsed == {
        "Key.A": "value-a",
        "Key.B": "value-b",
        "Key.C": "value c with spaces",
    }


def test_checkin_request_round_trips_locale_and_version() -> None:
    """Decode the produced AndroidCheckinRequest and verify a few top-level fields.

    AndroidCheckinRequest:
      id          = 2  (int64, == 0)
      checkin     = 4  (sub-message)
      locale      = 6  (string)
      timeZone    = 12 (string)
      version     = 14 (int32, == 3)
      device_cfg  = 18 (sub-message)
      fragment    = 20 (int32, == 0)
    """
    buf = build_checkin_request()
    assert get_int(buf, 2) == 0
    assert get_int(buf, 14) == 3
    assert get_int(buf, 20) == 0
    assert get_string(buf, 6) == DEFAULT_DEVICE_PROPS["Locales"]
    assert get_string(buf, 12) == DEFAULT_DEVICE_PROPS["TimeZone"]


def test_checkin_request_embeds_build_fingerprint() -> None:
    """AndroidCheckinProto.build.id (= field 1 of build sub-message)
    should carry the Build.FINGERPRINT string.
    """
    # Path: checkin(4) → build(1) → id(1)
    build_id = get_string(find_path(build_checkin_request(), 4, 1) or b"", 1)
    assert build_id == DEFAULT_DEVICE_PROPS["Build.FINGERPRINT"]


def test_checkin_request_carries_device_configuration() -> None:
    """DeviceConfigurationProto should be present at field 18 with at least
    the screen-density and gl-es-version varint fields populated."""
    dc_buf = find_path(build_checkin_request(), 18)
    assert isinstance(dc_buf, (bytes, bytearray))
    # screenDensity = 7 (varint)
    assert get_int(bytes(dc_buf), 7) == int(DEFAULT_DEVICE_PROPS["Screen.Density"])
    # glEsVersion = 8 (varint)
    assert get_int(bytes(dc_buf), 8) == int(DEFAULT_DEVICE_PROPS["GL.Version"])


def test_custom_props_override_default() -> None:
    """Caller-supplied props must propagate into the encoded UA + checkin."""
    custom = dict(DEFAULT_DEVICE_PROPS)
    custom["Build.MODEL"] = "Pixel Custom Test"
    ua = build_user_agent(custom)
    assert "model=Pixel Custom Test" in ua
    # The checkin build sub-message also carries the model at field 11.
    build_blob = find_path(build_checkin_request(custom), 4, 1)
    assert isinstance(build_blob, (bytes, bytearray))
    assert get_string(bytes(build_blob), 11) == "Pixel Custom Test"


def test_checkin_includes_at_least_one_native_platform() -> None:
    """DeviceConfigurationProto.nativePlatform (field 11, repeated string)
    is what Play uses to filter compatible APKs by ABI.
    """
    dc_buf = find_path(build_checkin_request(), 18)
    assert isinstance(dc_buf, (bytes, bytearray))
    platforms = [
        bytes(p).decode("utf-8")
        for fn, _wt, p in iter_fields(bytes(dc_buf))
        if fn == 11 and isinstance(p, (bytes, bytearray))
    ]
    assert "arm64-v8a" in platforms
