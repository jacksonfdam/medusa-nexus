//! MedusaNexus desktop shell.
//!
//! The Rust core is a maestro, not the brain. Boot sequence, in order:
//!   1. `stack::up`      — `docker compose up -d` the dependency services + health-gate
//!   2. `sidecar::spawn` — launch the frozen mnexus host core (device/frida/tart/DB)
//!   3. `device::start_watchers` — adb + usbmux → one `devices://changed` stream
//!
//! Heavy analysis lives in the sidecar (host) and the Docker stack. This binary
//! only orchestrates and bridges USB. See ../../../docs-site for the why.

mod commands;
mod device;
mod sidecar;
mod stack;

use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            commands::devices_snapshot,
            commands::stack_status,
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            // Boot off the UI thread; the window paints immediately and the
            // frontend reacts to stack:// and devices:// events as they fire.
            tauri::async_runtime::spawn(async move {
                if let Err(err) = boot(handle).await {
                    log::error!("boot sequence failed: {err:#}");
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("fatal: MedusaNexus shell crashed on launch");
}

async fn boot(app: tauri::AppHandle) -> anyhow::Result<()> {
    stack::up(&app).await?;
    sidecar::spawn(&app).await?;
    device::start_watchers(app);
    Ok(())
}
