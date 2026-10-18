import { defineConfig, devices } from "@playwright/test";

// End-to-end tests drive the real frontend against the real backend (no mocks).
// Both servers are started automatically unless they are already running.
const python = process.env.AGENTVAULT_E2E_PYTHON ?? (process.platform === "win32" ? ".venv\\Scripts\\python.exe" : "python");
const e2eDb = process.env.AGENTVAULT_E2E_DATABASE_URL ?? "sqlite:///./data/e2e.db";
// A dedicated port with --strictPort, so the tests never silently reuse an unrelated dev server.
const webPort = Number(process.env.AGENTVAULT_E2E_WEB_PORT ?? 5179);
const apiPort = Number(process.env.AGENTVAULT_E2E_API_PORT ?? 8000);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${apiPort}/api/v1/ready`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { AGENTVAULT_DATABASE_URL: e2eDb, AGENTVAULT_ENVIRONMENT: "test" },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { AGENTVAULT_API_PROXY: `http://127.0.0.1:${apiPort}` },
    },
  ],
});
