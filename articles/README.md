# MedusaNexus — companion article series

Eight technical articles, written for developers who don't yet think of
themselves as security people, that build from foundational concepts up
through hands-on use of the platform. Each article stands alone but
compounds with the rest.

The articles are kept here as plain Markdown (not MDX) so they paste
directly into Medium, LinkedIn, or any blog importer without conversion.
For the docs side of things, see [`../docs-site/`](../docs-site/).

| # | Title | Audience | Status |
| - | ----- | -------- | ------ |
| 01 | [Who attacks your mobile app — and who defends it](01-who-attacks-your-mobile-app.md) | Developers entering mobile security | Drafted |
| 02 | [The vocabulary — every term you need to read a mobile threat report](02-the-vocabulary.md) | Developers + first-time auditors | Drafted |
| 03 | [Your first APK scan, end to end — in 10 minutes](03-your-first-apk-scan.md) | Developers | Drafted |
| 04 | [Five tools, one truth — how MedusaNexus orchestrates static analysis](04-five-tools-one-truth.md) | Engineers curious about orchestration | Drafted |
| 05 | [Five small bugs, one critical chain — anatomy of a 1-click account takeover](05-five-small-bugs-one-critical-chain.md) | Security-curious devs | Drafted |
| 06 | [Shift-left mobile security — block bad commits with one YAML](06-shift-left-block-bad-commits.md) | DevSec / platform engineers | Drafted |
| 07 | [Let your AI assistant run the security review — MCP for mobile audits](07-ai-assistant-mobile-security-review.md) | AI-curious engineers | Drafted |
| 08 | [iOS without a jailbroken iPhone — what's possible and what isn't](08-ios-without-a-jailbroken-iphone.md) | iOS developers | Drafted |

## Voice

Formal yet accessible. Developer-first audience, security researchers
secondary. Informative not alarmist. Concrete platform features open
each piece; code blocks live inline; every article ends with an
actionable summary plus a blockquoted broader takeaway. The tone
follows [Jackson Mafra's Medium](https://medium.com/@jacksonfdam/)
verbatim — these articles are continuous with that catalogue, not a
detour from it.

## Cross-link strategy

Each article references one or two pieces from
[Umain Fortress's Codex](https://umain-fortress.vercel.app/) where the
reader can deepen on a specific topic — overlay attacks, attestation,
RASP, root detection, etc. The articles in this series introduce
foundational concepts and walk through MedusaNexus; the Codex provides
the depth on any single attack or defence the articles touch.

## Publishing

* **Canonical**: hosted alongside the docs at
  `https://mnexus.vercel.app/articles/<slug>` once the Vercel routing
  picks them up (planned for after the series is complete).
* **Medium**: paste the Markdown straight into the Medium import URL.
  Frontmatter becomes the post metadata.
* **LinkedIn**: a short excerpt + link to the canonical URL.

## Cadence

One article per week, in order. Each article ships ready to publish —
frontmatter complete, code blocks tested, cross-links live.
