//! Platform-agnostic device model the UI consumes. Android (adb) and iOS
//! (usbmux) feed the same struct; `platform` + `state` carry the difference.

use serde::Serialize;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Device {
    pub id: String,
    pub platform: Platform,
    pub name: String,
    pub state: DeviceState,
    /// `None` until the jailbreak/root probe runs — detection never infers it.
    pub jailbroken: Option<bool>,
    /// Which binary touched the device: "bundled" (our adb) or "host".
    pub source: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Platform {
    Android,
    Ios,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum DeviceState {
    /// adb `device` / iOS trusted + reachable.
    Online,
    /// adb saw it but the RSA prompt isn't accepted yet.
    Unauthorized,
    /// usbmux sees the iPhone but "Trust This Computer" is pending.
    Untrusted,
    Offline,
}
