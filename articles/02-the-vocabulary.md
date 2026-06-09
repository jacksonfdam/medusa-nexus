---
title: "The vocabulary — every term you need to read a mobile threat report"
description: "A precise glossary of every term used in mobile security reports, grouped by domain: attack surface, findings, engineering, Android-specific, iOS-specific."
published: 2026-06-16
author: Jackson Mafra
tags: ["mobile-security", "glossary", "android", "ios", "appsec", "developers"]
canonical: https://mnexus.vercel.app/articles/02-the-vocabulary
codex_refs:
  - "Command-Line Tools — https://medium.com/@jacksonfdam/"
  - "APK Decompiling — the dark art — https://medium.com/@jacksonfdam/"
medusa_refs:
  - https://github.com/jacksonfdam/medusa-nexus
tldr: |
  A reference dictionary for every term used in the rest of this series. Grouped into five
  domains: surface terminology, findings terminology, engineering terminology, Android-
  specific terms, iOS-specific terms. Read it once. Reference it forever. The articles
  after this one assume you know what each of these means.
---

If you read a mobile penetration testing report cold — without prior context — most of the language will feel familiar and most of the precise meaning will be off by a step or two. The word *finding* doesn't mean *bug*. The word *attack surface* doesn't mean *attack vector*. The word *MASVS* sounds like a typo. The word *intent* has a specific Android meaning that has nothing to do with the English word.

This article is the dictionary the rest of the series will reference. It's deliberately structured for skimming — every term is one paragraph, every paragraph has the same shape (definition → example → where it shows up). Read it once now, return to it whenever a later article uses a term you want pinned down precisely.

The terms are grouped into five domains. Skip whichever you already know.

## Surface terminology

**Attack surface.** Every entry point an attacker can reach from outside the trust boundary. For a mobile app, that includes exported manifest components, declared deeplinks, declared URL schemes, exposed `ContentProvider`s and `BroadcastReceiver`s, IPC endpoints, JavaScript interfaces in WebViews, native libraries loaded into the process, network calls the app initiates, and the user-facing input fields where data crosses from untrusted to trusted state. In MedusaNexus this is represented as the `AttackSurface` model — a single object aggregating every entry-point category. Your job, before anything else, is to know your own attack surface; an attacker will know theirs.

**Attack vector.** The specific path an attacker uses to reach a target through the attack surface. *"Sending a crafted deeplink that triggers the popup-panel WebView"* is an attack vector. *"All your exported activities"* is attack surface. A surface can host many vectors; a vector is always anchored on the surface.

