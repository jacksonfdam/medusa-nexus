//! iOS watcher — usbmux `Listen` (the iOS equivalent of adb track-devices):
//! connect the usbmux socket, send a `{ MessageType: "Listen" }` plist, and the
//! daemon pushes `Attached` / `Detached` packets as devices come and go.
//!
//! STUB. Wire the pure-Rust `idevice` crate here (`UsbmuxdConnection::listen`),
//! map Attached→Online/Untrusted and Detached→remove, then call
//! `replace_platform(app, Platform::Ios, …)`. Socket locations:
//!   • macOS   — unix `/var/run/usbmuxd`
//!   • Windows — tcp `127.0.0.1:27015` (ships with Apple Mobile Device Support)
//!   • Linux   — unix, needs the `usbmuxd` package
//!
//! Until wired, iOS devices won't appear; Android detection is unaffected.

use tauri::AppHandle;
use tokio::time::{sleep, Duration};

pub async fn watch(_app: AppHandle) {
    loop {
        log::debug!("ios usbmux watcher not yet wired — see device/ios.rs");
        sleep(Duration::from_secs(60)).await;
    }
}
