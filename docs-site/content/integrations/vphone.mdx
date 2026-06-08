# 🔱 MEDUSA NEXUS — VPhone (super-tart-vphone) Integration Plan

*A real iOS VM, owned by you, locally — without a jailbroken phone in the drawer.*

This plan covers integrating [`wh1te4ever/super-tart-vphone`](https://github.com/wh1te4ever/super-tart-vphone)
into Medusa Nexus as a first-class iOS *device* — alongside (or instead of)
physical iPhones connected via libimobiledevice.

---

## 1. What super-tart-vphone is

It's a fork of [Tart](https://tart.run) (CirrusLabs' Apple Silicon VM tool)
that boots **real iOS** in a virtual machine on an M-series Mac, built on
Apple's undocumented `vphone600ap` / `vresearch101ap` platform discovered
inside Apple's Private Cloud Compute (cloudOS 26) firmware.

Capability headlines:

| Feature                  | Detail                                                        |
|--------------------------|---------------------------------------------------------------|
| **Full boot chain**      | bootrom (custom AVPBooter) → iBSS/iBEC → kernel → SpringBoard.|
| **Apps run normally**    | App Store apps (re-signed) install + launch with Metal GPU.   |
| **SSH access**           | Built-in Dropbear at `localhost:2222` (`root:alpine`).        |
| **VNC desktop**          | TrollVNC mirror over the VM, scriptable input.                |
| **GDB on the kernel**    | Debugger attaches at `localhost:8000`.                        |
| **SEP debugger**         | Secure Enclave at `localhost:8001`.                           |
| **DFU mode**             | First-class — drop into DFU from the host.                    |
| **Snapshots**            | Tart's image format — fork a known-good VM in seconds.        |

For Medusa Nexus this is a *lab device*: SSH already enabled, sandbox
disabled, no signature verification, fully introspectable. Frida runs
without gadget injection. Burp routes through the host. Reverse engineering
is comfortable instead of acrobatic.

---

## 2. Honest caveats

**This is research-grade software.** The README states it plainly:
> "This is not for end-user, really messing/dirty project and most of things
> are hardcoded patch. Really not appropriate for end-user."

Four things make this deeply opt-in:

1. **Apple Silicon only**, macOS 15.7.4 (Sequoia) or 26.3 (Tahoe) or newer.
2. **SIP and AMFI must be disabled** + `csrutil allow-research-guests enable`.
   That's a fundamental host-security tradeoff — set up a dedicated lab Mac.
3. **Manual firmware patching is mandatory** the first time:
   bootrom (AVPBooter) → iBSS/iBEC → LLB → TXM → kernelcache, with
   hand-tuned offsets that depend on the exact build of cloudOS 26 you
   extract. The GUIDE.md is, quote, "incomplete".
4. **Apple firmware redistribution is forbidden** — you have to pull
   cloudOS 26.x and iOS 26.1 (build 23B85) firmware yourself, patch it
   yourself, and never share the patched IPSW.

Conclusion: **we will not attempt to automate the firmware patching path.**
That's where things break for the GUIDE author and that's where they would
break for us. Our integration assumes the user has *already* booted a vphone
VM (or wants to walk through the GUIDE manually) and gives them everything
to *use* it productively from Medusa Nexus.

---

## 3. What we automate (and what we don't)

| Step                                              | Auto?      | Notes |
|---------------------------------------------------|------------|-------|
| Apple Silicon + macOS version check               | ✅ yes     | `scripts/setup-vphone.sh` doctor.|
| SIP / AMFI / csrutil status check                 | ✅ yes     | Read-only — abort with clear hint if not disabled.|
| `git clone` super-tart-vphone + writeup           | ✅ yes     | Into `~/.mnexus/tools/vphone/`.|
| `swift build -c release`                          | ✅ yes     | Caches a writable binary symlink.|
| Write `MNEXUS_VPHONE_PATH` to `~/.mnexus/env.sh`  | ✅ yes     | Same pattern as adb/jadx/ghidra paths.|
| Cache cloudOS / iOS firmware                      | ❌ no      | User owns the legal + storage burden.|
| Patch bootrom / kernel / iBoot / TXM              | ❌ no      | Hand-tuned, build-dependent. GUIDE handles it.|
| Restore patched IPSW via idevicerestore           | ❌ no      | Manual — first-boot only.|
| Cryptex injection over SSH ramdisk                | ❌ no      | Manual — first-boot only.|
| **From a running VM** — list, status, ssh, files  | ✅ yes     | `VPhoneEngine`.|
| Frida attach (host:port, no gadget)               | ✅ yes     | Recipes work as-is over `frida -H 127.0.0.1:27042`.|
| Push `frida-server` to the VM                     | ✅ yes     | One-liner SSH bootstrap recipe.|
| Burp routing                                      | ✅ yes     | VM proxies through host's loopback.|

The line is sharp: **anything that requires Apple firmware bytes ≠
automated**. **Anything that talks to a running VM = automated**.

---

## 4. Architecture

### 4.1 Engine: `VPhoneEngine`

Same shape as `IDeviceEngine` from Wave 2 of the iOS plan, with `tart` as
the transport instead of libimobiledevice.

