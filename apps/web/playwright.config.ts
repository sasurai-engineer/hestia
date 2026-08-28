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
  // A cold production server, a cold uvicorn and a database seeing each query
  // for the first time are all slower than a warm dev box, and every one of
  // these assertions reads a row a POST has just created. Five seconds is the
  // Playwright default and it is a local-machine default; the failures it
  // produced on CI were timing, not truth. The test timeout above still caps
  // a genuinely stuck expectation.
  expect: { timeout: process.env.CI ? 15_000 : 5_000 },
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
