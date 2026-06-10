/**
 * Root layout — Nextra 4 App Router bootstrap.
 *
 * Follows the canonical example from nextra.site: import Layout/Navbar/Footer
 * from `nextra-theme-docs`, Banner/Head from `nextra/components`, and feed
 * Banner as a real `<Banner>` element (not a bare `<span>` — the docs Layout
 * validates its props with a strict Zod schema that's happier with the typed
 * elements).
 */

import type { Metadata, Viewport } from 'next';
import { Footer, Layout, Navbar } from 'nextra-theme-docs';
import { Banner, Head } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import 'nextra-theme-docs/style.css';
import '../styles/globals.css';
import { Analytics } from "@vercel/analytics/next"

const REPO = 'https://github.com/jacksonfdam/medusa-nexus';

export const metadata: Metadata = {
  metadataBase: new URL('https://mnexus.vercel.app'),
  title: {
    default: 'MedusaNexus — unified mobile threat analysis',
    template: '%s · MedusaNexus docs',
  },
  description:
    'Drop an APK or IPA, watch every static engine + Frida hook + Burp/Caido/Moxy session correlate findings into one mitigation-ready report. Docs, walkthroughs, API + CLI + MCP reference.',
  applicationName: 'MedusaNexus',
  icons: [{ rel: 'icon', url: '/favicon.svg' }],
  openGraph: {
    type: 'website',
    siteName: 'MedusaNexus',
    locale: 'en_US',
  },
  twitter: { card: 'summary_large_image' },
};

// Next.js 14+: themeColor lives in `viewport` export, not `metadata`.
export const viewport: Viewport = {
  themeColor: '#0e1117',
};

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
    <span style={{ fontSize: '1.3rem' }} aria-hidden>
      🔱
    </span>
    <span
      style={{
        backgroundImage: 'linear-gradient(90deg, #22d3ee 0%, #f0abfc 100%)',
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
      }}
    >
      MEDUSA&nbsp;NEXUS
    </span>
    <span
      style={{
        fontWeight: 500,
        fontSize: '0.78rem',
        color: '#7dd3fc',
        opacity: 0.75,
      }}
    >
      / docs
    </span>
  </span>
);

const banner = (
  <Banner storageKey="mnexus-alpha-2026">
    ⚡ <strong>Alpha</strong> — full Android pipeline + iOS toolkit + live dynamic loop. API still shifting; pin to commits in CI.
  </Banner>
);

const navbar = <Navbar logo={<Logo />} projectLink={REPO} />;

const footer = (
  <Footer>
    <span style={{ opacity: 0.7, fontSize: '0.85rem' }}>
      Built local-first · MIT license ·{' '}
      <a href={REPO} target="_blank" rel="noreferrer" style={{ color: '#22d3ee' }}>
        source on GitHub
      </a>{' '}
      · every head sees a different angle
    </span>
  </Footer>
);

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const pageMap = await getPageMap();
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <Head />
      <body>
        <Layout
          banner={banner}
          navbar={navbar}
          pageMap={pageMap}
          docsRepositoryBase={`${REPO}/blob/main/docs-site/content`}
          footer={footer}
          editLink="Edit this page on GitHub →"
          sidebar={{ defaultMenuCollapseLevel: 1, toggleButton: true }}
          feedback={{ content: 'Found a bug or stale doc? Open an issue →', labels: 'documentation' }}
          nextThemes={{ defaultTheme: 'dark' }}
        >
          {children}
        </Layout>
        {/*
          Vercel Analytics — pageview + visitor counters surfaced in the
          Vercel dashboard. Renders as a near-zero-size script tag; injects
          its own `<script>` only when running on Vercel infrastructure
          (the client checks `VERCEL_ENV` at runtime, so local dev stays
          telemetry-free).
        */}
        <Analytics />
      </body>
    </html>
  );
}
