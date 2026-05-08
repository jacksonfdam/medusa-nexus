"""Device fingerprint used by the Play client.

The Play protocol expects every checkin / delivery request to look
like it's coming from a real Android device. The fingerprint below is
the same ``device.properties`` used by the Aurora Store / apkeep
projects (Calyx Institute, GPL-3.0-or-later) — a stock Pixel 7a
running Android 13. Embedded as Python data so we don't need to ship
a separate config file.

Two builders consume this map:

* :func:`build_checkin_request` — assembles an ``AndroidCheckinRequest``
  protobuf for the ``/checkin`` endpoint, mint a fresh GSFID
  (Google Services Framework ID) the first time a user runs
  PlayIntel.
* :func:`build_user_agent` — formats the Aurora-style ``User-Agent``
  string used by every ``fdfe/*`` endpoint.

Anything more elaborate (per-call randomized fingerprint, multiple
profiles) is intentionally out of scope; we want to look like one
plausible device, not evade detection.
"""

from __future__ import annotations

from mnexus.playintel.protobuf_codec import MessageBuilder

# Field numbers from `pkg/googleplay/protos/GooglePlay.proto` in the
# original Go reference. Names match the proto for greppability.
_F_BUILD_ID = 1
_F_BUILD_PRODUCT = 2
_F_BUILD_CARRIER = 3
_F_BUILD_RADIO = 4
_F_BUILD_BOOTLOADER = 5
_F_BUILD_CLIENT = 6
_F_BUILD_TIMESTAMP = 7
_F_BUILD_GOOGLE_SERVICES = 8
_F_BUILD_DEVICE = 9
_F_BUILD_SDK = 10
_F_BUILD_MODEL = 11
_F_BUILD_MANUFACTURER = 12
_F_BUILD_BUILD_PRODUCT = 13
_F_BUILD_OTA_INSTALLED = 14

_F_CHK_BUILD = 1
_F_CHK_LAST_CHECKIN_MSEC = 2
_F_CHK_CELL_OPERATOR = 6
_F_CHK_SIM_OPERATOR = 7
_F_CHK_ROAMING = 8
_F_CHK_USER_NUMBER = 9

_F_REQ_ID = 2
_F_REQ_CHECKIN = 4
_F_REQ_LOCALE = 6
_F_REQ_TIME_ZONE = 12
_F_REQ_VERSION = 14
_F_REQ_DEVICE_CONFIG = 18
_F_REQ_FRAGMENT = 20

_F_DC_TOUCH_SCREEN = 1
_F_DC_KEYBOARD = 2
_F_DC_NAVIGATION = 3
_F_DC_SCREEN_LAYOUT = 4
_F_DC_HAS_HARD_KEYBOARD = 5
_F_DC_HAS_FIVE_WAY_NAV = 6
_F_DC_SCREEN_DENSITY = 7
_F_DC_GLES_VERSION = 8
_F_DC_SHARED_LIB = 9
_F_DC_FEATURE = 10
_F_DC_NATIVE_PLATFORM = 11
_F_DC_SCREEN_WIDTH = 12
_F_DC_SCREEN_HEIGHT = 13
_F_DC_LOCALES = 14
_F_DC_GL_EXTENSION = 15
_F_DC_DEVICE_CLASS = 16
_F_DC_MAX_APK_DOWNLOAD_MB = 17


# ─── Embedded device fingerprint (Pixel 7a / Android 13) ──────────────────