**Threat model.** A structured map of who would want to attack you, what they want, what they have to work with, and what techniques are within their reach. Threat-model frameworks like STRIDE (Microsoft) or LINDDUN (privacy) give you a checklist; mobile-specific frameworks like the [OWASP MAS Threat Modeling guide](https://mas.owasp.org/) tailor the questions to mobile constraints. A threat model precedes a security review — without one, the review has no target.

**Risk.** The product of *likelihood* and *impact*. A bug that's trivially exploited but reveals nothing sensitive is low risk. A bug that takes a sophisticated chain to trigger but exfiltrates every user's auth token is high risk. Risk is what you prioritize remediation by — not severity alone.

**Severity.** A flat, four-or-five-level scale ranking how bad the finding is *if exploited*. MedusaNexus uses five levels: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`. Many frameworks use four (folding INFO into LOW). The label is normative — a CRITICAL is something you fix before the next release; an INFO is something you note and move on.

**Confidence.** Often confused with severity. Confidence is *how sure we are this finding is real*. A static scanner might flag a CRITICAL cryptography misuse with LOW confidence (could be a false positive); dynamic confirmation moves it to HIGH confidence. Reports that confuse severity and confidence ship a lot of noise. In MedusaNexus, dynamic confirmation flips the `confirmed: bool` flag rather than touching severity — the two concepts stay separate by design.

## Findings terminology

**Finding.** The atomic unit a security review produces. One finding describes one issue: title, description, severity, category, evidence, location, remediation. In MedusaNexus the type is `mnexus.models.finding.Finding`; in OWASP the equivalent is a *vulnerability instance*. A report is a structured list of findings.

**Evidence.** The concrete proof that backs a finding. A smali snippet, a decompiled Java line, a Frida log, a proxy-captured request. Without evidence, a finding is an opinion. The MedusaNexus model layer refuses to build a `Finding` with empty evidence — "silence is not a finding" is a one-line invariant in the source.

**Remediation (or mitigation).** The concrete fix. Not *"improve security posture"*. Not *"validate input"*. A code change, a configuration line, a library substitution. MedusaNexus's model layer enforces this at construction time: any finding at `CRITICAL` or `HIGH` severity that doesn't carry a non-empty `remediation` string fails validation and never enters the database. The invariant is intentional — shipping findings without fixes is the noise that gave the industry a bad name.

**CWE — Common Weakness Enumeration.** A community-maintained dictionary of weakness categories, run by MITRE. Each CWE has a number (`CWE-798: Use of Hard-coded Credentials`, `CWE-89: SQL Injection`) and describes a *class* of vulnerability, not a specific instance. Findings reference a CWE so reviewers can find related issues across reports and tools.

**CVE — Common Vulnerabilities and Exposures.** Often confused with CWE. A CVE describes a *specific* vulnerability in a *specific* product (`CVE-2024-12345: Vulnerability in Foo 1.2.3`). CVEs are catalogued instances; CWEs are the categories those instances fall into. Mobile audit findings reference CWEs because they describe weaknesses in your code; if your code shipped a library version with a known CVE, the finding references that CVE too.

**OWASP MASVS — Mobile Application Security Verification Standard.** The current canonical framework for mobile-app security requirements, maintained by OWASP. It defines *what* a secure mobile app should do, organised into categories (`MSTG-CRYPTO-*`, `MSTG-NETWORK-*`, `MSTG-AUTH-*`, etc.) and verification levels (L1 = baseline, L2 = sensitive apps, R = resilience against reverse engineering). When a finding references `MSTG-CRYPTO-1`, it's saying *"this app violates the first MASVS cryptography control."* The MASVS replaced the older *OWASP Mobile Top 10* as the primary checklist for serious mobile audits; the *Top 10* survives as an awareness tool.

**OWASP MSTG — Mobile Security Testing Guide.** The companion guide to the MASVS. The MASVS tells you *what* to verify; the MSTG tells you *how*. Practical test cases, tool recommendations, code examples. When you're learning to audit, the MSTG is the textbook.

**OWASP Mobile Top 10.** A periodically-updated list of the ten most common mobile-app security risks. Useful for executive communication and awareness training; less useful as an audit checklist because it conflates risk classes with vulnerability instances. Cross-references to MASVS controls when you need to dig in.

**Mitigation playbook.** A bundle of remediations grouped by category and intended to be acted on as a whole. MedusaNexus reports always include a Mitigation Playbook section that groups findings by category (Cryptography, Network, Auth, …), lists the remediations together, and orders them by severity. The intent is that a developer can act on an entire category in one PR rather than chasing individual findings.

## Engineering terminology

**Static analysis.** Looking at the app *without running it*. Decompiling, disassembling, parsing the manifest, scanning the resources, walking the bytecode. The advantage: complete coverage of every code path. The disadvantage: cannot observe runtime values, cannot tell which paths the app actually takes in practice. Static analysis produces *suspicions*.

**Dynamic analysis.** Running the app and observing its behaviour. Hooking functions, capturing network traffic, dumping memory at specific points. The advantage: ground truth about what the app does in production. The disadvantage: only covers the paths your test triggers. Dynamic analysis produces *confirmations*.

**Correlation.** Mapping a static suspicion to a dynamic confirmation. *Static analysis sees a hard-coded API key; dynamic analysis sees that key go out over the wire.* When MedusaNexus's correlator can pair a static finding with a dynamic observation, the finding's `confirmed` flag flips and its confidence rises. Findings that have static evidence but no dynamic confirmation stay tentative — useful for the report, marked as such for the reviewer.

**Decompilation.** Turning compiled bytecode back into a higher-level language that looks more like the original source. For Android, `jadx` decompiles DEX bytecode into readable Java (or Kotlin-shaped Java). The output isn't the original source — variable names are mangled if the app was obfuscated, comments are gone, structure may be reorganised — but it's close enough for an analyst to read.

**Disassembly.** Turning compiled bytecode (or machine code) into the assembly instructions the CPU actually executes. Ghidra disassembles native libraries (`.so` files) into ARM64 / x86 assembly. Disassembly is one level lower than decompilation — closer to the hardware, harder to read, but the only option for native code that has no equivalent Java source.

**Bytecode vs machine code.** Bytecode is the format a virtual machine executes (the Android Runtime executes DEX; the JVM executes Java bytecode). Machine code is what the CPU executes directly. Java/Kotlin compile to DEX bytecode; C/C++ in NDK projects compile to machine code in `.so` libraries. Static analysis of Android apps deals with both: jadx handles bytecode, Ghidra handles machine code.

**Hook.** Injecting code into a running process to intercept a function call. Hooks let you log arguments, modify return values, or replace the function entirely. Hooks happen at runtime — they're the primitive of dynamic analysis. *"I hooked `SSLSocketFactory.createSocket` and logged every TLS connection"* is a hook description.

**Frida.** The standard toolkit for dynamic instrumentation on mobile platforms. Frida runs as a server on the device (`frida-server` on Android, `frida-server` on jailbroken iOS) and executes JavaScript "scripts" you load. Each script is a set of hooks. MedusaNexus's Runtime tab drives Frida sessions; the auto-hook generator emits Frida scripts based on what static analysis found.

**Instrumentation.** A superset of hooking. Modifying the app, the runtime, or the operating system to observe or control behaviour that wasn't intended to be observable. Frida is one form; LLDB-based instrumentation on iOS is another; eBPF on Linux is a third. *"Instrumented build"* means a build modified to expose internals — often via `dexlib` patches for Android or Mach-O modifications for iOS.

**Obfuscation.** Deliberately transforming code to make it harder to read after decompilation. On Android, `R8` (and its predecessor ProGuard) is the standard; it renames classes, methods, and fields to single-letter sequences (`a.b.c`), removes unused code, inlines short methods. Obfuscation makes decompilation output less readable but doesn't change runtime semantics — an analyst with patience still gets there.

**Repackaging.** Modifying an app's package contents and re-signing it as a new app. Used for legitimate purposes (translating, theming) and for attacks (injecting a `frida-gadget` library, replacing certificate-pinning libraries, rewriting URLs). MedusaNexus's Stheno integration handles repackaging on the defensive side; on the offensive side, frameworks like `apktool` + `apksigner` + `zipalign` do the same job manually.

**Re-signing.** Generating a new signature for an APK or IPA after modifying it. Android uses APK Signing Scheme v1, v2, v3, and v4; iOS uses Apple's code-signing system. A re-signed app loses its original developer's identity — Android refuses to install an update to an app with a different signature, and iOS refuses to launch a re-signed app on a non-jailbroken device.

**Manifest.** The metadata file declaring the app's identity and capabilities. On Android, `AndroidManifest.xml`; on iOS, `Info.plist`. The manifest is the most-read file in a static audit because it declares the entire externally-visible surface: components, permissions, deeplinks, schemes, exported services.

## Android-specific terminology

**Intent.** A message that one Android component sends to another (or to the operating system) requesting an action. An intent has an *action* (`android.intent.action.VIEW`), optionally a *category* (`android.intent.category.BROWSABLE`), optionally *data* (a `Uri`), and optional *extras* (a key-value bundle). Intents are the universal currency of Android IPC. *Explicit* intents name the target component directly; *implicit* intents describe what they want done and let the system pick a target.

**Intent-filter.** A declaration on an exported component saying *"I can handle these intents."* Lives in the manifest under `<activity>` / `<service>` / `<receiver>`. The intent-filter lists the actions, categories, and data types the component accepts. An intent-filter with `BROWSABLE` is reachable from the browser; an intent-filter without it is only reachable from other apps.

**Deeplink.** A URI that triggers an action inside an app when opened. Custom-scheme deeplinks (`myapp://path`) only work if the user already has the app installed. App Links (`https://example.com/foo`) verify ownership of the domain via the Digital Asset Links protocol and open the app automatically. Both are declared as intent-filters on activities.

**Scheme / host / path.** The three components of a URI that an intent-filter matches against. `myapp://settings/profile?ref=email` decomposes to scheme=`myapp`, host=`settings`, path=`/profile`. An intent-filter can declare any subset; the Android system finds a matching component using exact-match on scheme + host and prefix-match on path.

**Activity.** A single screen in the app. The primary component type. Exported activities can be launched from outside the app by sending the right intent. An exported activity with an open intent-filter is the easiest entrypoint for an attacker.

**Service.** A background-running component without UI. Can be started (one-shot) or bound (long-running with a client). Exported services are attack surface; unprotected exported services with intent-filters are a common finding.

**BroadcastReceiver.** A component that listens for system or app-level broadcast messages. *"User unlocked the phone"*, *"battery low"*, custom broadcasts from your own app. Exported receivers are attack surface — a malicious app can send the same broadcasts your own code sends, possibly tricking the receiver into the wrong state.

**ContentProvider.** A component that exposes structured data to other apps. Backed by SQL queries, file streams, or arbitrary key-value lookups. Exported providers without per-permission checks have produced some of the most-impactful Android vulnerabilities in the last decade. The Codex entry *Content-provider exploitation* goes deeper.

**NetworkSecurityConfig.** An XML file (typically `res/xml/network_security_config.xml`) declaring per-domain TLS policy. *"Disallow cleartext for production hosts"*, *"trust user-installed CAs in debug"*, *"pin this cert chain on these hosts."* The defensive equivalent of a manifest entry for network traffic.

**ProGuard / R8.** The Android obfuscation and shrinking toolchain. R8 is the modern replacement for ProGuard; both rename classes/methods to single letters, strip unused code, and inline short methods. *"Decompiled but obfuscated"* means jadx produced output but the names are `a.b.c` — readable in shape, opaque in intent. The Codex entry *APK Decompiling — the dark art* covers reading obfuscated output.

**JNI — Java Native Interface.** The bridge between Java/Kotlin and native code (C/C++). Functions named `Java_com_example_Foo_bar` are JNI exports — callable from the Java side. When MedusaNexus's native-lib analysis surfaces JNI exports, those are the entry points an attacker would target to reach into the native side of the app.

## iOS-specific terminology

**Info.plist.** The iOS equivalent of `AndroidManifest.xml`. A property-list file (`.plist`) declaring the app's bundle identifier, supported URL schemes, required device capabilities, permission usage descriptions, and configuration like `NSAppTransportSecurity`. Always the first file to read in an iOS audit.

**Bundle ID.** The unique identifier for an iOS app (`com.example.MyApp`). Equivalent to Android's package name. Used by the system for code signing, push notifications, app-to-app communication, and uniqueness in the App Store.

**Entitlement.** A capability granted to an iOS app, encoded in the app's signed entitlements file. Examples: `aps-environment` for push notifications, `com.apple.developer.networking.networkextension` for VPN apps, `keychain-access-groups` for shared keychain access. Entitlements are baked into the signed binary; you can't grant or revoke them at runtime.

**Provisioning profile.** The document that ties an app's bundle ID, signing certificate, entitlements, and target devices together. Embedded in the IPA as `embedded.mobileprovision`. Tells you the team ID, distribution type (development / ad-hoc / app-store / enterprise), and expiry. Often the first place to look in an audit — an enterprise-distributed app trying to look like an App Store app is a red flag.

**Mach-O.** The binary format used on Apple platforms. Equivalent to ELF on Linux/Android-native or PE on Windows. iOS executables and dynamic libraries are Mach-O. MedusaNexus's iOS patcher (`mnexus/runtime/ipa_patcher.py`) parses Mach-O directly to apply byte-level patches.

**FairPlay.** Apple's DRM scheme. Apps distributed through the App Store are FairPlay-encrypted at the binary level — the executable can only be decrypted by the device that downloaded it, using a key derived from the user's Apple ID. To analyze App Store binaries statically, you must first decrypt; tools like `bagbak` and `frida-ios-dump` extract the decrypted binary from a jailbroken device after the OS has decrypted it for execution.

**URL Scheme.** The iOS equivalent of an Android custom-scheme deeplink. Declared in `Info.plist` under `CFBundleURLTypes`. Other apps invoke them by calling `UIApplication.shared.open(URL(string: "myapp://..."))`. Same security model — anyone on the device can trigger your scheme.

**Universal Link.** The iOS equivalent of an Android App Link. Maps `https://example.com/foo` to your app instead of opening Safari. Configured via an `apple-app-site-association` file on the domain. More secure than URL Schemes because the domain ownership is cryptographically verified.

**Keychain.** The iOS secure-storage primitive for credentials. Hardware-backed on modern devices via the Secure Enclave. The right place to store auth tokens, refresh tokens, encryption keys. *"Stored in the Keychain"* is the canonical mitigation for credential-storage findings on iOS.

**App Attest.** Apple's app-attestation API. Lets your backend verify that a request actually came from an authentic, unmodified instance of your app on a real Apple device — the iOS equivalent of Play Integrity. Generates hardware-backed assertions that your server validates against Apple's published keys. The Codex entries on *Device Attestation 101* and *Trust No One* cover the conceptual framing; App Attest is the iOS implementation.

**Jailbreak.** A user-applied modification that removes Apple's restrictions on what the OS will let an app do — including disabling code-signing checks, mounting the system partition writable, and allowing root-level processes. On jailbroken devices, FairPlay-encrypted apps can be dumped, Frida can attach to any process, and the Mach-O patcher can re-sign with any identity. Most iOS dynamic analysis happens on jailbroken devices for this reason; *super-tart-vphone* (covered in article 8) is the alternative.

## Operational terminology

**Static fan-out.** Running every static-analysis engine in parallel against the same input. MedusaNexus's ingest pipeline fan-outs across jadx, apktool, Ghidra, MobSF, the secrets scanner, the deeplink extractor, and several intelligence-layer modules. The fan-out finishes in roughly the time of the slowest engine; the orchestrator collates the findings afterward.

**Correlator.** The module that pairs static suspicions with dynamic observations. Lives at `mnexus/intelligence/correlator.py`. When the correlator matches a static finding (e.g., *"this method calls `SSLContext.getInstance`"*) to a dynamic observation (e.g., *"a TLS handshake just happened with an insecure context"*), it flips the static finding's `confirmed` flag.

**Chain correlator.** A second-level correlator that pattern-matches *combinations* of findings against known attack chains. The 1-click ATO chain explained in article 5 is one such pattern; when its components are individually present in the surface, the chain correlator emits a single `CRITICAL` finding referencing all the links as evidence. The pattern lives at `mnexus/intelligence/chain_correlator.py`.

**Pipeline.** A named sequence of engine actions that runs against a project. MedusaNexus ships a built-in catalog (`full-static-android`, `android-quick`, `ios-static-only`, etc.) plus the ability to register your own. Pipelines are how the CI/CD integration in article 6 executes complex workflows in one HTTP call.

**Workspace.** The directory MedusaNexus uses to store per-project artefacts (`~/.mnexus/workspace/<project_id>/`). Source APK, decompiled tree, generated Frida hooks, reports, traffic captures. Everything outside the SQLite database lives here.

**Doctor.** A health-check pass over every registered engine. Verifies binaries are on PATH, services are reachable, API keys parse, versions are recent enough. Run on startup of the REPL, run as a stand-alone command (`mnexus doctor`), and run as the first step of CI scripts. If `doctor` is unhappy, the pipeline isn't going to be happy either.

## TL;DR

Mobile security has a precise vocabulary. *Findings* are atomic units backed by *evidence* and accompanied by *remediation*; their severity is independent of their confidence. *CWE* describes a class of weakness, *CVE* describes a specific instance, *MASVS* describes what to verify, *MSTG* describes how to verify it. *Static analysis* looks at the binary, *dynamic analysis* runs it, *correlation* pairs the two. On Android, your attack surface is the union of exported `Activity` / `Service` / `Receiver` / `Provider` components plus declared deeplinks; on iOS, it's `CFBundleURLTypes` and Universal Links plus exposed `Bundle` content. Mach-O is the iOS binary format, ELF the Linux one. FairPlay encrypts App Store binaries until a jailbroken device decrypts them for execution; App Attest and Play Integrity are the OS-mediated attestation primitives the Blue Team builds on.

You don't have to memorize this in one sitting. You will hear every term in the rest of the series; bookmark this article and come back when one slips.

> The biggest investment a developer can make in mobile security isn't a tool subscription — it's a precise vocabulary. Once *intent*, *deeplink*, *evidence*, *severity*, *MASVS* and *correlation* mean exactly one thing to you, every report you read becomes faster to process, every fix becomes faster to identify, and every meeting with your Red Team becomes a conversation between equals.

---

**Next in the series →** *Your first APK scan, end to end — in 10 minutes.* Hands-on: install MedusaNexus, drop an APK, read the findings panel, walk the web UI, generate a report. Zero theory, pure muscle memory. The article that turns curiosity into action.

---

*The series continues weekly on [Medium](https://medium.com/@jacksonfdam/). For deeper coverage of specific patterns — content provider exploitation, attestation, root detection, RASP, command-line tools — see the Codex at [Umain Fortress](https://umain-fortress.vercel.app/).*
