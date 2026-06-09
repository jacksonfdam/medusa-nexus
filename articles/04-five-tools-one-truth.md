---
title: "Five tools, one truth — how MedusaNexus orchestrates static analysis"
description: "Why jadx, apktool, Ghidra, MobSF, and PlayIntel each see a different slice of an APK — and what an orchestrator built on top of them produces that none could alone."
published: 2026-06-30
author: Jackson Mafra
tags: ["mobile-security", "android", "static-analysis", "orchestration", "developers"]
canonical: https://mnexus.vercel.app/articles/04-five-tools-one-truth
codex_refs:
  - "APK Decompiling — the dark art — https://medium.com/@jacksonfdam/"
  - "Command-Line Tools — https://medium.com/@jacksonfdam/"
medusa_refs:
  - https://github.com/jacksonfdam/medusa-nexus
tldr: |
  jadx decompiles, apktool unpacks resources, Ghidra disassembles native code, MobSF
  provides a heuristic second opinion, PlayIntel hunts credentials and Firebase configs.
  Each tool sees a different slice of the APK. None of them, individually, produces a
  complete attack surface. The orchestrator's job is to fan them out in parallel,
  reconcile the overlapping findings, and emit a single picture none of them could
  produce alone.
---

Any developer doing mobile security work eventually accumulates a folder of standalone tools — `jadx-gui` open on one monitor, `apktool d` running in a terminal, `MobSF` in a Docker container on localhost:8000, Ghidra projects sitting on disk. Each one does its job well. None of them, individually, tells the whole story about the APK in front of you.

That fragmentation is the problem MedusaNexus was built to solve. The platform doesn't reinvent any of those engines — `jadx` is still `jadx`, Ghidra is still Ghidra. What it adds is the *connective tissue*: parallel execution, finding reconciliation, surface aggregation, chain correlation, and a single data model the rest of the platform reads from. This article walks through what each of the five core static engines actually sees, what each one misses, and what the orchestrator produces by combining them.

## Why five tools instead of one

The temptation, when starting out, is to find the *one good tool* — the all-in-one scanner that produces a complete report. The temptation is reasonable; tool fragmentation is annoying. The reason it doesn't work is structural: every static engine has a *perspective*, and the perspective constrains what it can see.

A decompiler reads bytecode. It will tell you about hard-coded strings in Java/Kotlin, about API calls the code makes, about control flow. It will not tell you anything about the resources outside the bytecode — `res/xml/network_security_config.xml`, `res/raw/*.json`, `assets/*` — because those aren't in the DEX.

A resource unpacker reads the APK as a zip and parses the AAPT-compiled XML back to source-shaped form. It will tell you about manifest declarations, layout files, drawable references, raw resource bundles. It cannot tell you anything about what the bytecode *does* with those resources — whether the cleartext API URL in `BuildConfig.java` is ever read, or only present as a debug aid.

A native-code disassembler reads `.so` files. It will tell you about JNI exports, hard-coded URLs in the strings table, crypto-routine signatures, ROP gadgets. It is blind to the Java/Kotlin side that calls into the native library.

A framework-aware scanner uses heuristics tuned to specific frameworks and platforms — Android system APIs, common third-party SDKs, OWASP MASVS controls. It catches things specific tools miss because they were never trained on framework conventions, and it misses things specific tools catch because the heuristics didn't model that case.

A credential and Firebase scanner does pattern matching tuned to the formats specific services use — `AKIA…` for AWS, `AIza…` for Google API keys, `xoxb-…` for Slack bots, `eyJ…` for JWTs. It catches what the generic secrets scanner misses by knowing exactly which patterns matter and which look-alike values are noise.

Each of these is necessary. None is sufficient. The orchestrator stitches them together; the rest of this article walks through what each contributes.

## jadx — Java/Kotlin decompilation

The first engine in any Android analysis pipeline. `jadx` reads the DEX bytecode (`classes.dex` and friends), reconstructs the Java/Kotlin source, and emits a directory tree that looks like an exported IntelliJ project. For a 20-megabyte APK with a typical ProGuard pass, the output is on the order of 50,000–100,000 files; for a debug build with no obfuscation, it's a near-perfect reconstruction of the original source.

What `jadx` is good at:

* **Class- and method-level structure.** Every class declared, every method signature, every field. Inheritance, interfaces, generics.
* **String literals.** Every hard-coded string in the code path — URLs, format strings, error messages, encryption keys. The secrets scanner walks these.
* **API call detection.** What system APIs the code invokes — `Cipher.getInstance("AES/ECB/PKCS5Padding")`, `SSLContext.getInstance("SSL")`, `WebView.addJavascriptInterface`. The patterns that map to MASVS controls.
* **Reflection traces.** When code uses `Class.forName("...")` or `Method.invoke`, the analyser can sometimes follow the chain to the real call.

What `jadx` is bad at:

* **Heavily obfuscated code.** R8/ProGuard renaming makes the output a sea of `a.b.c` calls. Structure remains; intent doesn't. The Codex entry *APK Decompiling — the dark art* covers techniques for reading obfuscated output (string-table cross-referencing, control-flow recognition, behavioural fingerprinting).
* **Code generated at runtime.** Bytecode loaded from disk, downloaded after install, or generated by ART. Static analysis can't see runtime-loaded code.
* **Native code.** `.so` libraries are opaque to `jadx`; only the `loadLibrary` call shows up in the Java side, with no insight into what the library does.

In MedusaNexus, `jadx` runs as one of the parallel static engines. Its output lives at `~/.mnexus/workspace/<project_id>/jadx/`, and downstream analysers — the secrets scanner, the deeplink extractor, the crypto-primitive sniffer — walk it for their own patterns.

## apktool — resources, manifest, smali

Where `jadx` reads bytecode, `apktool` reads the APK as a zip archive and uses AAPT to decode the binary-encoded XML resources back into source-shaped form. The output is everything `jadx` doesn't produce: `AndroidManifest.xml` as readable XML, every layout file, every resource bundle, every raw asset, every smali file (DEX bytecode in human-readable assembly form).

What `apktool` contributes:

* **Manifest visibility.** The complete `AndroidManifest.xml` as the OS sees it — every exported component, every intent-filter, every permission, every `<meta-data>` tag. The foundation of the attack surface.
* **Network security configuration.** `res/xml/network_security_config.xml` — the per-domain TLS policy. Whether cleartext is allowed, what's pinned, what's exempted in debug builds.
* **Resource strings.** `res/values/strings.xml` and its localizations. Sometimes contains operational metadata accidentally left in (internal API hostnames, debug toggle keys).
* **Raw assets.** `assets/` and `res/raw/` — files bundled into the APK that aren't compiled. JavaScript bundles for WebViews, configuration files for ML models, certificate bundles, third-party SDK configs.
* **Smali output.** When `jadx` chokes on a particular class (rare but happens with aggressive obfuscation), the smali version remains readable for an analyst willing to work in DEX assembly.

What `apktool` is bad at: it doesn't analyse bytecode at all. It produces a richly-decoded *static structure* for the analyser to read, not findings of its own.

In MedusaNexus, `apktool`'s output lives at `~/.mnexus/workspace/<project_id>/apktool/`. The manifest analyser, permissions analyser, network-security-config parser, and deeplink extractor all read from it.

## Ghidra — native code analysis

When an Android app uses native code — almost every app does, even if only via a third-party SDK — the analysis problem changes shape entirely. Native libraries (`.so` files) are compiled ARM64 or x86_64 machine code, not bytecode. `jadx` doesn't read them. `apktool` doesn't analyse them. Ghidra does.

Ghidra is the NSA's open-source reverse-engineering platform. It's a heavyweight tool — gigabytes of install, Java-based UI, project-oriented workflow — but it has a headless mode (`analyzeHeadless`) that fits into automated pipelines. MedusaNexus runs Ghidra headless against every `.so` in the APK.

What Ghidra contributes:

* **JNI export enumeration.** Functions whose names start with `Java_` are callable from the Java side via the JNI bridge. These are the entry points an attacker would target to reach into the native code.
* **String table analysis.** Hard-coded URLs, hostnames, file paths, error messages in the `.rodata` segment. When an app's Java side looks clean but the native side has `http://api.example.com/admin` in its strings table, that's a finding.
* **Crypto-routine identification.** Ghidra's analyser recognises AES S-boxes, SHA constants, RSA exponents by signature. The output is a list of cryptographic primitives the native code uses — useful both for compliance (FIPS-tracked algorithms) and for security (recognising deliberately-weak algorithms like DES still in use).
* **Symbol cross-referencing.** Calls between native functions, calls from Java into native, calls from native to system libraries (`libssl.so`, `libc.so`). The picture of how native code interfaces with everything else.

