---
title: "Who attacks your mobile app — and who defends it"
description: "A four-way map of who's looking at your mobile app, where the developer fits, and what makes mobile security genuinely different from web security."
published: 2026-06-09
author: Jackson Mafra
tags: ["mobile-security", "android", "ios", "appsec", "developers", "security-engineering"]
canonical: https://mnexus.vercel.app/articles/01-who-attacks-your-mobile-app
codex_refs:
  - "Mobile Top 10 — https://medium.com/@jacksonfdam/"
  - "Bulletproof Security — https://medium.com/@jacksonfdam/"
medusa_refs:
  - https://github.com/jacksonfdam/medusa-nexus
tldr: |
  Black, Red, and Blue Team aren't synonyms — they're three different jobs with three
  different rule sets. As a mobile developer, you occupy a fourth role: security partner.
  Mobile is different from web because you ship binaries, not endpoints — the OS mediates
  trust, not your server. MedusaNexus is the orchestrator that gives developers Red Team
  eyes without making them Red Teamers. This is the first article in an eight-part series
  on mobile threat analysis for developers.
---

Open the Google Play Console for any app with more than a few thousand installs. There is a tab called "App security & trust" that shows you, in plain English, what attackers have already tried. Most developers never look at it. Most developers also can't precisely tell you the difference between a Red Team and a Blue Team — let alone where they themselves fit in the picture.

That gap is the problem this article is about. Not because the gap is anyone's fault, but because the language we use for mobile security was built by people who do mobile security full time, and it implicitly assumes everyone reading it already knows the players. This series is for developers who ship mobile apps and want to understand the work that happens around them — the people, the rules they play by, and where the developer's own role lives in the picture.

We start with the cast. Then we'll look at why mobile is a genuinely different problem from web security, and where a platform like [MedusaNexus](https://github.com/jacksonfdam/medusa-nexus) — the open-source orchestrator this series is built around — sits in that picture.

## The four-way map

The industry talks about "security" as if it were one job. It isn't. There are at least four distinct roles people play around your mobile app, and the differences between them matter.

**Black Team** — Independent attackers. Motivated by money, ideology, curiosity, or some mix of the three. No contractual scope. Paid by themselves, or by whoever buys the result on a market. Adversarial: treats your app as a target.

**Red Team** — Paid attackers. Contractual scope. Goal is to model what a Black Team would actually do. Paid by your company, or by a client your company hired. Contracted adversarial: treats your app as a target *within agreed limits*.

**Blue Team** — Defenders inside the company. Watches telemetry, hunts intrusions, ships patches. Paid by your company. Defensive: treats your app as something to protect.

**Purple Team** — The bridge. Red and Blue working together, sharing findings in real time. Sometimes a real team, sometimes a workshop format. Paid by your company. Collaborative.

This taxonomy isn't legal — it's operational. The same person can do all four jobs in their career; the rules change with the role.

## Black Team

A Black Team — sometimes called a *threat actor* in formal writing — is someone attacking your app without your permission. They operate on their own timeline and toward their own goals. There's no contract limiting what they can touch, no agreed-on report format, no shared Slack channel. If they find a vulnerability, what they do with it depends on what kind of Black Team they are.

The categories are roughly:

* **Financially-motivated**. Stealing payment credentials, OAuth tokens, session cookies. The flagship pattern is the *overlay attack* — a malicious app draws a fake login screen on top of yours and harvests what the user types. There is a deep dive on this pattern in the Umain Fortress Codex entry *Overlay Attacks*, and a follow-up on *GhostTouch* that shows the input-injection variant.
* **Information-motivated**. Stealing user data — health, location, conversations. Slower payoff than financial fraud but a larger market.
* **Disruption-motivated**. Defacement, denial of service, public embarrassment. Rare against individual mobile apps; common against the platforms they integrate with.
* **Researcher-motivated**. People who break things for the puzzle of breaking them, sometimes responsibly disclose, sometimes don't. The "grey area" of the Black Team category.

What unifies them is that they don't tell you they're there. You learn after the fact, from a fraud-report spike, a leaked credentials database, a Twitter thread. The Blue Team's job, partly, is to shorten the gap between "they got in" and "we noticed."

## Red Team

A Red Team is a contracted adversary. They model what a Black Team would do, but under a written agreement that specifies what they can touch, what they cannot, what they have to report, and who they have to report it to. The output is usually a written assessment delivered in a defined timebox — a "pentest report" in the colloquial sense, though serious Red Team engagements go further than what most people mean by pentest.

The difference between *Red Team* and *penetration test* is mostly one of scope:

* A **penetration test** typically has a narrow, well-defined target — one app, one API, one feature — and a fixed set of tests. The goal is to enumerate findings.
* A **Red Team engagement** has a broader objective — *"can you reach the production database from outside?"* — and the team chooses their own path. The goal is to test whether the defenders notice and respond in time.

