import { defineConfig, devices } from '@playwright/test'

/**
 * Two kinds of end-to-end tests:
 *
 * - `smoke` (CI, `npm run e2e`): the UI against the Prism mock of the API contract, which
 *   serves the contract's example data. Starts Prism and the Vite dev server in mock mode.
 * - `fakelab` and `screenshots` (local, `npm run e2e:fakelab`): the real stack with the fake
 *   lab (`make fakelab-up fakelab-seed`), at E2E_BASE_URL (default http://127.0.0.1:8080).
 */
const fakelab = Boolean(process.env.E2E_FAKELAB)
const MOCK_UI = 'http://127.0.0.1:5173'

export default defineConfig({
  testDir: './e2e',
  timeout: fakelab ? 180_000 : 30_000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: fakelab ? (process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8080') : MOCK_UI,
    trace: 'retain-on-failure',
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    { name: 'smoke', testMatch: 'smoke.spec.ts', use: { ...devices['Desktop Chrome'] } },
    { name: 'fakelab', testMatch: 'fakelab.spec.ts', use: { ...devices['Desktop Chrome'] } },
    {
      name: 'screenshots',
      testMatch: 'screenshots.spec.ts',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: fakelab
    ? undefined
    : [
        {
          command: 'npm run mock',
          url: 'http://127.0.0.1:4010/api/health',
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
        {
          command: 'npm run dev:mock -- --host 127.0.0.1 --port 5173 --strictPort',
          url: MOCK_UI,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      ],
})
