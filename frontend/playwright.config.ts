import { defineConfig, devices } from '@playwright/test'

/** E2E against the local stack: the public shared lab (backend :8000 in DP_AUTH_MODE=public on a
 * throwaway SQLite copy of the demo lab, see scripts/e2e_backend.py) and Vite :5173. */
const py = process.env.DP_E2E_PYTHON ?? (process.platform === 'win32' ? '..\\backend\\.venv\\Scripts\\python.exe' : '../backend/.venv/bin/python')

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    // Optional: a Chromium already on the machine instead of `npx playwright install`.
    launchOptions: process.env.DP_E2E_CHROMIUM ? { executablePath: process.env.DP_E2E_CHROMIUM } : {},
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 860 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: `${py} ../scripts/e2e_backend.py --port 8000 --fresh`,
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
    },
    { command: 'npm run dev', url: 'http://localhost:5173', reuseExistingServer: !process.env.CI, timeout: 60_000 },
  ],
})
