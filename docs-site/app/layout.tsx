/**
 * Root layout — Nextra 4 App Router bootstrap.
 *
 * Owns the global `<html>` shell, the cyberpunk-flavoured header / footer,
 * theme persistence, and the cyan→magenta wordmark. The page contents
 * flow through the catch-all `[[...mdxPath]]/page.tsx` route.
 */

import type { Metadata } from 'next';
import { Layout, Navbar, Footer } from 'nextra-theme-docs';
import { Head } from 'nextra/components';
import { getPageMap } from 'nextra/page-map';
import 'nextra-theme-docs/style.css';
import '../styles/globals.css';

const REPO = 'https://github.com/jackson-mafra/MedusaNexus';

export const metadata: Metadata = {
  metadataBase: new URL('https://medusanexus.dev'),
  title: {
    default: 'MedusaNexus — unified mobile threat analysis',
    template: '%s · MedusaNexus docs',
  },
  description:
    'Drop an APK or IPA, watch every static engine + Frida hook + Burp/Caido/Moxy session correlate findings into one mitigation-ready report. Docs, walkthroughs, API + CLI + MCP reference.',
  applicationName: 'MedusaNexus',
  themeColor: '#0e1117',
  icons: [{ rel: 'icon', url: '/favicon.svg' }],
  openGraph: {
    type: 'website',
    siteName: 'MedusaNexus',
    locale: 'en_US',
  },
  twitter: { card: 'summary_large_image' },
};

function Logo() {
  return (
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
}

const navbar = (
  <Navbar
    logo={<Logo />}
    projectLink={REPO}
  />
);

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
          navbar={navbar}
          footer={footer}
          editLink="Edit this page on GitHub →"
          docsRepositoryBase={`${REPO}/blob/main/docs-site/content`}
          sidebar={{ defaultMenuCollapseLevel: 1, toggleButton: true }}
          toc={{ backToTop: true }}
          feedback={{
            content: 'Found a bug or stale doc? Open an issue →',
            labels: 'documentation',
          }}
          pageMap={pageMap}
          banner={
            <span>
              ⚡ <strong>Alpha</strong> — full Android pipeline + iOS toolkit + live dynamic loop. API still shifting; pin to commits in CI.
            </span>
          }
          themeSwitch={{ light: 'Light', dark: 'Dark', system: 'System' }}
          nextThemes={{ defaultTheme: 'dark' }}
        >
          {children}
        </Layout>
      </body>
    </html>
  );
}