For mobile apps specifically, you'll usually encounter penetration tests. A mobile-app pentest produces a list of findings (each with severity, evidence, and ideally a fix), maps them to a framework like the [OWASP MASVS](https://mas.owasp.org/), and hands it to the team that owns the app — which, often, is the team reading this article.

## Blue Team

A Blue Team is the defender inside the building. They run the SIEM, write the detection rules, hunt for indicators of compromise, ship patches, and own the incident-response playbook. Their work is largely invisible to anyone outside the team. When they do their job well, nothing happens — which is also why they're often underfunded.

For mobile apps, the Blue Team's work is split between two places:

* **Server-side defence** — monitoring API endpoints, flagging anomalous request patterns, rotating credentials when something looks off. This is the same job as Blue Team for any backend.
* **Client-side hardening** — *anti-tamper* checks, *root detection*, *certificate pinning*, *Play Integrity* attestation on Android, *DeviceCheck* and the *App Attest* family on iOS. These run on the device, in your app, and decide whether the app should refuse to operate.

The second category is where the Blue Team's work overlaps most with the developer's day-to-day. Adding a `NetworkSecurityConfig.xml` that pins your TLS certificates is Blue Team work. Wiring up Play Integrity is Blue Team work. Choosing not to log the Authorization header is Blue Team work. Codex entries *Bulletproof Security*, *Device Attestation 101*, and *Trust No One* go deep on the patterns that show up here.

## Purple Team

A Purple Team is what you get when the Red and Blue Teams stop working in isolation and start sharing findings in real time. In its strongest form, it's a recurring meeting where the Red Team demonstrates an attack, the Blue Team explains what their tools saw, and both sides debug the gap. In its weakest form, it's a marketing term applied to whatever Red-and-Blue collaboration already happens.

When Purple Teaming works well, it produces detection rules tied directly to attacker techniques, not generic alerts. For mobile apps, this looks like a Red Team demonstrating that they can repackage your APK with `frida-server` baked in and pivot to your backend; the Blue Team then ships a Play Integrity check that catches that exact technique on the next build. The Red Team retests; the Blue Team patches again. The loop is the product.

## Where the developer lives

There is a fifth role that the canonical taxonomy doesn't name, and it's the one most people reading this article occupy: the developer who ships the app.

You're not a Black Team — you're not attacking your own app. You're not a Red Team — your role doesn't include scoped offensive testing as your job description. You're not a Blue Team — you don't sit on the SIEM. You're not Purple — you don't moderate the workshops.

What you do is build the surface that everyone else is reacting to. Every `<intent-filter>` you declare in `AndroidManifest.xml` becomes Red Team scope. Every `addJavascriptInterface()` call becomes a Blue Team detection rule. Every `okhttp` interceptor you forget to add becomes a Black Team opportunity. The developer is the security *cause* — and, very often, the security *fix*.

The shift the industry has been gradually making — sometimes labelled *shift-left*, sometimes *DevSec*, sometimes just *engineering* — is the recognition that the developer needs at least a Red Team-shaped view of their own app, before the Red Team ever gets there. Not the full skill set, not the full toolchain. Enough to spot the obvious gaps, enough to read a finding and know what to do with it, enough to argue back when an external report is wrong.

That's the role this series is written for.

## Why mobile is different from web

The taxonomy above applies to any software, not just mobile. But the *texture* of mobile security is different from web security, and the differences are worth naming before we get any further.

**You ship binaries, not endpoints.** A web app exists on a server you control. A mobile app exists on the user's device, in a binary you handed them. Once it ships, you can't change what code is running until they take an update — which, on average, takes weeks across the install base. Findings in mobile apps live longer than findings in web apps.

**The OS mediates trust, not your code.** When a web app needs to verify the user, it makes a network call to its own server. When a mobile app needs the same thing, it often delegates to the operating system — biometrics, keystore, attestation, integrity APIs. That means a chunk of your security posture lives in code you didn't write, on top of a kernel you don't control. The Codex entries on *Play Integrity attestation* and *Hardware-backed token vault* go deeper on this.

**Permissions are dialogue boxes, not headers.** Web apps negotiate trust through CSP headers, CORS preflights, and CSRF tokens — all of which are server-mediated. Mobile apps negotiate trust through dialog boxes the user dismisses without reading, and through manifest declarations the user never sees. The attack surface is partly defined by the manifest you ship and partly by the user's behaviour when granting runtime permissions.

**Decompilation is trivial.** A motivated attacker can pull your APK from the device, run `apktool` and `jadx`, and read your Java/Kotlin source as if you'd shared the repository. iOS is slightly harder — App Store binaries are FairPlay-encrypted — but the encryption only protects against casual users; a jailbroken phone and `bagbak` or `frida-ios-dump` decrypts in seconds. *APK decompiling — the dark art* in the Codex covers this in detail. The implication: you cannot rely on attackers not understanding your code. Assume they have it.

