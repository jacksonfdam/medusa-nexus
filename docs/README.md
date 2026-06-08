# Documentation moved → `docs-site/`

The docs now live as a deployable Vercel site under
[`../docs-site/`](../docs-site/), authored in MDX, with auto-generated
CLI / REPL / API reference at build time.

**Hosted site (when deployed):** https://medusanexus.dev

**Source of truth (markdown):** [`docs-site/content/`](../docs-site/content/)

**Old → new mapping**

| Old path | New page |
| -------- | -------- |
| `docs/SPEC.md`           | [`design/spec`](../docs-site/content/design/spec.mdx) |
| `docs/QUICKSTART.md`     | [`getting-started/quickstart`](../docs-site/content/getting-started/quickstart.mdx) |
| `docs/RUNTIME.md`        | [`workflows/dynamic`](../docs-site/content/workflows/dynamic.mdx) |
| `docs/IOS.md`            | [`workflows/ios`](../docs-site/content/workflows/ios.mdx) |
| `docs/IOS_PLAN.md`       | [`design/ios-plan`](../docs-site/content/design/ios-plan.mdx) |
| `docs/PIPELINES.md`      | [`workflows/pipelines`](../docs-site/content/workflows/pipelines.mdx) |
| `docs/REPORTING.md`      | [`workflows/reporting`](../docs-site/content/workflows/reporting.mdx) |
| `docs/PLAYINTEL.md`      | [`workflows/playintel`](../docs-site/content/workflows/playintel.mdx) |
| `docs/MOXY.md`           | [`integrations/moxy`](../docs-site/content/integrations/moxy.mdx) |
| `docs/VPHONE_PLAN.md`    | [`integrations/vphone`](../docs-site/content/integrations/vphone.mdx) |
| `docs/MCP.md`            | [`integrations/mcp`](../docs-site/content/integrations/mcp.mdx) |
| `docs/DESIGN_LANGUAGE.md` | [`design/design-language`](../docs-site/content/design/design-language.mdx) |

## Why move

* Vercel-native build (Nextra 4 + Next.js 16) — one `git push` deploys
  the docs.
* Auto-generated CLI / REPL / API reference can never go stale —
  `npm run prebuild` regenerates from the Python source at deploy time.
* MDX components (callouts, cards, tabs) work natively. Plain markdown
  still renders without changes — `.md → .mdx` was a pure rename.
* Search + dark mode + ToC + edit-on-GitHub links are free.

Browse [`docs-site/`](../docs-site/) for the new layout, or read the
quickstart at the very root of the repo: [`../README.md`](../README.md).
