import { defineConfig, devices } from "@playwright/test";

const useExistingServer = process.env.PLAYWRIGHT_USE_EXISTING_SERVER === "1";
const frontendPort = Number(process.env.PLAYWRIGHT_FRONTEND_PORT || (useExistingServer ? "3000" : "3005"));
const backendPort = Number(process.env.PLAYWRIGHT_BACKEND_PORT || (useExistingServer ? "8000" : "8005"));
const frontendBaseUrl = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${frontendPort}`;
const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || `http://127.0.0.1:${backendPort}/api`;
const pythonBin = process.env.PYTHON_BIN || "../../.venv/bin/python";
const llmRequired = process.env.LLM_REQUIRED || "0";
const localEnvFile = process.env.LOCAL_ENV_FILE || "/tmp/opentutor_playwright.env";
const bootstrapLlmFromEnv = process.env.BOOTSTRAP_LLM_FROM_ENV === "1";
const backendLlmEnv = bootstrapLlmFromEnv
  ? 'OPENAI_API_KEY="${OPENAI_API_KEY:-}" ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}" OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}" GEMINI_API_KEY="${GEMINI_API_KEY:-}" GROQ_API_KEY="${GROQ_API_KEY:-}"'
  : "OPENAI_API_KEY= ANTHROPIC_API_KEY= DEEPSEEK_API_KEY= OPENROUTER_API_KEY= GEMINI_API_KEY= GROQ_API_KEY=";

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
    baseURL: frontendBaseUrl,
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
  webServer: useExistingServer
    ? undefined
    : [
        {
          command: `cd apps/api && rm -f ${localEnvFile} && touch ${localEnvFile} && LOCAL_ENV_FILE=${localEnvFile} ${backendLlmEnv} APP_AUTO_CREATE_TABLES=true APP_AUTO_SEED_SYSTEM=true APP_RUN_SCHEDULER=0 CORS_ORIGINS=http://127.0.0.1:${frontendPort} SCRAPE_FIXTURE_DIR=../../tests/e2e/fixtures/scrape LLM_REQUIRED=${llmRequired} ${pythonBin} -c "import asyncio; from main import _maybe_create_tables; asyncio.run(_maybe_create_tables())" && LOCAL_ENV_FILE=${localEnvFile} ${backendLlmEnv} APP_AUTO_CREATE_TABLES=true APP_AUTO_SEED_SYSTEM=true APP_RUN_SCHEDULER=0 CORS_ORIGINS=http://127.0.0.1:${frontendPort} SCRAPE_FIXTURE_DIR=../../tests/e2e/fixtures/scrape LLM_REQUIRED=${llmRequired} ${pythonBin} -m uvicorn main:app --host 127.0.0.1 --port ${backendPort}`,
          url: `${apiBaseUrl}/health`,
          reuseExistingServer: false,
          stdout: "ignore",
          stderr: "pipe",
          timeout: 120_000,
        },
        {
          command: `cd apps/web && NEXT_PUBLIC_API_URL=${apiBaseUrl} npm run build && NEXT_PUBLIC_API_URL=${apiBaseUrl} npm run start -- --hostname 127.0.0.1 --port ${frontendPort}`,
          url: frontendBaseUrl,
          reuseExistingServer: false,
          stdout: "ignore",
          stderr: "pipe",
          timeout: 120_000,
        },
      ],
});
