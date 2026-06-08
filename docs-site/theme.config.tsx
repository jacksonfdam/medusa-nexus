import React from 'react';
import type { DocsThemeConfig } from 'nextra-theme-docs';
import { useRouter } from 'next/router';

/**
 * MedusaNexus docs theme.
 *
 * Cyberpunk palette (cyan / magenta) inherited from the REPL banner and
 * the in-app SPA so the docs feel like one product. The trident emoji
 * stands in for the wordmark; replace `public/logo.svg` to swap.
 */

const REPO = 'https://github.com/jackson-mafra/MedusaNexus';

const Logo = () => (
  <span
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.55rem',
      fontWeight: 700,
      letterSpacing: '0.02em',
    }}
  >
    <span style={{ fontSize: '1.3rem' }} aria-hidden>🔱</span>
    <span style={{
      backgroundImage: 'linear-gradient(90deg, #22d3ee 0%, #f0abfc 100%)',
      WebkitBackgroundClip: 'text',
      WebkitTextFillColor: 'transparent',
      backgroundClip: 'text',
    }}>
      MEDUSA&nbsp;NEXUS
    </span>
    <span style={{
      fontWeight: 500,
      fontSize: '0.78rem',
      color: '#7dd3fc',
      opacity: 0.75,
    }}>
      / docs
    </span>
  </span>
);

const config: DocsThemeConfig = {
  logo: <Logo />,
  project: { link: REPO },
  docsRepositoryBase: `${REPO}/blob/main/docs-site`,
  chat: { link: '' },
  footer: {
    text: (
      <span style={{ opacity: 0.7, fontSize: '0.85rem' }}>
        Built local-first · MIT license ·{' '}
        <a href={REPO} target="_blank" rel="noreferrer" style={{ color: '#22d3ee' }}>
          source on GitHub
        </a>{' '}
        · every head sees a different angle
      </span>
    ),
  },
  head: () => {
    const { asPath } = useRouter();
    const title = 'MedusaNexus — unified mobile threat analysis';
    const description =
      'Drop an APK or IPA, watch every static engine + Frida hook + Burp/Caido/Moxy session correlate findings into one mitigation-ready report. Docs, walkthroughs, API + CLI + MCP reference.';
    const url = `https://medusanexus.dev${asPath}`;
    return (
      <>
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <meta property="og:title" content={title} />
        <meta property="og:description" content={description} />
        <meta property="og:url" content={url} />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="theme-color" content="#0e1117" />
        <link rel="icon" href="/favicon.svg" />
      </>
    );
  },
  useNextSeoProps() {
    return { titleTemplate: '%s · MedusaNexus docs' };
  },
  sidebar: {
    defaultMenuCollapseLevel: 1,
    toggleButton: true,
  },
  toc: {
    backToTop: true,
  },
  editLink: {
    text: 'Edit this page on GitHub →',
  },
  feedback: {
    content: 'Found a bug or stale doc? Open an issue →',
    labels: 'documentation',
  },
  nextThemes: {
    defaultTheme: 'dark',
  },
  primaryHue: 188,            // cyan
  primarySaturation: 90,
  banner: {
    key: 'alpha-2026',
    text: (
      <span>
        ⚡ <strong>Alpha</strong> — full Android pipeline + iOS toolkit + live dynamic loop. API still shifting; pin to commits in CI.
      </span>
    ),
  },
};

export default config;
