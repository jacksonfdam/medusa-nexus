# Credits

## Author

**Jackson Mafra** — Mobile Threat Engineer @ Umain.

- https://github.com/jacksonmafra-umain
- https://github.com/jacksonfdam

## Built on the shoulders of other people's research

MEDUSA NEXUS is an orchestration layer. The heavy lifting belongs to the people and projects listed below.

| Project | Author(s) | Role in MEDUSA NEXUS |
|---|---|---|
| [Medusa](https://github.com/Ch0pin/medusa) | [ch0pin](https://github.com/Ch0pin) | Dynamic instrumentation recipe framework — the brainstem of the dynamic engine. |
| [Stheno](https://github.com/Ch0pin/Stheno) | [ch0pin](https://github.com/Ch0pin) | APK patching — gadget injection, pinning/root-detection neutering. |
| [JADX](https://github.com/skylot/jadx) | [Skylot](https://github.com/skylot) | Decompilation + indexed code browsing. |
| [Ghidra](https://github.com/NationalSecurityAgency/ghidra) | NSA | Headless native-lib analysis. |
| [MobSF](https://github.com/MobSF/Mobile-Security-Framework-MobSF) | Ajin Abraham + contributors | Automated static scan. |
| [Frida](https://frida.re) | Ole André Vadla Ravnås + contributors | Dynamic instrumentation runtime. |
| [Burp Suite](https://portswigger.net/burp) | PortSwigger | HTTP interception + scanning. |
| [APKTool](https://apktool.org/) | iBotPeaches + contributors | Manifest + resource decoding. |
| `adb` | AOSP | Device bridge and package pull. |

MEDUSA NEXUS does not fork, rewrite, or compete with any of these. It makes them talk to each other.

## Visual reference

UI aesthetic inspired by the `CyberpunkHackersToolkit` Android project (local reference): pure black canvas, neon cyan + acid green + magenta, Courier Prime monospace, CRT scanlines and glitch. Captured and adapted in [`docs/DESIGN_LANGUAGE.md`](docs/DESIGN_LANGUAGE.md).
