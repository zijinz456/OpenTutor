import { expect, test } from "@playwright/test";

/**
 * Onboarding / Setup flow tests.
 *
 * /setup is a first-run gate: it checks the LLM connection (auto-advancing
 * to /new when ready) and otherwise shows the provider configuration with a
 * "Skip for now" button that hands off to /new, the single course-creation flow.
 *
 * Legacy /onboarding redirects to /setup (next.config redirect).
 */

test.describe("Onboarding flow", () => {
  // ---- redirect behaviour -----------------------------------------------

  test("redirects to /setup when opentutor_onboarded is not set", async ({ page }) => {
    // Do NOT call skipOnboarding -- localStorage has no flag.
    // Mock preferences to return empty profile
    await page.route("**/api/preferences/profile", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          preferences: [],
          dismissed_preferences: [],
          signals: [],
          dismissed_signals: [],
          memories: [],
          dismissed_memories: [],
          summary: {
            strength_areas: [],
            weak_areas: [],
            recurring_errors: [],
            inferred_habits: [],
          },
        }),
      });
    });
    // Mock courses to return empty — ensures no courses trigger the "onboarded" flag
    await page.route("**/api/courses/overview", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });
    await page.goto("/");
    await expect(page).toHaveURL(/\/setup/, { timeout: 15_000 });
  });

  test("does NOT redirect when opentutor_onboarded is set", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("opentutor_onboarded", "true");
    });
    await page.goto("/");
    // Wait for dashboard to render (heading or create button), then verify URL
    await expect(
      page.getByRole("heading", { name: /Your Learning Spaces/i })
    ).toBeVisible({ timeout: 15_000 });
    expect(page.url()).not.toContain("/setup");
  });

  test("does NOT redirect when onboarding preferences already exist on the server", async ({ page }) => {
    await page.route("**/api/preferences/profile", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          preferences: [
            { id: "1", dimension: "language", value: "zh", scope: "global", source: "playwright", confidence: 1, course_id: null, updated_at: new Date().toISOString() },
            { id: "2", dimension: "learning_mode", value: "balanced", scope: "global", source: "playwright", confidence: 1, course_id: null, updated_at: new Date().toISOString() },
            { id: "3", dimension: "detail_level", value: "balanced", scope: "global", source: "playwright", confidence: 1, course_id: null, updated_at: new Date().toISOString() },
            { id: "4", dimension: "layout_preset", value: "balanced", scope: "global", source: "playwright", confidence: 1, course_id: null, updated_at: new Date().toISOString() },
          ],
          dismissed_preferences: [],
          signals: [],
          dismissed_signals: [],
          memories: [],
          dismissed_memories: [],
          summary: {
            strength_areas: [],
            weak_areas: [],
            recurring_errors: [],
            inferred_habits: [],
          },
        }),
      });
    });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    expect(page.url()).not.toContain("/setup");
  });

  // ---- /onboarding legacy redirect --------------------------------------

  test("legacy /onboarding redirects to /setup", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page).toHaveURL(/\/setup/, { timeout: 15_000 });
  });

  // ---- setup page renders -----------------------------------------------

  test("setup page renders with OpenTutor branding", async ({ page }) => {
    await page.goto("/setup");
    await expect(page.getByRole("heading", { name: "OpenTutor" })).toBeVisible({ timeout: 15_000 });
  });

  // ---- LLM connect gate (auto-advances to /new if LLM is ready) ---------

  test("shows provider configuration when the LLM is not ready", async ({ page }) => {
    await page.route("**/api/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "degraded",
          llm_status: "not_configured",
          db_status: "ready",
          version: "test",
        }),
      });
    });
    await page.route("**/api/preferences/runtime/llm", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ provider: "", model: "", provider_keys: {} }),
      });
    });
    await page.goto("/setup");
    await expect(page.getByTestId("settings-api-keys")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("setup-continue")).toBeVisible({ timeout: 15_000 });
  });

  test("auto-advances to /new when the LLM is ready", async ({ page }) => {
    await page.route("**/api/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          llm_status: "ready",
          llm_primary: "ollama / llama3.2:3b",
          db_status: "ready",
          version: "test",
        }),
      });
    });
    await page.goto("/setup");
    await expect(page).toHaveURL(/\/new/, { timeout: 15_000 });
    const flag = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
    expect(flag).toBe("true");
  });

  // ---- localStorage flag ------------------------------------------------

  test("skipping the LLM gate marks onboarding complete and opens /new", async ({ page }) => {
    await page.route("**/api/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "degraded",
          llm_status: "configuration_required",
          db_status: "ready",
          version: "test",
        }),
      });
    });
    await page.goto("/setup");
    await page.getByTestId("setup-continue").click();
    await expect(page).toHaveURL(/\/new/, { timeout: 30_000 });
    const flag = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
    expect(flag).toBe("true");
  });
});
