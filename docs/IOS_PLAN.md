# 🔱 MEDUSA NEXUS — iOS Support Plan

*One platform per APK was the wrong call. Time to make the platform invariant.*

This document is the plan-of-record for extending the orchestrator to scan
iOS apps end-to-end. It covers the engines we add, the engines we explicitly
*don't* add (and why), the data-model changes, and the work breakdown.

**Status**: planning. No code lands until each ticket is reviewed.

---

## 1. Design principles

The reason this codebase is small is because we said **no** a lot. We keep
saying no:

1. **One tool per job.** If two tools do the same thing, we pick one and
   reject the other. Maintenance budget is finite.
2. **Bias to libraries over CLIs we don't ship.** Where a thing can be a
   25-line Python parser, it stays in-tree (we already do this for AXML +
   DEX strings + ELF strings).
3. **Frida is the dynamic dispatch layer.** Anything that's "instrument a
   running app at runtime" goes through Frida. We don't ship a second
   instrumentation framework.
4. **Burp is the proxy.** Anything that's "MITM HTTPS traffic on a mobile
   device" goes through Burp's API. We don't ship a second proxy.
5. **MobSF is the wide static net.** It already covers iOS. We don't add a
   second wide-spectrum static scanner.
6. **The platform is invariant in the data model.** `Project`, `Finding`,
   `AttackSurface` are platform-agnostic; only the engines branch on
   "is this an APK or an IPA?".

---

## 2. Tool evaluation

The cheat sheet listed 60+ tools. After applying §1 we get the following.

### 2.1 Tools we ADOPT

| Tool | Why | Replaces / overlaps |
|------|------|---------------------|
| **libimobiledevice** (`idevice*` family) | iOS analog to ADB — list devices, install/uninstall IPAs, pull files via AFC, follow `idevicesyslog`. **Required**. | New capability — no overlap. |
| **ios-deploy** | Install IPAs to non-jailbroken devices via the Mobile Installation framework. | Filling a gap libimobiledevice doesn't fully cover. |
| **bagbak** | Decrypt App Store IPAs from a jailbroken device. Most modern of its class — no SSH required, supports app extensions. | Picked over Clutch (older), dumpdecrypted (manual `DYLD_INSERT_LIBRARIES`), bfinject (less actively maintained), Frida-iOS-Dump (works but bagbak is cleaner), Fridpa (re-signing tool, different job), XReSign (re-signing, different job). |
| **otool / class-dump / dsdump** | Mach-O metadata + Objective-C class table extraction. We invoke them where present; built-in fallback parses the load commands directly. | Picked over Hopper (closed-source/paid), Radare2 (we already have Ghidra). For deep disassembly we drive the **existing** Ghidra engine on Mach-O — same `analyzeHeadless` + post-script pattern as for `.so`. |
| **plistlib** (Python stdlib) | Parse `Info.plist`, `embedded.mobileprovision`, entitlements. **Built-in, no external dep**. | Replaces every "use plistutil from XYZ package" recommendation. |
| **SSL Kill Switch 2** | Standard iOS pinning bypass. Single-purpose, deployed as a Frida recipe. | Picked over iOS-TrustMe (less coverage), the various Cycript pinning tweaks (Cycript itself is superseded by Frida). |
| **keychaindumper** | Pulls keychain contents from a jailbroken device. Surface as a recipe + a one-shot finding generator (`leaked_keychain_items`). | Single-purpose — no overlap. |
| **DVIA-v2 / iGoat-iOS / InsecureBankv2 / UnCrackable** | Lab APKs/IPAs for self-test. Add to `scripts/setup.sh --lab`. | These are reference targets, not engines. |

### 2.2 Tools we ADOPT *only as Frida recipes* (no engine, no extra dep)

These are scripts you can already run via Frida — they live in our recipes
library so they show up in the UI alongside Medusa modules. No separate
integration is needed.

- `ios-ssl-bypass` (lichao890427)
- `ios10-ssl-bypass` (dki)
- `fridantiroot` (dzonerzy) — already there for Android
- `universal-android-ssl-pinning-bypass` (pcipolloni) — already there
- A `keychain_dumper` recipe that wraps the canonical Frida script.
- A `jailbreak_detection_bypass` recipe (covers `tsProtector`/`JailProtect`/
  `Shadow` use-cases without us shipping any of them).

### 2.3 Tools we ADOPT *optionally* (Phase 2 — only if there's demand)

