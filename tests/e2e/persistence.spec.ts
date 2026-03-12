import { expect, test } from "@playwright/test";
import { skipOnboarding } from "./helpers/test-utils";

/**
 * localStorage persistence tests (Phase 1 -- no course content required).
 *
 * Verifies that key application state survives page reloads
 * by reading/writing localStorage values.
 */

test.describe("Persistence", () => {
  // ---- onboarding flag --------------------------------------------------

  test("onboarding flag persists across reloads", async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/");
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    // Verify the flag is set
    const flag = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
    expect(flag).toBe("true");

    // Reload and verify it persists
    await page.reload();
    const flagAfterReload = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
    expect(flagAfterReload).toBe("true");

    // Should still be on dashboard (no redirect to onboarding)
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- locale setting ---------------------------------------------------

  test("locale setting persists across reloads", async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/settings");

    // Click English to set locale
    await page.getByRole("button", { name: "English" }).click();
    await expect(page.getByText("Switched to English")).toBeVisible({ timeout: 15_000 });

    // Check localStorage
    const locale = await page.evaluate(() => localStorage.getItem("opentutor-locale"));
    expect(locale).toBe("en");

    // Reload and verify
    await page.reload();
    const localeAfterReload = await page.evaluate(() => localStorage.getItem("opentutor-locale"));
    expect(localeAfterReload).toBe("en");
  });

  // ---- theme preference -------------------------------------------------

  test("theme preference persists across reloads", async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/settings");

    // Switch to dark
    await page.getByRole("button", { name: /Dark/i }).click();
    await expect.poll(
      async () => {
        const cls = await page.locator("html").getAttribute("class");
        return cls?.includes("dark") ?? false;
      },
      { timeout: 5_000 },
    ).toBe(true);

    // next-themes stores the preference in localStorage under "theme"
    const theme = await page.evaluate(() => localStorage.getItem("theme"));
    expect(theme).toBe("dark");

    // Reload and verify
    await page.reload();
    const themeAfterReload = await page.evaluate(() => localStorage.getItem("theme"));
    expect(themeAfterReload).toBe("dark");
  });

  // ---- onboarding completion prevents redirect --------------------------

  test("onboarding completion prevents redirect", async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/");
    // Wait for dashboard to render, then verify URL
    await expect(
      page.getByRole("heading", { name: /Your Learning Spaces/i })
    ).toBeVisible({ timeout: 15_000 });
    expect(page.url()).not.toContain("/setup");
  });

  // ---- removing onboarding flag -----------------------------------------

  test("removing onboarding flag triggers redirect", async ({ browser }, testInfo) => {
    // Use a fresh browser context to avoid addInitScript pollution from other tests.
    const baseURL = testInfo.project.use.baseURL || "http://127.0.0.1:3005";
    const emptyProfileResponse = JSON.stringify({
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
    });

    const emptyCourses = JSON.stringify([]);

    // First: verify that WITH the flag, dashboard stays at /
    const ctx1 = await browser.newContext({ baseURL });
    const page1 = await ctx1.newPage();
    await page1.route("**/api/preferences/profile**", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: emptyProfileResponse });
    });
    await page1.route("**/api/courses/overview", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: emptyCourses });
    });
    await page1.addInitScript(() => localStorage.setItem("opentutor_onboarded", "true"));
    await page1.goto("/");
    await expect(page1.getByRole("heading", { name: /Your Learning Spaces/i })).toBeVisible({ timeout: 15_000 });
    expect(page1.url()).not.toContain("/setup");
    await page1.close();
    await ctx1.close();

    // Second: verify that WITHOUT the flag, dashboard redirects to /setup
    const ctx2 = await browser.newContext({ baseURL });
    const page2 = await ctx2.newPage();
    await page2.route("**/api/preferences/profile**", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: emptyProfileResponse });
    });
    await page2.route("**/api/courses/overview", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: emptyCourses });
    });
    await page2.goto("/");
    await expect(page2).toHaveURL(/\/setup/, { timeout: 30_000 });
    await page2.close();
    await ctx2.close();
  });
});
