"""Native Google Play protocol client (pure Python, no external deps).

Implements just enough of the protocol that PlayIntel needs:

1. ``POST /auth`` (form-encoded) — exchange the Gmail address + AAS
   master token for a short-lived OAuth-style bearer token. Plain text
   ``key=value`` response.
2. ``POST /checkin`` (protobuf) — mint a Google Services Framework ID
   the first time the client runs, so subsequent calls have a stable
   device identity. Skipped on subsequent runs once a GSFID is cached.
3. ``GET /fdfe/details?doc=<pkg>`` (protobuf response) — read the
   latest version code for a target package.
4. ``POST /fdfe/purchase?doc=<pkg>&vc=<vc>`` — claim a free app to
   obtain a delivery token. Required before /delivery for every app
   (free or paid).
5. ``GET /fdfe/delivery?doc=<pkg>&vc=<vc>&dtok=<token>`` (protobuf
   response) — read the signed CDN URL + size for the base APK plus
   any splits and OBB additional files.

Credentials are loaded from ``~/.config/apkeep/apkeep.ini`` (the same
file the apkeep CLI uses), or from explicit constructor arguments.
The four cached pieces — ``email``, ``aas_token`` (master token),
``gsfid``, and the cached ``auth_token`` — are written back on
successful checkin so subsequent runs can skip work.

This client is the native replacement for the Go-binary bridge in
``apk_source.py::PlayBinarySource``. Wired in via
:class:`mnexus.playintel.apk_source.PlayProtocolSource`.
"""

from __future__ import annotations

import configparser
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from mnexus.playintel.device_props import (
    DEFAULT_DEVICE_PROPS,
    build_checkin_request,
    build_user_agent,
)
from mnexus.playintel.protobuf_codec import (
    find_all_fields,
    find_field,
    find_path,
    get_int,
    get_string,
    get_uint64_fixed,
    iter_fields,
)

log = logging.getLogger(__name__)

# Field numbers from GooglePlay.proto. Kept inline (not imported) so a
# grep for any field number lands exactly where it's used.
# ResponseWrapper.payload = 1
# Payload.detailsResponse = 2; .buyResponse = 4; .deliveryResponse = 21
# DetailsResponse.item = 4
# Item.details = 13
# DocumentDetails.appDetails = 1
# AppDetails.versionCode = 3
# BuyResponse.purchaseResponse(1).encodedDeliveryToken = 55  -- but the Go
#   reference reads it directly off BuyResponse, which is an unnumbered
#   group; the actual proto puts encodedDeliveryToken at field 55 of
#   PurchaseNotificationResponse. We handle both shapes when decoding.
# DeliveryResponse.appDeliveryData = 2
# AndroidAppDeliveryData: downloadSize=1, downloadUrl=3, additionalFile=4 (rep),
#   splitDeliveryData=15 (rep)
# SplitDeliveryData: name=1, downloadSize=2, downloadUrl=5
# AppFileMetadata: fileType=1, versionCode=2, size=3, downloadUrl=4
# AndroidCheckinResponse: androidId=7 (fixed64), securityToken=8 (fixed64),
#   deviceCheckinConsistencyToken=12

_PLAY_BASE = "https://android.clients.google.com"
_AUTH_SERVICE = "oauth2:https://www.googleapis.com/auth/googleplay"
_GMS_CERT_SHA1 = "38918a453d07199354f8b19af05ec6562ced5788"

_AUTH_REFRESH_LEAD_S = 300  # mint a fresh token if within 5min of expiry


# ─── Config / credential storage ───────────────────────────────────────────


class PlayAuthError(RuntimeError):
    """Raised for any auth / checkin / delivery failure that's the
    user's responsibility to fix (bad token, package unavailable, …)."""


