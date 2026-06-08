# Capturing mobile traffic with Moxy

[Moxy](https://github.com/matank001/Moxy) is an open-source MITM proxy + web UI
built on top of [mitmproxy](https://mitmproxy.org/). It does the same job as
Burp Suite or Caido for HTTP/HTTPS interception, but free, scriptable from a
browser, and orchestrable from Docker. The MedusaNexus installer wires it up
end-to-end: boot the container, scrape the CA out of it, push it to a
connected device via `adb`, and persist the right env vars so `mnexus doctor`
and the web UI know where it lives.

---

## One-shot setup

```bash
./scripts/setup.sh --moxy
```

What it does, in order:

1. Verifies the Docker daemon is reachable.
2. Removes any existing `moxy` container (volume on the host survives —
   nothing you saved in the Moxy UI is lost).
3. Runs `ghcr.io/matank001/moxy:latest` with the `projects_data` volume
   mounted under `~/.mnexus/tools/moxy/projects_data` so state lives outside
   the repo.
4. Polls the UI on `http://localhost:5000` until it answers (60s budget).
5. `docker cp`s the mitmproxy CA out of the container into
   `~/.mnexus/tools/moxy/moxy-ca.cer`. Falls back to a filesystem scan
   inside the container if upstream moves the file.
6. Detects the host's LAN IP (`en0..en5` on macOS, default-route src on
   Linux). That's the address the **device** has to point at — not
   `localhost`.
7. If a single `adb` device is connected and `MOXY_PUSH_TO_DEVICE` isn't
   `0`, copies the CA to `/sdcard/Download/moxy-ca.cer` so the user can
   install it from **Settings → Security** in three taps.
8. Writes the following into `~/.mnexus/env.sh` (idempotent):

   ```sh
   export MNEXUS_MOXY_URL=http://localhost:5000
   export MNEXUS_MOXY_PROXY_HOST=192.168.x.y     # your LAN IP
   export MNEXUS_MOXY_PROXY_PORT=8081
   export MNEXUS_MOXY_CA_PATH=/Users/.../moxy-ca.cer
   ```

9. Prints device-side instructions with the resolved IP/port already
   substituted.

Re-source and verify:

```bash
source ~/.mnexus/env.sh
mnexus doctor
```

### Custom ports

If 5000 or 8081 is already taken (Flask dev servers love to squat on 5000
under macOS Sonoma+ because AirPlay Receiver does too):

```bash
MOXY_UI_PORT=5001 MOXY_PROXY_PORT=8082 ./scripts/setup.sh --moxy
```

The env file picks up whatever you pass. The device-side instructions printed
at the end will reflect it.

### Skip the adb push

```bash
MOXY_PUSH_TO_DEVICE=0 ./scripts/setup.sh --moxy
```

Useful when the connected device isn't the one you actually want to test, or
when you'd rather AirDrop the cert by hand.

---

## Device-side: pointing the phone at Moxy

After `--moxy` finishes you'll have the UI on `http://localhost:5000` and a
CA at `~/.mnexus/tools/moxy/moxy-ca.cer`. On the phone:

### 1. Configure the Wi-Fi proxy

> The phone and the Mac must be on the **same Wi-Fi**. Loopback isn't a
> destination — the phone has to reach `MNEXUS_MOXY_PROXY_HOST` over the
> network.

**Android**: Settings → Wi-Fi → long-press the connected SSID → *Modify
network* → *Advanced options*:

- **Proxy**: `Manual`
- **Hostname**: the LAN IP printed by `--moxy` (e.g. `192.168.0.8`)
- **Port**: `8081` (or whatever `MOXY_PROXY_PORT` resolved to)

Hit *Save*.

### 2. Install the CA

If `--moxy` was able to `adb push` the cert, it's already at
`/sdcard/Download/moxy-ca.cer`. Otherwise, push it manually:

```bash
adb push ~/.mnexus/tools/moxy/moxy-ca.cer /sdcard/Download/moxy-ca.cer
```

On the phone:

**Settings → Security → Encryption & credentials → Install a certificate →
CA certificate** → confirm → pick `moxy-ca.cer` from Downloads → name it
`moxy`.

### 3. Smoke test

Open the phone's browser at `http://example.com` and `https://example.com`.
Both should load without warnings. They'll show up in the Moxy UI at
`http://localhost:5000` (or `:5001` if you remapped) as full
request + response pairs.

---

## Targeting an installed app

The browser test only proves the cert is trusted. Real-world apps add two
extra hurdles:

### Hurdle 1 — Network Security Config

Since Android 7 (Nougat), apps **do not** trust user-installed CAs unless their
`network_security_config.xml` explicitly opts in. Almost no production app
does.

Symptom: browser works, the target app gets `SSLHandshakeException` and
fails to talk to the network. Nothing in Moxy.

Three ways out:

| Approach              | When to use                                                       |
|-----------------------|-------------------------------------------------------------------|
| **Magisk module** *AlwaysTrustUserCerts* | Rooted device or emulator. Reboot → user CAs become system CAs automatically. Cleanest. |
| **Patch the APK**     | Non-rooted device. Pipe the APK through Stheno (`network_security_config_user_trust` patch), reinstall, retry. |
| **System CA install** | Rooted but no Magisk. Hash the cert (`openssl x509 -inform PEM -subject_hash_old`), drop into `/system/etc/security/cacerts/`, `chmod 644`, reboot. Android 14+ may need a Magisk overlay anyway. |

### Hurdle 2 — Certificate pinning

Even with the cert in the system store, pinned apps will refuse to talk to
mitmproxy. Symptom in Moxy: only `CONNECT host:443 → tunnel established`
entries, no headers/bodies.

That's not a Moxy problem — it's the app being well-engineered. Bypass with
Frida + a pin-bypass recipe:

```bash
# 1. Push frida-server matching the device ABI (one-time)
./scripts/setup.sh --device

# 2. Pick a recipe from the Nexus Recipes panel (categories: SSL / RESILIENCE)
#    e.g. pinning_universal (Android), ios_ssl_kill_switch (iOS).

# 3. Spawn the app with the recipe attached
frida -U -f com.target.app \
      -l ~/.mnexus/tools/medusa/modules/SSL/pinning_universal.med \
      --no-pause
```

Once the dynamic flow lands in the Nexus UI, hit **Dynamic → load recipe →
RUN** to do the same from the browser.

---

## Common pitfalls

### "No response available" — intercept mode is on

Moxy has two modes, easy to confuse:

- **Passive capture** (default workflow): every request flows through
  immediately and you see request + response pairs as they happen.
- **Intercept mode**: every request **pauses** until you click `Forward` or
  `Drop`. Until then, the upstream never sees the request → no response →
  the right pane reads "No response available".

If the toggle at the top of the UI shows **`Intercept ✅ N`** (with a counter
of queued requests), that's why. Click it to turn it off, and either let the
queue drain by clicking `Forward` repeatedly or `Clear All` and re-trigger
the action on the phone.

Use intercept mode only when you want to **modify** a specific request in
transit — click the row, `Edit`, change headers/body, then `Forward`.

### Phone times out before any request hits Moxy

The proxy never receives the connection.

1. **Wi-Fi client isolation.** Most corporate / guest networks block
   station-to-station traffic. Verify by opening `http://<LAN_IP>:5000`
   from the phone's browser (no proxy needed) — if that times out too,
   the phone literally can't reach the Mac on this network. Switch to a
   personal hotspot or a home network.
2. **macOS Application Firewall.** Even with the right network, the firewall
   can drop inbound on the Docker-bound port:

   ```bash
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
   ```

   If enabled, allow Docker / OrbStack in *System Settings → Network →
   Firewall → Options*, or disable temporarily.
3. **Wrong interface.** If the Mac is on Ethernet **and** Wi-Fi, the LAN IP
   might point at an interface the phone can't reach. `route get
   <LAN_IP>` shows which interface it leaves through.

### `curl: (60) SSL certificate problem` from the Mac itself

Not a bug — proof the proxy works. Curl on the Mac doesn't trust the
mitmproxy CA, so it correctly rejects the intercepted TLS. To make `curl`
trust it from your shell:

```bash
curl --cacert ~/.mnexus/tools/moxy/moxy-ca.cer -x http://localhost:8081 \
     https://example.com
```

…or pipe through `-k` (insecure mode) just to confirm reachability.

### `mnexus doctor` says `moxy MISSING`

Re-source the env file in the current shell:

```bash
source ~/.mnexus/env.sh
mnexus doctor
```

`scripts/setup.sh --moxy` only writes the file — it can't mutate your shell's
environment.

---

## Pre-loading Moxy with the APK's endpoints

After a static scan, the Nexus exporter can emit a Moxy ruleset YAML listing
every endpoint discovered in the APK (manifest deep links + static URL
constants + dynamic captures from previous runs). Import it into a Moxy
project so its agentic flows have an attack surface to work from before any
organic traffic happens:

```bash
mnexus
> /use PRJ-A1B2C3D4
> /export moxy
✓ wrote ./moxy.yml — 47 endpoints from the APK
```

Or click **`[ MOXY .yml ]`** in the Overview/Network exports panel of the web
UI. Either way you get a ruleset Moxy understands; load it via the project
import flow in the UI.

---

## TL;DR

```text
./scripts/setup.sh --moxy                 # one shot: docker + CA + adb push
source ~/.mnexus/env.sh && mnexus doctor  # confirm

phone Wi-Fi proxy   → <LAN_IP>:8081
phone install CA    → Settings → Security → Install certificate
Moxy UI             → http://localhost:5000   (Intercept OFF for passive capture)
target app fails    → Stheno patch (user-trust) or Frida pin bypass
```

If something fails, the diagnosis tree is:

```text
phone browser http://example.com works?
├─ no  → LAN routing / firewall / Wi-Fi isolation
└─ yes → phone browser https://example.com works without warning?
         ├─ no  → CA not installed (or wrong slot)
         └─ yes → target app works?
                  ├─ no, network error          → Network Security Config — patch APK or Magisk
                  └─ no, only CONNECT in Moxy   → certificate pinning — Frida recipe
```
