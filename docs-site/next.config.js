/**
 * Next.js + Nextra config.
 *
 * Theme config lives in `theme.config.tsx`. Output mode is the default
 * Node build because we run a `prebuild` Python step that emits MDX
 * (the auto-gen CLI / REPL / API reference) — static export would
 * still work, we just don't pin to it.
 */

const withNextra = require('nextra')({
  theme: 'nextra-theme-docs',
  themeConfig: './theme.config.tsx',
  defaultShowCopyCode: true,
  staticImage: true,
  // Search the table of contents — useful for the long reference pages.
  flexsearch: {
    codeblocks: true,
  },
});

module.exports = withNextra({
  reactStrictMode: true,
  // Keep build deterministic on Vercel — the Python prebuild already
  // generates content, so we don't need next.js to scan stuff we'll
  // overwrite.
  output: 'standalone',
});