@dataclass(slots=True)
class PlayCredentials:
    """The four facts that identify one Play account on one device.

    Loaded from ``~/.config/apkeep/apkeep.ini`` by default. The
    ``aas_token`` is the long-lived master token (also called
    "Token=oauth2_master" by the apkeep wiki); ``gsfid`` is the
    Google Services Framework ID minted by checkin and effectively
    permanent for that account/device pair.
    """

    email: str
    aas_token: str
    gsfid: str = ""  # filled in by checkin if missing
    locale: str = "en-US"

    @classmethod
    def from_apkeep_ini(cls, path: Path | None = None) -> PlayCredentials:
        """Load from ``~/.config/apkeep/apkeep.ini`` (or override path).

        The apkeep config schema is::

            [google]
            username = me@gmail.com
            aas_token = aas_et/...
            gsfid = 1234567890abcdef   # optional; minted by checkin
        """
        ini_path = path or Path.home() / ".config" / "apkeep" / "apkeep.ini"
        if not ini_path.exists():
            raise PlayAuthError(
                f"apkeep config not found at {ini_path}. "
                "See https://github.com/EFForg/apkeep#configuration for setup."
            )
        parser = configparser.ConfigParser()
        parser.read(ini_path)
        if "google" not in parser:
            raise PlayAuthError(f"[google] section missing in {ini_path}")
        section = parser["google"]
        email = section.get("username") or section.get("email") or ""
        aas = section.get("aas_token") or section.get("oauth_token") or ""
        if not email or not aas:
            raise PlayAuthError(
                f"username and aas_token required in [google] section of {ini_path}"
            )
        return cls(
            email=email,
            aas_token=aas,
            gsfid=section.get("gsfid", ""),
            locale=section.get("locale", "en-US"),
        )


# ─── Wire-format result types ──────────────────────────────────────────────


@dataclass(slots=True)
class SplitInfo:
    """One config / language / ABI split returned by /delivery."""

    name: str
    url: str
    size: int


@dataclass(slots=True)
class AdditionalFile:
    """An OBB or patch file returned by /delivery."""

    name: str
    url: str
    size: int


@dataclass(slots=True)
class PlayDownloadInfo:
    """What /delivery yields for one package."""

    package_name: str
    version_code: int
    base_url: str
    base_size: int
    splits: list[SplitInfo] = field(default_factory=list)
    additional_files: list[AdditionalFile] = field(default_factory=list)


# ─── Client ────────────────────────────────────────────────────────────────


