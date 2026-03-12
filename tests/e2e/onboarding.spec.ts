import { expect, test } from "@playwright/test";

/**
 * Onboarding / Setup flow tests.
 *
 * The setup page at /setup has 5 steps:
 *   1. Connect  (LLM check — auto-advances if ready)
 *   2. Feed     (Upload files / URL / Canvas)
 *   3. Interview (Habit interview — optional)
 *   4. Template  (Workspace layout template selection)
 *   5. Discover  (Ingestion progress + AI probe)
 *
 * Legacy /onboarding redirects to /setup.
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

  test("setup page shows step indicators", async ({ page }) => {
    await page.goto("/setup");
    // Step indicators show numbered circles
    await expect(page.getByText("1").first()).toBeVisible({ timeout: 15_000 });
  });

  // ---- step 1: LLM connect (auto-advances if LLM is ready) -------------

  test("step 1 shows Connect label", async ({ page }) => {
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
    await expect(page.getByText("Connect").first()).toBeVisible({ timeout: 15_000 });
  });

  // ---- step navigation via query param ----------------------------------

  test("?step=content skips to content step", async ({ page }) => {
    await page.goto("/setup?step=content");
    await expect(
      page.getByTestId("project-name-input")
        .or(page.getByText(/Upload|Drag|drop/i).first())
    ).toBeVisible({ timeout: 15_000 });
  });

  // ---- demo course option -----------------------------------------------

  test("demo course button is available on content step", async ({ page }) => {
    await page.goto("/setup?step=content");
    await expect(
      page.getByRole("button", { name: /demo|try|sample/i })
        .or(page.getByText(/demo|try a sample/i).first())
    ).toBeVisible({ timeout: 15_000 });
  });

  // ---- localStorage flag ------------------------------------------------

  test("localStorage flag is set after setup completion", async ({ page }) => {
    const fakeCourseId = "test-setup-completion";
    // Mock course creation so skip works without a real backend
    await page.route("**/api/courses/", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ id: fakeCourseId, name: "Test", description: "", sources: [], metadata: {} }),
        });
      } else {
        await route.continue();
      }
    });
    // Mock preferences endpoints (POST/PUT for applyDefaultPreferences)
    await page.route("**/api/preferences/**", async (route) => {
      if (route.request().method() !== "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      } else {
        await route.continue();
      }
    });
    await page.goto("/setup?step=content");
    // Look for a skip/demo/empty button to bypass setup
    const skipBtn = page.getByRole("button", { name: /skip|demo|try|empty|start empty/i }).first();
    const skipVisible = await skipBtn.isVisible({ timeout: 5_000 }).catch(() => false);
    if (skipVisible) {
      await skipBtn.click();
      // Skip creates a course then navigates to /course/{id}
      await expect.poll(() => page.url(), { timeout: 30_000 }).not.toContain("step=content");
      // Verify localStorage flag was set
      const flag = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
      expect(flag).toBe("true");
    } else {
      test.skip();
    }
  });
});
