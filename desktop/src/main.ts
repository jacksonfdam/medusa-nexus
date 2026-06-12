// Placeholder wiring: prove the Rust↔frontend channel works before the real
// .pen-derived UI lands. Subscribes to the two boot event streams and renders
// the live device list.
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type Platform = "android" | "ios";
type DeviceState = "online" | "unauthorized" | "untrusted" | "offline";

interface Device {
  id: string;
  platform: Platform;
  name: string;
  state: DeviceState;
  jailbroken: boolean | null;
  source: string;
}

function renderDevices(devices: Device[]): void {
  const list = document.getElementById("devices");
  if (!list) return;
  if (devices.length === 0) {
    list.innerHTML = "<li>no devices — plug one in and authorize</li>";
    return;
  }
  list.innerHTML = devices
    .map((d) => `<li>[${d.platform}] ${d.name} — ${d.state} (${d.source})</li>`)
    .join("");
}

function renderStatus(status: string): void {
  const el = document.getElementById("stack-status");
  if (el) el.textContent = `stack: ${status}`;
}

async function main(): Promise<void> {
  await listen<string>("stack://status", (e) => renderStatus(e.payload));
  await listen<Device[]>("devices://changed", (e) => renderDevices(e.payload));

  // Pull the current snapshot in case events fired before we subscribed.
  try {
    renderDevices(await invoke<Device[]>("devices_snapshot"));
  } catch (err) {
    console.error("devices_snapshot failed", err);
  }
}

void main();
