//! Tauri commands the frontend invokes. Events (`devices://changed`,
//! `stack://status`) are the push channel; these are the pull/snapshot side.

use tauri::AppHandle;

use crate::device::{self, model::Device};

/// Current device list — used on mount before the first `devices://changed`.
#[tauri::command]
pub fn devices_snapshot(app: AppHandle) -> Vec<Device> {
    device::snapshot(&app)
}

/// Placeholder readiness probe. The authoritative signal is the `stack://status`
/// event stream emitted during boot; this lets the UI re-query on demand.
#[tauri::command]
pub fn stack_status() -> String {
    "unknown".to_string()
}
