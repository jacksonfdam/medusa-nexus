// MedusaNexus desktop — thin shim. All wiring lives in the lib so
// tauri::generate_context! has a stable crate to bind to.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    medusa_nexus_desktop_lib::run();
}
