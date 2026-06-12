//! Host-side mnexus core, spawned as a frozen sidecar.
//!
//! This process owns everything that must touch the host: USB device bridges,
//! frida, tart/vphone, the proxies, and the SQLite store. It serves FastAPI on
//! :8765 (off MobSF's :8000). We hand it the shim paths so its binary engines
//! transparently run inside the ghidra-tools container.

use std::fs;
use std::path::Path;

use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

const API_PORT: &str = "8765";

pub async fn spawn(app: &AppHandle) -> anyhow::Result<()> {
    let res = app.path().resource_dir()?;
    let shims = res.join("shims");
    ensure_executable(&shims);

    let jadx = shims.join("jadx-docker");
    let apktool = shims.join("apktool-docker");
    let ghidra_home = shims.join("ghidra-home");

    let cmd = app
        .shell()
        .sidecar("mnexus-server")?
        .env("MNEXUS_API_PORT", API_PORT)
        // Dependency services live in the Docker stack.
        .env("MNEXUS_MOBSF_URL", "http://localhost:8000")
        .env("MNEXUS_MOXY_URL", "http://localhost:5000")
        // Binary engines route through the containerised-tool shims.
        .env("MNEXUS_JADX_PATH", path_str(&jadx))
        .env("MNEXUS_APKTOOL_PATH", path_str(&apktool))
        .env("MNEXUS_GHIDRA_PATH", path_str(&ghidra_home));

    let (mut rx, _child) = cmd.spawn()?;
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    log::info!("[mnexus] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!("[mnexus] sidecar exited: {:?}", payload.code);
                }
                _ => {}
            }
        }
    });

    Ok(())
}

fn path_str(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

/// Resource extraction can drop the executable bit. The shims are bash scripts
/// the sidecar must be able to exec, so re-assert +x on Unix.
fn ensure_executable(shims: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let scripts = [
            shims.join("_docker_tool.sh"),
            shims.join("jadx-docker"),
            shims.join("apktool-docker"),
            shims.join("ghidra-home/support/analyzeHeadless"),
        ];
        for s in scripts {
            if let Ok(meta) = fs::metadata(&s) {
                let mut perms = meta.permissions();
                perms.set_mode(0o755);
                let _ = fs::set_permissions(&s, perms);
            }
        }
    }
    #[cfg(not(unix))]
    let _ = shims;
}
