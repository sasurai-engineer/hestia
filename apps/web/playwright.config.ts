import { defineConfig } from '@playwright/test';

/**
 * The end-to-end walk: a REAL browser against the REAL stack (postgres +
 * API + built web app). CI boots all three; locally, run scripts/dev.sh
 * first and `pnpm --filter @hestia/web e2e`.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  // One worker, always: both spec files write to the same real database, and
  // two files interleaving on a shared world is the exact species of ordering
  // bug that turned main red once already. Determinism over a minute saved.
  workers: 1,
  // The CI budget covers what is genuinely slower there — a cold production
  // server, a cold uvicorn, a first-touch database on a 2-core runner — and
  // nothing else. It was 15s while it also absorbed the read-your-writes
  // race (#78); #83 fixed that at the root, so the budget came down (#91).
  // Evidence from green runs at 10s is what justifies the next step down.
  expect: { timeout: process.env.CI ? 10_000 : 5_000 },
  use: {
    baseURL: process.env.HESTIA_WEB_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
  },
  webServer: process.env.CI
    ? {
        command: 'pnpm start',
        url: 'http://localhost:3000',
        timeout: 60_000,
        reuseExistingServer: false,
      }
    : undefined,
});