DEFAULT_DEVICE_PROPS: dict[str, str] = {
    "UserReadableName": "Google Pixel 7a",
    "Build.BOOTLOADER": "lynx-1.0-9716681",
    "Build.BRAND": "google",
    "Build.DEVICE": "lynx",
    "Build.FINGERPRINT": "google/lynx/lynx:13/TQ2B.230505.005.A1/9808202:user/release-keys",
    "Build.HARDWARE": "lynx",
    "Build.ID": "TQ2A.230505.002",
    "Build.MANUFACTURER": "Google",
    "Build.MODEL": "Pixel 7a",
    "Build.PRODUCT": "lynx",
    "Build.RADIO": "g5300n-230203-230323-B-9801058,g5300n-230203-230323-B-9801058",
    "Build.VERSION.RELEASE": "13",
    "Build.VERSION.SDK_INT": "33",
    "CellOperator": "310",
    "Client": "android-google",
    "GL.Version": "196610",
    "GSF.version": "203615037",
    "HasFiveWayNavigation": "false",
    "HasHardKeyboard": "false",
    "Keyboard": "1",
    "Navigation": "1",
    "Roaming": "mobile-notroaming",
    "Screen.Density": "420",
    "Screen.Height": "2156",
    "Screen.Width": "1080",
    "ScreenLayout": "2",
    "SimOperator": "38",
    "TimeZone": "UTC-10",
    "TouchScreen": "3",
    "Vending.version": "82201710",
    "Vending.versionString": "22.0.17-21 [0] [PR] 332555730",
    # Keep the lists short. The Play backend tolerates trimmed sets;
    # carrying the full Pixel-7a feature/locale/extension dump is
    # overkill for our purposes and ~25 KB of noise on every checkin.
    "Platforms": "arm64-v8a",
    "Locales": "en_US,en",
    "SharedLibraries": "android.test.runner,com.google.android.maps",
    "Features": (
        "android.hardware.touchscreen,android.hardware.touchscreen.multitouch,"
        "android.hardware.wifi,android.hardware.location,android.hardware.bluetooth,"
        "android.hardware.bluetooth_le,android.hardware.camera,android.hardware.camera.any,"
        "android.hardware.camera.flash,android.hardware.microphone,android.software.app_widgets,"
        "android.software.live_wallpaper,android.software.midi,android.software.print,"
        "android.software.webview,android.software.input_methods,android.hardware.audio.output,"
        "android.hardware.faketouch"
    ),
    "GL.Extensions": (
        "GL_OES_compressed_ETC1_RGB8_texture,GL_OES_EGL_image,GL_OES_EGL_image_external,"
        "GL_OES_depth24,GL_OES_depth_texture,GL_OES_element_index_uint,"
        "GL_OES_standard_derivatives,GL_OES_texture_float,GL_OES_texture_half_float,"
        "GL_OES_packed_depth_stencil,GL_OES_rgb8_rgba8,GL_OES_vertex_array_object,"
        "GL_KHR_blend_equation_advanced,GL_KHR_texture_compression_astc_ldr,"
        "GL_EXT_texture_filter_anisotropic,GL_EXT_texture_storage,GL_EXT_color_buffer_float"
    ),
}


# ─── Helpers over the property map ────────────────────────────────────────


def _get_int(props: dict[str, str], key: str) -> int:
    try:
        return int(props.get(key, "0"))
    except ValueError:
        return 0


def _get_list(props: dict[str, str], key: str) -> list[str]:
    raw = props.get(key) or ""
    return [s for s in (p.strip() for p in raw.split(",")) if s]


def parse_properties_file(content: str) -> dict[str, str]:
    """Parse a ``device.properties``-style ``key=value`` config blob.

    Lines starting with ``#`` and empty lines are ignored. Useful for
    callers that want to load an Aurora-Store-style config off disk
    rather than using :data:`DEFAULT_DEVICE_PROPS`.
    """
    out: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        if sep:
            out[key.strip()] = val.strip()
    return out


# ─── Protobuf builders ────────────────────────────────────────────────────


def build_device_configuration(props: dict[str, str]) -> bytes:
    """Serialize the ``DeviceConfigurationProto`` sub-message."""
    b = MessageBuilder()
    b.add_varint(_F_DC_TOUCH_SCREEN, _get_int(props, "TouchScreen"))
    b.add_varint(_F_DC_KEYBOARD, _get_int(props, "Keyboard"))
    b.add_varint(_F_DC_NAVIGATION, _get_int(props, "Navigation"))
    b.add_varint(_F_DC_SCREEN_LAYOUT, _get_int(props, "ScreenLayout"))
    b.add_bool(_F_DC_HAS_HARD_KEYBOARD, props.get("HasHardKeyboard") == "true")
    b.add_bool(_F_DC_HAS_FIVE_WAY_NAV, props.get("HasFiveWayNavigation") == "true")
    b.add_varint(_F_DC_SCREEN_DENSITY, _get_int(props, "Screen.Density"))
    b.add_varint(_F_DC_GLES_VERSION, _get_int(props, "GL.Version"))
    for lib in _get_list(props, "SharedLibraries") or [
        "android.test.runner",
        "com.google.android.maps",
    ]:
        b.add_string(_F_DC_SHARED_LIB, lib)
    for feat in _get_list(props, "Features") or [
        "android.hardware.touchscreen",
        "android.hardware.wifi",
        "android.hardware.location",
    ]:
        b.add_string(_F_DC_FEATURE, feat)
    for plat in _get_list(props, "Platforms"):
        b.add_string(_F_DC_NATIVE_PLATFORM, plat)
    b.add_varint(_F_DC_SCREEN_WIDTH, _get_int(props, "Screen.Width"))
    b.add_varint(_F_DC_SCREEN_HEIGHT, _get_int(props, "Screen.Height"))
    for loc in _get_list(props, "Locales"):
        b.add_string(_F_DC_LOCALES, loc)
    for ext in _get_list(props, "GL.Extensions") or [
        "GL_OES_compressed_ETC1_RGB8_texture",
        "GL_OES_EGL_image",
    ]:
        b.add_string(_F_DC_GL_EXTENSION, ext)
    b.add_varint(_F_DC_DEVICE_CLASS, 0)
    b.add_varint(_F_DC_MAX_APK_DOWNLOAD_MB, 50)
    return b.to_bytes()


