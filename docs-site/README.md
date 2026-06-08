# MedusaNexus docs site

Nextra 4 + Next.js 16 + MDX, hosted on Vercel at
**[mnexus.vercel.app](https://mnexus.vercel.app)**.

The site is a thin presentation layer over the MDX files in
`content/`. The CLI / REPL / API reference pages are *generated from
the Python source* at build time, so they can't drift.

## Local development

```bash
cd docs-site
npm install
npm run dev
```

`npm run dev` runs `predev` first — `python3 scripts/gen_reference.py` —
which regenerates `content/reference/cli.mdx`, `repl.mdx`, and
`api/<tag>.mdx` from the live `mnexus` package. The dev server then
boots on http://localhost:3030.

`npm run build` does the same prebuild step before the production build,
so the deployed site can't ever show stale reference.

## File layout

```
docs-site/
├── app/                  ← App Router shell (Nextra 4)
│   ├── layout.tsx        ← Navbar, footer, theme, metadata
│   └── [[...mdxPath]]/   ← Catch-all MDX route
│       └── page.tsx
├── content/              ← Source of truth — MDX
│   ├── _meta.json        ← Top-level sidebar
│   ├── index.mdx         ← Landing page
│   ├── getting-started/  ← Install, requirements, env, first scan
│   ├── workflows/        ← Analyst stories
│   ├── integrations/     ← Per-tool wiring
│   ├── reference/        ← Architecture + auto-generated CLI/REPL/API
│   └── design/           ← Spec, design language, historical plans
├── scripts/
│   └── gen_reference.py  ← Click + SLASH_COMMANDS + OpenAPI walker
├── mdx-components.js     ← Theme bridge
├── next.config.mjs
├── package.json          ← prebuild = predev = gen_reference.py
├── theme.config / styles ← Cyberpunk palette (cyan→magenta)
├── tsconfig.json
└── vercel.json
```

## Vercel deployment

The site is configured to deploy from `docs-site/` on every push to
`main`. To wire it up:

1. **Import the repo** in the Vercel dashboard. Pick this directory
   (`docs-site/`) as the project root — Vercel will detect the
   framework as Next.js.
2. **Build command:** `npm run build` (already declared in
   `vercel.json`).
3. **Output directory:** `.next` (default).
4. **Install command:** `npm install`.
5. **Environment:**
   * `PYTHON_VERSION=3.11` (or 3.12 — Vercel's Node runtime ships
     Python 3.x for the `predev` / `prebuild` hooks).
6. **Domain:** point a CNAME at the Vercel project. The expected canon
   is `mnexus.vercel.app`.

If the build step ever fails to run Python, the previously generated
reference MDX is committed to the deploy preview — pages stay
visible, just slightly stale, until the next successful build.

## Editing content

Plain MDX. Tables, callouts, tabs, code blocks all work. To add a new
page:

```bash
# 1. Create the file in the right bucket
echo "---\ntitle: My new page\n---\n# My new page" > content/workflows/my-thing.mdx

# 2. Add to the sidebar
$EDITOR content/workflows/_meta.json
```

To preview locally:

```bash
npm run dev
open http://localhost:3030/workflows/my-thing
```

## Regenerating reference manually

```bash
python3 scripts/gen_reference.py
```

Writes:
* `content/reference/cli.mdx`
* `content/reference/repl.mdx`
* `content/reference/api/<tag>.mdx` (one per URL prefix)
* `content/reference/api/_meta.json`

These files are gitignored — they regenerate on every build.

## Linking back to the repo

* Wordmark in the navbar links to the GitHub repo.
* Every page footer has an "Edit this page on GitHub →" link pointing
  at `content/<path>.mdx`.
* Internal links use absolute paths (`/workflows/dynamic`) so they
  work both on the live site and when navigating the markdown in your
  editor.
