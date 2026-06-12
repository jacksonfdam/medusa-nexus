"""PyInstaller entry point for the host-side mnexus sidecar.

Tauri's Rust core spawns this frozen binary and talks to it over the local
FastAPI port (NOT 8000 — MobSF owns 8000 in the compose stack). Everything
device-facing lives here on the host: adb/usbmux bridges, frida, tart, proxies.
"""

from __future__ import annotations

import os

import uvicorn

# Dedicated port — keep it off MobSF's 8000. The Rust core reads the same value.
PORT = int(os.environ.get("MNEXUS_API_PORT", "8765"))


def main() -> None:
    uvicorn.run("mnexus.api.main:app", host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
