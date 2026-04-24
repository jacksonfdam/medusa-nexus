# 🔱 MEDUSA NEXUS

*Unified Mobile Threat Analysis Platform.*
*Every head sees a different angle.*

`mnexus` is the orchestrator your APK never asked for. It doesn't reinvent JADX, Ghidra, MobSF, Frida, Medusa, Stheno, Burp or APKTool — it makes them stop pretending they don't know each other, sits them down at one SQLite-backed table, and watches them correlate findings like adults.

## What it does

1. **You drop an APK** (or pull one off a device with one click).
2. **Static engines run in parallel** — JADX decompiles, MobSF lectures, Ghidra dissects the `.so` files, a secrets scanner finds the API key that's been hardcoded since 2019.
3. **The attack surface gets built** — exported components, deep links, crypto primitives, pinning libs, root-detection libs, the works.
4. **Frida hooks get auto-generated** based on what static analysis actually found. No more copy-pasting `universal-ssl-pinning-bypass.js` from Stack Overflow.
5. **You run the dynamic session**. Traffic routes through Burp, Medusa recipes load, Stheno patches the APK if needed, every crypto call and intent gets logged.
6. **Correlation layer confirms findings** — static suspicion + dynamic evidence = a finding with a confidence level your client will take seriously.
7. **Reports ship with mitigation.** Not "improve security posture". Actual before/after code.

## Status

**Pre-code.** The repo currently contains the product spec, the design language, and (soon) the full Pencil UI deck covering 31 screens. Python orchestrator, FastAPI, and React frontend land after the design is locked.

## Structure

| Path | What lives here |
|---|---|
| `docs/SPEC.md` | Full product specification (architecture, engines, CLI, pipeline). |
| `docs/DESIGN_LANGUAGE.md` | Visual tokens, typography, effects — extracted from the reference aesthetic. |
| `design/system/` | Design system exports (tokens, components). |
| `design/screens/` | Per-screen PNG exports, organized by group. |
| `design/INDEX.md` | Index of every designed screen. |
| `CREDITS.md` | Author and upstream acknowledgements. |

## Author

**Jackson Mafra** — Mobile Threat Engineer @ Umain.
[@jacksonmafra-umain](https://github.com/jacksonmafra-umain) · [@jacksonfdam](https://github.com/jacksonfdam)

See [CREDITS.md](CREDITS.md) for full acknowledgements.

## License

TBD — everything here is currently private and opinionated.
