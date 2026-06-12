//! Device detection: two independent watchers, one registry, one event.
//!
//! ```text
//! adb host:track-devices ─┐
//!                         ├─→ Registry ─→ emit "devices://changed" ─→ React
//! usbmux Listen ──────────┘
//! ```

pub mod android;
pub mod ios;
pub mod model;

use std::collections::HashMap;
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager};

use model::{Device, Platform};

/// Managed Tauri state: serial/udid → Device, merged across both watchers.
#[derive(Default)]
pub struct Registry(pub Mutex<HashMap<String, Device>>);

pub fn start_watchers(app: AppHandle) {
    app.manage(Registry::default());

    let android_app = app.clone();
    tauri::async_runtime::spawn(async move { android::watch(android_app).await });

    let ios_app = app.clone();
    tauri::async_runtime::spawn(async move { ios::watch(ios_app).await });
}

/// Replace the slice owned by one platform with a fresh listing, then emit.
/// Each watcher is authoritative only for its own platform — they never race
/// over each other's entries.
pub fn replace_platform(app: &AppHandle, platform: Platform, devices: Vec<Device>) {
    {
        let registry = app.state::<Registry>();
        let mut map = registry.0.lock().expect("device registry poisoned");
        map.retain(|_, d| d.platform != platform);
        for d in devices {
            map.insert(d.id.clone(), d);
        }
    }
    emit_changed(app);
}

pub fn snapshot(app: &AppHandle) -> Vec<Device> {
    app.state::<Registry>()
        .0
        .lock()
        .expect("device registry poisoned")
        .values()
        .cloned()
        .collect()
}

fn emit_changed(app: &AppHandle) {
    let _ = app.emit("devices://changed", snapshot(app));
}
