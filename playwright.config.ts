import { defineConfig, devices } from "@playwright/test";

const frontendPort = 3005;
const backendPort = 8005;
const pythonBin = process.env.PYTHON_BIN || "../../.venv/bin/python";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `cd apps/api && APP_AUTO_CREATE_TABLES=true APP_AUTO_SEED_SYSTEM=true APP_RUN_SCHEDULER=0 CORS_ORIGINS=http://127.0.0.1:${frontendPort} SCRAPE_FIXTURE_DIR=../../tests/e2e/fixtures/scrape ${pythonBin} -c "import asyncio; from main import _maybe_create_tables; asyncio.run(_maybe_create_tables())" && APP_AUTO_CREATE_TABLES=true APP_AUTO_SEED_SYSTEM=true APP_RUN_SCHEDULER=0 CORS_ORIGINS=http://127.0.0.1:${frontendPort} SCRAPE_FIXTURE_DIR=../../tests/e2e/fixtures/scrape ${pythonBin} -m uvicorn main:app --host 127.0.0.1 --port ${backendPort}`,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
    {
      command: `cd apps/web && NEXT_PUBLIC_API_URL=http://127.0.0.1:${backendPort}/api npm run build && NEXT_PUBLIC_API_URL=http://127.0.0.1:${backendPort}/api npm run start -- --hostname 127.0.0.1 --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
      timeout: 120_000,
    },
  ],
});