What Ghidra is bad at: speed. A multi-megabyte `.so` can take minutes to fully analyse. The orchestrator runs Ghidra in parallel with the other engines, so the rest of the pipeline doesn't block — but a Ghidra-heavy scan is genuinely slower than a Ghidra-skipped one (`./scripts/setup.sh --minimal` skips it deliberately).

In MedusaNexus, Ghidra's output gets parsed by `mnexus/engines/ghidra_engine.py` into structured findings: one `NativeLibrary` model per `.so`, with `jni_functions`, `crypto_primitives_detected`, and `hardcoded_urls` populated from the analysis. The native tab in the web UI is a direct projection of those models.

## MobSF — heuristic second opinion

MobSF (Mobile Security Framework) is a long-running open-source project that runs its own static-analysis pipeline against APKs. It's framework-aware, MASVS-mapped, and tuned over years of mobile-audit experience. Where `jadx` + `apktool` + Ghidra produce a *picture*, MobSF produces an *opinion*.

What MobSF contributes:

* **Independent ruleset.** MobSF's rules are written by a different team with a different perspective. When MobSF and MedusaNexus agree on a finding, confidence is high. When they disagree, the disagreement itself is signal — one of them is wrong, and figuring out which is part of the audit.
* **MASVS coverage.** MobSF maps findings to MASVS controls. The overlap with MedusaNexus's own MASVS mapping creates a sanity check; gaps in the overlap reveal blind spots in either tool.
* **Domain heuristics.** Patterns specific to Android framework usage that aren't in generic rule libraries — improper Firebase rules, AndroidKeyStore misuse, dangerous WebView configurations. The years of accumulated rules.
* **Tracker detection.** MobSF maintains a list of analytics, ads, and tracking SDKs. When the APK includes one, MobSF flags it — useful for privacy-focused audits.

What MobSF is bad at: depth. It's a *broad* tool — it catches what generic patterns can catch. It's not the right tool for understanding a specific attack chain. The orchestrator treats MobSF as a second opinion, not a primary engine.

In MedusaNexus, MobSF runs as an HTTP-driven engine. The installer's `--mobsf` flag spins up the Docker container with a pinned API key; the orchestrator POSTs the APK to MobSF's REST endpoint and parses the JSON response into findings. The MobSF tab in the web UI shows the raw MobSF report alongside the MedusaNexus findings for cross-reference.

## PlayIntel — credential + Firebase reconnaissance

PlayIntel started as a Python port of an internal Go scanner specialised for mobile credential and Firebase reconnaissance. It became the fifth engine when its hit rate against real APKs proved consistently higher than the generic secrets scanner. PlayIntel is the *specialist* in the lineup.

What PlayIntel contributes:

* **Tuned credential patterns.** ~25 confirmed patterns covering OpenAI, Anthropic, AWS, Stripe, Slack, GitHub, FCM legacy server keys, PEM private keys, and more. Each pattern is tight enough to avoid false positives but loose enough to catch obfuscated variants.
* **AKIA paired-secret search.** When an AWS access key (`AKIA…` or `ASIA…`) appears, PlayIntel scans a 1024-byte window for the paired secret key with extra entropy and hex-only filters to drop SHA-1s. The pair is the exploitable artefact, not the access key alone.
* **Firebase configuration extraction.** Parses `google-services.json`, mines the `resources.arsc` for Firebase resource entries, and emits structured `FirebaseConfig` objects with `project_id`, `api_key`, `database_url`, `storage_bucket`. Downstream, the active-probe module hits each config against RTDB / Firestore / Storage to find misconfigured rules.
* **Play Store streaming mode.** PlayIntel can stream an APK directly from Google Play (no local download), using a pure-Python implementation of the Play Store protocol. The use case: continuously scanning competitor apps, partner apps, or your own production builds without manual download.
* **Resource ARSC parser.** Hand-rolled parser for Android's compiled resource table, written from scratch (no `aapt` dependency). Extracts every string resource — Firebase configs, but also thousands of unrelated strings used for entropy-filtered secret detection that other tools miss.

What PlayIntel is bad at: it's narrow. It doesn't understand Java/Kotlin, doesn't disassemble native code, doesn't do crypto-primitive identification. Specialist depth in exchange for breadth.

In MedusaNexus, PlayIntel runs as a first-class engine. The Codex entry on credential scanning predates the PlayIntel engine and informed several of its patterns; the engine in turn is what powers the `/play-scan` workflow that streams APKs from the Play Store.

## What the orchestrator produces

If the five engines were standalone, you'd produce five disjoint reports and reconcile them manually. The orchestrator's job is to do the reconciliation automatically.