**The device is hostile.** On a web app, the server is trusted and the client is suspect. On a mobile app, *both* are suspect. A user might have rooted their own device. An adversary might have compromised it. Anti-cheat logic, anti-fraud logic, and anti-tamper logic all live in your app's code path — running on a device that may be lying about its own state. *Root detection in 2026*, *RASP strategies*, and *KernelSU on Android emulators* in the Codex all live on this fault line.

A working summary: web security is mostly about controlling what your server returns. Mobile security is mostly about deciding what your app should refuse to do on a device it can't trust.

## Where MedusaNexus fits

The reason this series is anchored on a specific tool — [MedusaNexus](https://github.com/jacksonfdam/medusa-nexus) — is that the developer's role in security needs *operational ergonomics* to be sustainable. Reading a Red Team report once a year does not move the needle. Looking at your own app the way a Red Team would, on every commit, does.

The space of tools that already exist is large and fragmented. There are decompilers (`jadx`, `apktool`), native-code reversers (Ghidra, IDA, radare2), framework-aware scanners (MobSF), dynamic-instrumentation toolkits (Frida), traffic interceptors (Burp, Caido, Moxy), patcher chains (Stheno), iOS-specific helpers (bagbak, frida-ios-dump, ldid). Every one of them does its job well in isolation. None of them, individually, gives a developer a complete picture.

MedusaNexus's premise is that the *orchestration* between these tools is the missing piece. Sit them all down at one SQLite-backed table, let each contribute its findings, run an intelligence layer on top that correlates the findings into chains, and present the result as one *attack surface* per project. That single picture is what an analyst would build by hand over a week of work; the tool's job is to build it in two minutes and keep it current as the app evolves.

From the four-way map, MedusaNexus sits at the boundary between Red and Blue Team capabilities, exposed to the developer:

* It runs the same static-analysis chain a **Red Team** would run during a mobile pentest — decompile, surface map, deeplink enumeration, native-library triage, secret scanning, attack-chain correlation.
* It produces output in the shape a **Blue Team** consumes — every finding carries a CWE reference, an OWASP MASVS control, and a mandatory remediation block. Reports map to the same MASVS matrix a defence team uses to track coverage.
* And it integrates into the surface a **developer** already lives in — a CLI, a REPL, a web UI, JSON output for CI pipelines, an MCP server so an AI assistant can drive the analysis.

Future articles in this series walk through each of those surfaces. Article 2 is a vocabulary piece — every term we'll use for the rest of the series, defined precisely. Article 3 walks the first scan end to end. Article 4 explains the orchestration philosophy. Article 5 dissects a complete attack chain — five small bugs that combine into a one-click account takeover.

## TL;DR

Black, Red, and Blue are three different jobs, not three synonyms for "hacker." Black Teams attack without permission, Red Teams attack with one, Blue Teams defend from inside. Purple is the workshop where the two halves debug their disagreements together.

Developers occupy a fifth role the canonical taxonomy doesn't name — *security partner* — and that role grows in importance the more mobile-specific your app's risk surface becomes. Mobile is genuinely different from web: you ship binaries, the OS mediates trust, your code runs on hostile hardware, and decompilation is trivial. The security posture lives in code you wrote and code you didn't, on devices you don't control.

MedusaNexus is the orchestrator for the developer's side of that boundary — a single tool that gives you Red Team-shaped eyes on your own app without requiring you to become a Red Teamer. The rest of the series is hands-on: you'll install it, scan your first APK, learn the language of mobile findings, and watch five small bugs combine into one critical chain.

> The most important shift in mobile security over the last decade hasn't been a new attack class or a new defence. It's been the recognition that the developer building the app and the engineer auditing it can — and should — be the same person on different days of the week. Tools like MedusaNexus exist to make that shift practical, not aspirational.

---

**Next in the series →** *The vocabulary — every term you need to read a mobile threat report.* We define every term this series uses from scratch: *attack surface, finding, severity, CWE, OWASP MASVS, static vs dynamic analysis, decompilation vs disassembly, intent, intent-filter, deeplink, scheme, action, category, activity, service, receiver, provider, bundle, Info.plist, entitlement, hook, Frida, instrumentation, mitigation playbook*. Bookmark it; the rest of the series will reference it.

---

*Found this useful? The series continues weekly on [Medium](https://medium.com/@jacksonfdam/). The companion repository for MedusaNexus is on [GitHub](https://github.com/jacksonfdam/medusa-nexus). For deep dives on specific mobile-attack patterns — overlay attacks, GhostTouch, attestation, root detection — see the Codex at [Umain Fortress](https://umain-fortress.vercel.app/).*
