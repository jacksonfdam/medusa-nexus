/**
 * Next.js 16 + Nextra 4 config.
 *
 * Nextra 4 ships an MDX plugin that wraps next-config with content
 * discovery, search, and the App Router layout adapter. Our extra
 * twist is the `prebuild` Python step that regenerates the CLI / REPL
 * / API reference pages under content/reference/ — guaranteed to
 * track the source code at every deploy.
 */

import nextra from 'nextra';

const withNextra = nextra({
  search: {
    codeblocks: true,
  },
  defaultShowCopyCode: true,
  staticImage: true,
  contentDirBasePath: '/',
});

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
};

export default withNextra(config);