**Step 1: parallel fan-out.** Every engine runs in parallel against the same APK. With `MNEXUS_PARALLEL_ENGINES=1` (the default), the wall-clock is the slowest engine's runtime — typically Ghidra on a heavy app, or MobSF if it's spinning up cold.

**Step 2: surface build.** The intelligence layer aggregates per-engine outputs into one `AttackSurface` model. Components from `apktool`'s manifest parse. Deeplinks from `jadx`'s URL extraction plus `apktool`'s intent-filter parse. Native libraries from Ghidra. API endpoints from `jadx`'s string-literal scan plus Ghidra's `.rodata` scan plus `apktool`'s manifest. Crypto operations from `jadx` plus Ghidra. The surface is the *union* of every engine's perspective, deduplicated and structured.

**Step 3: finding reconciliation.** When two engines report the same finding — for instance, `jadx` and MobSF both flag a hard-coded API key — the orchestrator collapses them into one finding with two `source_engine` references and a higher confidence. When they disagree on severity, the higher severity wins. When only one engine sees something, the finding stays single-sourced.

**Step 4: chain correlation.** The chain correlator pattern-matches against known attack chains — the 1-click ATO chain (article 5) is one example. When the components of a chain are individually present in the surface, a single `CRITICAL` chain finding is emitted referencing every link. This is the layer that produces findings *no individual engine could*: the chain is invisible to any one engine because each engine sees only its slice.

**Step 5: hook generation.** For findings that would benefit from dynamic confirmation, the auto-hook generator emits Frida scripts. The static suspicion becomes the seed for the dynamic confirmation — the loop that distinguishes a serious audit from a checklist scan.

The result is a single `Project` object — one `AttackSurface`, a list of `Finding`s, a risk score, a set of generated hooks. The CLI, REPL, web UI, JSON API, and MCP server all read from that same object. The fragmentation that exists at the engine layer is invisible at the consumer layer.

## A finding that exists because the engines disagreed

To make the orchestrator's contribution concrete, consider a finding pattern that requires multiple engines to surface:

* `jadx` sees a method `loadConfig()` that opens a file path stored as a string literal.
* `apktool` sees a file at `res/raw/config.json` containing a `firebase_url` field with a real URL.
* `PlayIntel` parses the `resources.arsc` and extracts a `firebase_database_url` resource entry pointing at the same URL.
* PlayIntel's active probe (when enabled) confirms the RTDB instance allows anonymous read.

No single engine produces this finding. `jadx` doesn't read raw resources. `apktool` doesn't extract Firebase configs. PlayIntel doesn't analyse Java code. The active probe doesn't know what Firebase URL to test until the static extraction is done. The orchestrator chains them in the right order, and the result is one `CRITICAL` finding with a concrete remediation: lock down the RTDB rules.

That's the *truth* the five tools converge on. None of them sees it alone; together, they do.

## TL;DR

`jadx` decompiles Java/Kotlin bytecode. `apktool` unpacks resources and the manifest. Ghidra disassembles native libraries. MobSF provides a heuristic second opinion mapped to MASVS controls. PlayIntel hunts credentials and Firebase configurations with tuned patterns. Each tool is excellent at its perspective and blind everywhere else. The orchestrator runs them in parallel, builds a unified attack surface from their outputs, reconciles overlapping findings into single deduplicated records, and runs the chain correlator on top to produce findings no individual engine could produce alone.

The reason MedusaNexus doesn't reinvent any of these tools is that the tools aren't the problem. The problem is the connective tissue between them — and that's the only thing the platform builds itself.

> The mistake the mobile-security space made for a decade was searching for the single-best-tool. The shift over the last few years has been to accept that the tools are good enough; the work that adds value is the orchestration. MedusaNexus's bet is that an orchestrator that produces *one truth* from *five perspectives* is a better investment than the next single-best-tool that comes along.

---

**Next in the series →** *Five small bugs, one critical chain — anatomy of a 1-click account takeover.* The article that walks through a complete real-world chain — deeplink router + applink bridge + javascript whitelist + intent redirection + authenticated WebView — and shows how MedusaNexus's chain correlator surfaces it as a single critical finding.

---

*The series continues weekly on [Medium](https://medium.com/@jacksonfdam/). For deeper coverage of the foundational tools — `APK Decompiling — the dark art`, `Command-Line Tools` — see the Codex at [Umain Fortress](https://umain-fortress.vercel.app/).*