def build_checkin_request(props: dict[str, str] | None = None) -> bytes:
    """Build the ``AndroidCheckinRequest`` payload for ``POST /checkin``.

    Result is the raw protobuf bytes — POST it with
    ``Content-Type: application/x-protobuf``. The response is an
    ``AndroidCheckinResponse`` whose ``androidId`` (fixed64 field 7)
    is the freshly minted GSFID.
    """
    p = props or DEFAULT_DEVICE_PROPS

    build = (
        MessageBuilder()
        .add_string(_F_BUILD_ID, p.get("Build.FINGERPRINT", ""))
        .add_string(_F_BUILD_PRODUCT, p.get("Build.HARDWARE", ""))
        .add_string(_F_BUILD_CARRIER, p.get("Build.BRAND", ""))
        .add_string(_F_BUILD_RADIO, p.get("Build.RADIO", ""))
        .add_string(_F_BUILD_BOOTLOADER, p.get("Build.BOOTLOADER", ""))
        .add_string(_F_BUILD_CLIENT, p.get("Client", ""))
        .add_varint(_F_BUILD_TIMESTAMP, 0)
        .add_varint(_F_BUILD_GOOGLE_SERVICES, _get_int(p, "GSF.version"))
        .add_string(_F_BUILD_DEVICE, p.get("Build.DEVICE", ""))
        .add_varint(_F_BUILD_SDK, _get_int(p, "Build.VERSION.SDK_INT"))
        .add_string(_F_BUILD_MODEL, p.get("Build.MODEL", ""))
        .add_string(_F_BUILD_MANUFACTURER, p.get("Build.MANUFACTURER", ""))
        .add_string(_F_BUILD_BUILD_PRODUCT, p.get("Build.PRODUCT", ""))
        .add_bool(_F_BUILD_OTA_INSTALLED, False)
    )

    checkin = (
        MessageBuilder()
        .add_message(_F_CHK_BUILD, build)
        .add_varint(_F_CHK_LAST_CHECKIN_MSEC, 0)
        .add_string(_F_CHK_CELL_OPERATOR, p.get("CellOperator", ""))
        .add_string(_F_CHK_SIM_OPERATOR, p.get("SimOperator", ""))
        .add_string(_F_CHK_ROAMING, p.get("Roaming", ""))
        .add_varint(_F_CHK_USER_NUMBER, 0)
    )

    req = (
        MessageBuilder()
        .add_varint(_F_REQ_ID, 0)
        .add_message(_F_REQ_CHECKIN, checkin)
        .add_string(_F_REQ_LOCALE, p.get("Locales", "en_US"))
        .add_string(_F_REQ_TIME_ZONE, p.get("TimeZone", "UTC"))
        .add_varint(_F_REQ_VERSION, 3)
        .add_message(_F_REQ_DEVICE_CONFIG, build_device_configuration(p))
        .add_varint(_F_REQ_FRAGMENT, 0)
    )
    return req.to_bytes()


def build_user_agent(props: dict[str, str] | None = None) -> str:
    """Format the Aurora-Store-style ``Android-Finsky/...`` User-Agent."""
    p = props or DEFAULT_DEVICE_PROPS
    return (
        f"Android-Finsky/{p.get('Vending.versionString', '')} "
        f"(api=3,versionCode={p.get('Vending.version', '')},"
        f"sdk={p.get('Build.VERSION.SDK_INT', '')},"
        f"device={p.get('Build.DEVICE', '')},"
        f"hardware={p.get('Build.HARDWARE', '')},"
        f"product={p.get('Build.PRODUCT', '')},"
        f"platformVersionRelease={p.get('Build.VERSION.RELEASE', '')},"
        f"model={p.get('Build.MODEL', '')},"
        f"buildId={p.get('Build.ID', '')},"
        f"isWideScreen=0,"
        f"supportedAbis={p.get('Platforms', '')})"
    )