| Tool | Wave | Rationale |
|------|------|-----------|
| **Objection** | Phase 2 | Frida wrapper with built-in helpers. We have Frida; Objection adds workflow shortcuts (auto-explore, memory dump, RPC wrappers). Worth a thin engine that exposes Objection's most useful helpers via JSON, *only* if the recipe library proves insufficient. |
| **Drozer** | Phase 2 | Android-only. Goes deeper into IPC than MobSF — content-provider injection, intent fuzzing, broadcast sniffing. Worth a dedicated engine **only if** real-world findings prove our manifest-derived IPC findings are too shallow. |
| **OWASP iMAS** | Phase 2 | iOS security controls library. More documentation than tooling — fold into our remediation copy where applicable. |

### 2.4 Tools we REJECT (with reasoning)

| Tool | Why we skip |
|------|-------------|
| **mitmproxy / OWASP ZAP / Charles Proxy / Mallory / Wireshark / tcpdump / Burp Suite Mobile Assistant** | We use Burp's REST API. Adding a second proxy doubles maintenance for zero capability gain. *Mitmproxy is great — just not for us.* |
| **Apk-mitm** | Same job as our Stheno-based APK patching + Frida pinning bypass. |
| **Cycript** | Frida supersedes it for Android **and** iOS. Cycript has been deprecated in practice since 2018; Frida-Cycript is a reanimation that's easier to ignore. |
| **Needle** | iOS framework, last meaningful release 2018. Supplanted by Frida + Objection. |
| **Inspeckage** | Xposed-based; superseded by Frida. |
| **AndBug** | Java-only debugger; rarely used vs Frida. |
| **House / RMS / Diff-GUI / iNalyzer / Grapefruit (Passionfruit) / Introspy-iOS** | These are all "Frida web UIs". We **are** the Frida web UI now. Bringing in a second one would be confusing. |
| **AndroBugs / Qark / SUPER / Spotbugs / GDA / Bytecode Viewer / APK Studio** | MobSF + our DEX scanner cover this. None of these are best-in-class anymore. |
| **PID Cat** | We have a logcat tail with grep. Same thing. |
| **Hopper / Radare2** | Ghidra is already integrated and free. Hopper is paid. Radare2 has a steeper learning curve. |
| **Magisk / tsProtector / JailProtect / Shadow / RootCoak Plus / Just-Trust-Me / SSLUnpinning / Android-SSL-Bypass / SSL Trust Killer** | These run *on the device*, not in our orchestrator. We document the user's choice and our recipes do the actual bypass via Frida. |
| **Filezilla / Cyberduck / iFunbox / itunnel / iProxy / Apple Configurator 2** | UI tools we'd duplicate badly. Our file manager talks AFC directly via libimobiledevice. |
| **Clutch / dumpdecrypted / bfinject / Fridpa / Frida-iOS-Dump / XReSign** | Pick one — bagbak. The rest are older or solve a slightly different problem (re-signing). |
| **BinaryCookieReader** | Reimplement in ~30 lines of Python. The format is documented and trivial. |
| **Cydia Substrate / Xposed Framework** | Legacy. Frida is the current answer. |
| **Mobile pentesting VMs (Appie, Tamer, Androl4b, Vezir, Mobexler)** | Out of scope. We orchestrate engines; users pick their own host OS. |

---

## 3. Architecture changes

### 3.1 Data model

| Model | Change |
|-------|--------|
| `Project`     | Add `platform: Literal["android", "ios"]`. SQLite migration: existing rows default to `"android"`. |
| `Project`     | Rename `package_name` to `bundle_id` *only* in display — keep field name for backward compat; add a `bundle_id` property that returns the same value with a docstring explaining the dual meaning. |
| `AttackSurface` | Add `entitlements: list[str]` (iOS), `url_schemes: list[str]` (iOS deeplink analog), `app_transport_security: dict[str, Any]` (ATS exceptions). Existing `permissions` stays Android-only. |
| `AttackSurface` | Add `provisioning_profile: dict[str, Any] | None` (iOS — distribution type, team id, expiry). |

### 3.2 Engines

| Engine | Status | Role |
|--------|--------|------|
| `ADBEngine`        | existing | Android device bridge. |
| `APKToolEngine`    | existing | Android static. |
| `JADXEngine`       | existing | Android DEX scan. |
| `GhidraEngine`     | existing | **Both platforms** — Mach-O for iOS, ELF for Android. |
| `MobSFEngine`      | existing | **Both platforms** — already supports iOS uploads. |
| `BurpEngine`       | existing | Platform-agnostic. |
| `FridaEngine`      | existing | **Both platforms** — recipes select scripts by target OS. |
| `IDeviceEngine`    | **NEW**  | iOS analog to ADB — libimobiledevice + ios-deploy wrappers. |
| `IPAToolEngine`    | **NEW**  | iOS static — IPA zip + Info.plist + entitlements + Mach-O metadata. Built-in (no external dep). |
| `BagbakEngine`     | **NEW**  | iOS IPA decryption from a jailbroken device. |

