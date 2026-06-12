//! Android watcher — speaks the adb wire protocol directly to the server on
//! :5037. `host:track-devices` keeps the socket open and pushes the full device
//! list on every plug/unplug. No polling, no extra crate.
//!
//! adb wire format: 4 hex digits of payload length, then the payload. Responses
//! start with `OKAY` / `FAIL`.

use tauri::AppHandle;
use tauri_plugin_shell::ShellExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::time::{sleep, Duration};

use super::model::{Device, DeviceState, Platform};
use super::replace_platform;

const ADB_SERVER: &str = "127.0.0.1:5037";

pub async fn watch(app: AppHandle) {
    loop {
        if let Err(err) = track(&app).await {
            log::warn!("adb track-devices ended ({err:#}); (re)starting server");
            // Bring up our bundled adb server (-a so the docker VM can reach it).
            if let Ok(cmd) = app.shell().sidecar("adb") {
                let _ = cmd.args(["-a", "-P", "5037", "start-server"]).output().await;
            }
            sleep(Duration::from_secs(3)).await;
        }
    }
}

async fn track(app: &AppHandle) -> anyhow::Result<()> {
    let mut stream = TcpStream::connect(ADB_SERVER).await?;
    send(&mut stream, "host:track-devices").await?;

    let mut status = [0u8; 4];
    stream.read_exact(&mut status).await?;
    anyhow::ensure!(&status == b"OKAY", "adb refused track-devices");

    loop {
        let mut len_hex = [0u8; 4];
        stream.read_exact(&mut len_hex).await?;
        let len = usize::from_str_radix(std::str::from_utf8(&len_hex)?, 16)?;

        let mut buf = vec![0u8; len];
        stream.read_exact(&mut buf).await?;
        let listing = String::from_utf8_lossy(&buf);

        replace_platform(app, Platform::Android, parse_listing(&listing));
    }
}

async fn send(stream: &mut TcpStream, cmd: &str) -> anyhow::Result<()> {
    stream
        .write_all(format!("{:04x}{}", cmd.len(), cmd).as_bytes())
        .await?;
    Ok(())
}

/// Each line: `<serial>\t<state>`. An empty payload means "no devices".
fn parse_listing(listing: &str) -> Vec<Device> {
    listing
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|line| {
            let mut parts = line.split('\t');
            let serial = parts.next()?.trim().to_string();
            let state = match parts.next().unwrap_or("offline").trim() {
                "device" => DeviceState::Online,
                "unauthorized" => DeviceState::Unauthorized,
                _ => DeviceState::Offline,
            };
            Some(Device {
                id: serial.clone(),
                platform: Platform::Android,
                name: serial,
                state,
                jailbroken: None,
                source: "bundled".to_string(),
            })
        })
        .collect()
}
