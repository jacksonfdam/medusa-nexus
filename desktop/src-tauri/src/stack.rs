//! Docker dependency-stack lifecycle.
//!
//! We shell out to the `docker` CLI rather than pull in a Docker-API crate:
//! `docker compose` is the contract, and the user needs the CLI present anyway.
//! Status is pushed to the UI on `stack://status` so the boot screen can narrate.

use std::path::PathBuf;

use tauri::{AppHandle, Emitter, Manager};
use tokio::process::Command;
use tokio::time::{sleep, Duration};

const HEALTH_CONTAINER: &str = "mnexus-mobsf";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(180);

fn compose_file(app: &AppHandle) -> anyhow::Result<PathBuf> {
    let res = app.path().resource_dir()?;
    Ok(res.join("stack/docker-compose.yml"))
}

async fn docker_available() -> bool {
    Command::new("docker")
        .arg("info")
        .output()
        .await
        .map(|o| o.status.success())
        .unwrap_or(false)
}

pub async fn up(app: &AppHandle) -> anyhow::Result<()> {
    if !docker_available().await {
        let _ = app.emit("stack://status", "docker-unavailable");
        anyhow::bail!("Docker is not running — start Docker Desktop and relaunch");
    }

    let compose = compose_file(app)?;
    let _ = app.emit("stack://status", "starting");

    let status = Command::new("docker")
        .args(["compose", "-f"])
        .arg(&compose)
        .args(["up", "-d"])
        .status()
        .await?;
    anyhow::ensure!(status.success(), "`docker compose up` failed");

    wait_healthy(app).await?;
    let _ = app.emit("stack://status", "ready");
    Ok(())
}

/// Poll the MobSF container's health until it reports healthy or we time out.
/// The ghidra-tools container has no healthcheck (it's `sleep infinity`), so
/// MobSF is our readiness proxy for "the stack is up".
async fn wait_healthy(app: &AppHandle) -> anyhow::Result<()> {
    let _ = app.emit("stack://status", "waiting-health");
    let mut waited = Duration::ZERO;
    let step = Duration::from_secs(3);

    while waited < HEALTH_TIMEOUT {
        let out = Command::new("docker")
            .args([
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                HEALTH_CONTAINER,
            ])
            .output()
            .await?;
        let state = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if state == "healthy" || state == "running" {
            return Ok(());
        }
        sleep(step).await;
        waited += step;
    }
    anyhow::bail!("stack did not become healthy within {}s", HEALTH_TIMEOUT.as_secs())
}