### 3.3 Pipeline routing

`orchestrator.ingest_apk` becomes `orchestrator.ingest`, dispatches by file
extension:

```python
async def ingest(path: Path, **kw) -> Project:
    if path.suffix.lower() in (".apk", ".xapk"):
        return await self._ingest_apk(path, **kw)
    if path.suffix.lower() == ".ipa":
        return await self._ingest_ipa(path, **kw)
    raise UnsupportedArtifact(path.suffix)
```

Both paths produce the **same** `Project` shape; the engines that participate
just differ. The `FindingCorrelator` and `HookGenerator` are platform-aware
via the new `platform` field but otherwise unchanged.

### 3.4 API endpoints

All existing project endpoints stay. Add:

```
POST  /v1/ipas/upload                      # ingest an .ipa
GET   /v1/idevices                         # list iOS devices
POST  /v1/idevices/{udid}/install          # IPA install via ios-deploy
POST  /v1/idevices/{udid}/uninstall
POST  /v1/idevices/{udid}/decrypt          # bagbak wrapper
GET   /v1/idevices/{udid}/syslog           # idevicesyslog tail
GET   /v1/idevices/{udid}/files?path=      # AFC listing
GET   /v1/idevices/{udid}/file?path=       # AFC pull
POST  /v1/idevices/{udid}/screenshot       # via idevicescreenshot
```

The existing `/v1/devices/...` (Android multi-device) namespace is untouched.

### 3.5 Frontend

- **Upload** — accept `.ipa` alongside `.apk`/`.xapk`. The dropzone already
  has the file-input; add `.ipa` to the `accept` attr.
- **Project list** — small Apple/Android glyph next to the package name.
- **Project tabs** — terminology adapts:
  - "Components / Deep links" → "URL Schemes / Universal Links" on iOS.
  - "Permissions" → "Entitlements" on iOS.
  - "Native libraries" → "Mach-O frameworks" on iOS.
- **Device dropdown** in the ADB control panel groups Android + iOS devices
  with their respective transport (`adb` / `ios-deploy`/`libimobiledevice`).
- **Recipes** library gets a **platform** filter chip (Android | iOS | Both).

### 3.6 MASTG mapping

We already map findings to `MSTG-CRYPTO-x` etc. Coverage today is
Android-leaning; the iOS work expands rule packs to cover:

- `MSTG-STORAGE-1..14` (iOS keychain, Files app, NSURLCache, etc.).
- `MSTG-CRYPTO-1..6` (CommonCrypto patterns in Mach-O).
- `MSTG-AUTH-1..12` (Keychain access groups, Touch/FaceID escrow).
- `MSTG-NETWORK-1..6` (ATS, NSURLSessionPinning).
- `MSTG-PLATFORM-1..11` (URL schemes, App Extensions, WKWebView, ATS).
- `MSTG-CODE-1..9` (Swift/Obj-C anti-patterns: `NSLog` of secrets,
  `NSUserDefaults` of credentials).
- `MSTG-RESILIENCE-1..13` (jailbreak detection, anti-debug, integrity).

---

## 4. Phasing

**Wave 1 — minimum useful iOS scan** (everything below in tickets):
1. Data model (`platform`, `bundle_id`, `entitlements`, `url_schemes`).
2. `IPAToolEngine` (built-in, no external deps).
3. Orchestrator dispatch by extension.
4. Frontend accepts `.ipa` and shows iOS-flavored tabs.
5. Frida engine recipes for iOS pinning bypass + jailbreak bypass +
   keychain dumper.

**Wave 2 — device interaction**:
6. `IDeviceEngine` (libimobiledevice wrapper).
7. iOS device tab in the ADB control panel (renamed to "Device control").
8. `BagbakEngine` for App Store decryption.

**Wave 3 — depth + nice-to-haves**:
9. Mach-O Ghidra integration + dedicated rule pack.
10. Optional `ObjectionEngine` if recipes prove insufficient.
11. Optional `DrozerEngine` for Android deep IPC.
12. Lab targets in `scripts/setup.sh --lab`.

Each wave is independently shippable.

---

## 5. Tickets

The tickets that follow this plan land in the task tracker. Wave 1 first.