class PlayClient:
    """Pure-Python Play protocol client.

    One instance per Play account; threadsafe-enough for serial use
    (the Play protocol itself is request/response with no shared
    server-side state besides the cached auth token).

    Typical lifecycle::

        creds = PlayCredentials.from_apkeep_ini()
        client = PlayClient(creds)
        client.ensure_ready()                      # auth + checkin if needed
        info = client.get_download_info("com.example.app")
        # info.base_url is now a signed CDN URL good for ~1 hour.

    All HTTP traffic flows through a single ``httpx.Client`` so callers
    can substitute a transport (proxy, mock) for tests.
    """

    def __init__(
        self,
        credentials: PlayCredentials,
        *,
        device_props: dict[str, str] | None = None,
        http_client: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.credentials = credentials
        self.device_props = device_props or DEFAULT_DEVICE_PROPS
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_s, follow_redirects=False)
        self._auth_token: str = ""
        self._auth_token_expiry: float = 0.0
        self._device_checkin_token: str = ""

    def __enter__(self) -> PlayClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # ─── public flow ────────────────────────────────────────────────

    def ensure_ready(self) -> None:
        """Mint a GSFID if missing and a fresh auth token if expired."""
        if not self.credentials.gsfid:
            self.checkin()
        self._ensure_auth()

    def get_download_info(self, package_name: str) -> PlayDownloadInfo:
        """Resolve a package name to a signed CDN URL + size.

        Pipeline: details → purchase (delivery token) → delivery.
        Each call can fail with :class:`PlayAuthError` carrying the
        Play-side reason.
        """
        self.ensure_ready()
        version_code = self._fetch_version_code(package_name)
        delivery_token = self._fetch_delivery_token(package_name, version_code)
        return self._fetch_delivery(package_name, version_code, delivery_token)

    # ─── auth ───────────────────────────────────────────────────────

    def _ensure_auth(self) -> None:
        if self._auth_token and time.time() < self._auth_token_expiry - _AUTH_REFRESH_LEAD_S:
            return
        token, expiry = self._login_auth(_AUTH_SERVICE)
        self._auth_token = token
        # If Play didn't return Expiry=, conservatively expire in 1h.
        self._auth_token_expiry = expiry if expiry > 0 else time.time() + 3600

    def _login_auth(self, service: str) -> tuple[str, float]:
        """POST to /auth and parse the ``Auth=`` / ``Expiry=`` lines."""
        creds = self.credentials
        lang, _, country = creds.locale.partition("-")
        params = {
            "sdk_version": "33",
            "Email": creds.email,
            "google_play_services_version": self.device_props.get("GSF.version", "203615037"),
            "device_country": (country or "us").lower(),
            "lang": (lang or "en").lower(),
            "callerSig": _GMS_CERT_SHA1,
            "androidId": creds.gsfid or "0",
            "app": "com.android.vending",
            "client_sig": _GMS_CERT_SHA1,
            "callerPkg": "com.google.android.gms",
            "Token": creds.aas_token,
            "oauth2_foreground": "1",
            "token_request_options": "CAA4AVAB",
            "check_email": "1",
            "system_partition": "1",
            "service": service,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "app": "com.google.android.gms",
            "User-Agent": (
                "Dalvik/2.1.0 (Linux; U; Android 13; "
                f"{self.device_props.get('Build.MODEL', 'Pixel 7a')} "
                f"Build/{self.device_props.get('Build.ID', 'TQ2A.230505.002')})"
            ),
            "device": creds.gsfid or "0",
        }
        resp = self._http.post(f"{_PLAY_BASE}/auth", data=params, headers=headers)
        if resp.status_code != 200:
            raise PlayAuthError(
                f"/auth returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        token = ""
        expiry = 0.0
        for line in resp.text.splitlines():
            key, sep, value = line.partition("=")
            if not sep:
                continue
            if key == "Auth":
                token = value
            elif key == "Expiry":
                try:
                    expiry = float(value)
                except ValueError:
                    pass
        if not token:
            raise PlayAuthError(
                f"/auth response missing Auth=. Check that your aas_token "
                f"is valid and not expired. Raw response: {resp.text[:300]}"
            )
        return token, expiry

    # ─── checkin ────────────────────────────────────────────────────

    def checkin(self) -> str:
        """POST /checkin and persist the freshly minted GSFID.

        Returns the GSFID as a hex string. Mutates ``self.credentials``
        in place; the caller is responsible for writing it back to
        apkeep.ini if persistence is desired.
        """
        body = build_checkin_request(self.device_props)
        headers = {
            "Content-Type": "application/x-protobuf",
            "User-Agent": "Android-Checkin/2.0 (generic_x86 JMR1); gzip",
        }
        resp = self._http.post(f"{_PLAY_BASE}/checkin", content=body, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise PlayAuthError(
                f"/checkin returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        # AndroidCheckinResponse.androidId is fixed64 at field 7.
        android_id = get_uint64_fixed(resp.content, 7)
        if not android_id:
            raise PlayAuthError(
                "checkin response missing androidId — Google may have rejected "
                "the device fingerprint. Try a fresh apkeep.ini."
            )
        gsfid = f"{android_id:x}"
        self.credentials.gsfid = gsfid
        consistency = find_field(resp.content, 12)
        if isinstance(consistency, (bytes, bytearray)):
            self._device_checkin_token = bytes(consistency).decode("utf-8", errors="replace")
        log.info("playintel: checkin ok → gsfid=%s", gsfid)
        return gsfid

    # ─── fdfe/* helpers ─────────────────────────────────────────────

    def _fdfe_headers(self) -> dict[str, str]:
        """Build the standard headers every /fdfe/* call expects."""
        creds = self.credentials
        h = {
            "Authorization": f"Bearer {self._auth_token}",
            "User-Agent": build_user_agent(self.device_props),
            "X-DFE-Device-Id": creds.gsfid,
            "Accept-Language": creds.locale.replace("_", "-"),
            "X-DFE-Client-Id": "am-android-google",
            "X-DFE-Network-Type": "4",
            "X-DFE-Content-Filters": "",
            "X-Limit-Ad-Tracking-Enabled": "false",
            "X-Ad-Id": "",
            "X-DFE-UserLanguages": creds.locale,
            "X-DFE-Request-Params": "timeoutMs=4000",
        }
        if self._device_checkin_token:
            h["X-DFE-Device-Checkin-Consistency-Token"] = self._device_checkin_token
        return h

    def _fetch_version_code(self, package_name: str) -> int:
        """``GET /fdfe/details?doc=<pkg>`` and read AppDetails.versionCode."""
        url = f"{_PLAY_BASE}/fdfe/details"
        resp = self._http.get(
            url, params={"doc": package_name}, headers=self._fdfe_headers()
        )
        if resp.status_code != 200:
            raise PlayAuthError(
                f"/details returned HTTP {resp.status_code} for {package_name} — "
                "package may not exist or not available in your region"
            )
        # ResponseWrapper(1).payload(2).detailsResponse(4).item(13).details(1).appDetails(3).versionCode
        # Path: payload=1, detailsResponse=2, item=4, details=13, appDetails=1
        # then AppDetails.versionCode = field 3.
        app_details = find_path(resp.content, 1, 2, 4, 13, 1)
        if not isinstance(app_details, (bytes, bytearray)):
            raise PlayAuthError(f"/details: AppDetails missing for {package_name}")
        vc = get_int(bytes(app_details), 3)
        if not vc:
            raise PlayAuthError(f"/details: versionCode missing for {package_name}")
        return vc

    def _fetch_delivery_token(self, package_name: str, version_code: int) -> str:
        """``POST /fdfe/purchase`` — get the encoded delivery token (free apps)."""
        url = f"{_PLAY_BASE}/fdfe/purchase"
        headers = {**self._fdfe_headers(), "Content-Length": "0"}
        resp = self._http.post(
            url,
            params={"ot": "1", "doc": package_name, "vc": str(version_code)},
            headers=headers,
        )
        if resp.status_code != 200:
            raise PlayAuthError(
                f"/purchase returned HTTP {resp.status_code} for {package_name} vc={version_code}"
            )
        # ResponseWrapper(1).payload(2).buyResponse(4).encodedDeliveryToken(55)
        buy_response = find_path(resp.content, 1, 2, 4)
        if not isinstance(buy_response, (bytes, bytearray)):
            raise PlayAuthError("/purchase: buyResponse missing")
        token = get_string(bytes(buy_response), 55)
        if not token:
            raise PlayAuthError(
                f"/purchase: encodedDeliveryToken missing for {package_name}. "
                "App may be paid (this client only handles free apps) or "
                "unavailable on your account."
            )
        return token

    def _fetch_delivery(
        self, package_name: str, version_code: int, delivery_token: str
    ) -> PlayDownloadInfo:
        """``GET /fdfe/delivery`` — get the signed CDN URL + size."""
        url = f"{_PLAY_BASE}/fdfe/delivery"
        resp = self._http.get(
            url,
            params={
                "ot": "1",
                "doc": package_name,
                "vc": str(version_code),
                "dtok": delivery_token,
            },
            headers=self._fdfe_headers(),
        )
        if resp.status_code != 200:
            raise PlayAuthError(
                f"/delivery returned HTTP {resp.status_code} for {package_name} "
                f"vc={version_code} (app not downloadable or invalid token)"
            )
        # ResponseWrapper(1).payload(2).deliveryResponse(21).appDeliveryData(2)
        delivery_response = find_path(resp.content, 1, 2, 21)
        if not isinstance(delivery_response, (bytes, bytearray)):
            raise PlayAuthError("/delivery: deliveryResponse missing")
        delivery_status = get_int(bytes(delivery_response), 1)
        app_delivery = find_field(bytes(delivery_response), 2)
        if not isinstance(app_delivery, (bytes, bytearray)):
            raise PlayAuthError(
                f"/delivery: status={delivery_status} but no AppDeliveryData "
                "(likely device/geo/account incompatibility)"
            )
        return _parse_app_delivery_data(bytes(app_delivery), package_name, version_code)


# ─── AppDeliveryData decoding ──────────────────────────────────────────────


def _parse_app_delivery_data(
    data: bytes, package_name: str, version_code: int
) -> PlayDownloadInfo:
    """Walk an AppDeliveryData buffer and pull URL + size + splits + extras."""
    # AndroidAppDeliveryData fields:
    #   downloadSize = 1 (int64)
    #   downloadUrl = 3 (string)
    #   additionalFile = 4 (repeated AppFileMetadata)
    #   splitDeliveryData = 15 (repeated SplitDeliveryData)
    base_size = get_int(data, 1)
    base_url = get_string(data, 3)
    if not base_url:
        raise PlayAuthError(f"/delivery: downloadUrl missing for {package_name}")

    splits: list[SplitInfo] = []
    for split_blob in find_all_fields(data, 15):
        if not isinstance(split_blob, (bytes, bytearray)):
            continue
        # SplitDeliveryData: name=1, downloadSize=2, downloadUrl=5
        name = get_string(bytes(split_blob), 1)
        size = get_int(bytes(split_blob), 2)
        url = get_string(bytes(split_blob), 5)
        if name and url:
            splits.append(SplitInfo(name=name, url=url, size=size))

    additional: list[AdditionalFile] = []
    for file_blob in find_all_fields(data, 4):
        if not isinstance(file_blob, (bytes, bytearray)):
            continue
        # AppFileMetadata: fileType=1, versionCode=2, size=3, downloadUrl=4
        file_type = get_int(bytes(file_blob), 1)
        file_vc = get_int(bytes(file_blob), 2)
        size = get_int(bytes(file_blob), 3)
        url = get_string(bytes(file_blob), 4)
        if not url:
            continue
        prefix = "patch" if file_type else "main"
        additional.append(
            AdditionalFile(
                name=f"{prefix}.{file_vc}.{package_name}.obb",
                url=url,
                size=size,
            )
        )

    return PlayDownloadInfo(
        package_name=package_name,
        version_code=version_code,
        base_url=base_url,
        base_size=base_size,
        splits=splits,
        additional_files=additional,
    )


# ─── Helpers exposed for tests / external decoders ─────────────────────────


def decode_app_delivery_data(data: bytes) -> dict[str, object]:
    """Return a dict view of AppDeliveryData — useful for tests.

    Not used by the production path; the typed dataclasses above are.
    """
    return {
        "download_size": get_int(data, 1),
        "download_url": get_string(data, 3),
        "additional_files": [
            {
                "file_type": get_int(bytes(b), 1),
                "version_code": get_int(bytes(b), 2),
                "size": get_int(bytes(b), 3),
                "download_url": get_string(bytes(b), 4),
            }
            for b in find_all_fields(data, 4)
            if isinstance(b, (bytes, bytearray))
        ],
        "splits": [
            {
                "name": get_string(bytes(b), 1),
                "size": get_int(bytes(b), 2),
                "download_url": get_string(bytes(b), 5),
            }
            for b in find_all_fields(data, 15)
            if isinstance(b, (bytes, bytearray))
        ],
    }


__all__ = [
    "AdditionalFile",
    "PlayAuthError",
    "PlayClient",
    "PlayCredentials",
    "PlayDownloadInfo",
    "SplitInfo",
    "decode_app_delivery_data",
]
