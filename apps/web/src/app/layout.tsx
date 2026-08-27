import type { Metadata } from 'next';
import { Bitter, IBM_Plex_Mono, IBM_Plex_Sans } from 'next/font/google';
import type { ReactNode } from 'react';
import './globals.css';

// Hestia's own voices — the consultancy's typefaces may not appear in this
// product, and the livery test enforces the ban by name. Bitter: a warm
// contemporary slab, brick-solid, the hearth's voice. IBM Plex Sans + Mono:
// one family for dense UI text and tabular ledger figures. Self-hosted at
// build time by next/font: zero runtime requests to any font host.
const bitter = Bitter({ subsets: ['latin'], variable: '--font-display' });
const plexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-ui',
});
const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
});

export const metadata: Metadata = {
  title: 'Hestia',
  description: "The owner's operating platform for real property.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${bitter.variable} ${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <div className="shell">
          <header className="masthead">
            <a className="masthead__wordmark" href="/">
              Hestia
            </a>
            <nav className="masthead__nav" aria-label="Primary">
              <a href="/">Portfolio</a>
              <a href="/leases">Leases</a>
              <a href="/transactions">Transactions</a>
              <a href="/documents">Documents</a>
              <a href="/maintenance">Maintenance</a>
              <a href="/vendors">Vendors</a>
              <a href="/reports">Reports</a>
              <a href="/calendar">Calendar</a>
              <a href="/coverage">Coverage</a>
            </nav>
          </header>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