```python
class VPhoneEngine(BaseEngine):
    name = "vphone"
    capabilities = ["vm_lifecycle", "ssh", "scp", "frida", "gdb", "vnc"]

    async def health_check() -> EngineStatus  # checks tart + super-tart bin
    async def list_vms() -> list[dict]         # tart list -> [{name, state}]
    async def vm_info(name) -> dict            # parsed from tart status
    async def start(name)                      # tart run --serial --gdb 8000 ...
    async def stop(name)
    async def ssh(name, cmd) -> str            # uses ssh -p 2222 root@127.0.0.1
    async def push(name, local, remote)        # scp
    async def pull(name, remote, local)        # scp
    async def install_ipa(name, ipa_path)      # scp + ldid + chmod + uicache
    async def screenshot(name) -> bytes        # via TrollVNC frame grab
```

Lives at `mnexus/engines/vphone_engine.py`. Registered in
`MedusaNexus._register_engines()`. Doctor table picks it up next to ADB and
the existing engines.

### 4.2 API surface: `/v1/vphones/*`

Mirrors the existing multi-device shape so the frontend's device dropdown
can list ADB serials, libimobiledevice UDIDs, and VPhone names side by
side without caring about the transport.

```
GET    /v1/vphones                       # list VMs
GET    /v1/vphones/{name}                # one VM's status + ports + transport
POST   /v1/vphones/{name}/start
POST   /v1/vphones/{name}/stop
POST   /v1/vphones/{name}/ssh            # one-shot ssh exec; recorded in adb log
POST   /v1/vphones/{name}/install        # IPA upload → scp → ldid -S → uicache
GET    /v1/vphones/{name}/file?path=     # scp pull
POST   /v1/vphones/{name}/file/upload    # scp push
GET    /v1/vphones/{name}/screenshot     # VNC frame -> PNG
```

Every command goes through the existing `_adb` audit-log wrapper (renamed
internally to `_run_recorded`) so the ADB Control Panel's "Command Log"
also surfaces vphone calls — same pane, same UI, different `transport`
column value (`vphone` vs `adb` vs `idevice`).

### 4.3 Frontend

- **Device Control Panel dropdown** gets a third group: `VPHONES`.
- **Per-VM tab** at `#/vphone/{name}` with sub-tabs INFO / SSH / FILES /
  SCREEN / FRIDA / GDB. The first four reuse the components already built
  for the ADB tabs; FRIDA opens an attach-by-host action; GDB exposes the
  port + a one-liner copy-to-clipboard.
- **Project workspace integration**: when a project has `platform=ios` and
  a vphone is selected, the existing DYNAMIC tab's "START SESSION" button
  routes to the VPhone instead of the not-yet-existing physical-device
  Frida path.

### 4.4 CLI

REPL slash commands:

```
/vphone                # list VMs (alias /vphones)
/vphone start <name>
/vphone stop <name>
/vphone ssh <name> -- <cmd…>
/vphone install <name> <ipa>
/vphone screenshot <name>
/vphone bootstrap <name>     # push frida-server, common scripts
```

Flat subcommand: `mnexus vphone <verb> ...`.

### 4.5 Recipes

A built-in `vphone_bootstrap` recipe — not a Frida script, an SSH
script — that:
1. Checks for `frida-server` at `/usr/sbin/frida-server`.
2. If missing, scp's a known-good ARM64 `frida-server` into place.
3. Pushes a launchd plist that auto-starts it on next boot.
4. Starts it manually for the current session.

Side effect: any iOS recipe that previously needed a jailbroken physical
device now Just Works against a vphone VM.

---

## 5. Phasing

**Wave 1 — Setup automation + doctor.** Ships immediately as the script
the user asked for. Idempotent. No firmware steps automated; clear
escalation to the GUIDE for those.

**Wave 2 — Engine + API.** `VPhoneEngine` + `/v1/vphones/*` endpoints +
audit-log integration.

**Wave 3 — UI.** Device dropdown + per-VM tabs + recipe surfacing.

**Wave 4 — Project workspace integration.** DYNAMIC tab routes through
selected vphone. Recipes filter by VM availability.

Each wave is independently shippable. Wave 1 alone is enough for a power
user to clone, build, and use super-tart from the CLI — Medusa Nexus just
makes that flow less painful.

---

## 6. Tickets

See the tracker for the breakdown — tagged `vphone·w1·*` through
`vphone·w4·*`. Wave 1's setup script is the immediate deliverable.

---

## 7. Security & legal posture

- **Default off.** No Medusa Nexus install ever launches a vphone VM
  on its own. The setup script is a separate, opt-in command.
- **Read-only checks.** The script *checks* SIP/AMFI status and
  *reports* — never disables them.
- **No firmware ships.** We never store, redistribute, or download
  Apple firmware. The user owns that path end-to-end.
- **Doctor surfaces the risk.** When a vphone VM is healthy and reachable,
  the doctor row carries an extra `mode: research` chip with a link to
  `docs/VPHONE_QUICKSTART.md` so a teammate doesn't trip into research
  mode by accident.

---

## 8. Why this is worth doing

Three concrete wins:

1. **Reproducible iOS lab.** Snapshot a clean VM, run an APK^Wn IPA,
   restore. No more "did the device state matter?" debates.
2. **Lower the bar for iOS dynamic analysis.** Not every team has a
   spare jailbroken iPhone. Most teams have a Mac.
3. **Bridge the static→dynamic gap on iOS.** The existing iOS Wave 1
   covers static. With a vphone in the picture, every iOS auto-hook the
   `HookGenerator` emits has somewhere to actually run.
