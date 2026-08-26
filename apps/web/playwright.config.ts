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
