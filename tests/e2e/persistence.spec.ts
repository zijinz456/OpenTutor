import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourse, getCourseViaApi } from "./helpers/test-utils";

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
    await expect(page.locator("html")).toHaveAttribute("class", /dark/, { timeout: 5_000 });

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
    await page.waitForLoadState("networkidle");
    // URL should remain / (no redirect to /onboarding)
    expect(page.url()).not.toContain("/onboarding");
  });

  // ---- removing onboarding flag -----------------------------------------

  test("removing onboarding flag triggers redirect", async ({ browser }, testInfo) => {
    // Use a fresh browser context to avoid addInitScript pollution from other tests.
    // A brand-new context has no localStorage, so the onboarding check fires immediately.
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

    // First: verify that WITH the flag, dashboard stays at /
    const ctx1 = await browser.newContext({ baseURL });
    const page1 = await ctx1.newPage();
    await page1.route("**/api/preferences/profile**", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: emptyProfileResponse });
    });
    await page1.addInitScript(() => localStorage.setItem("opentutor_onboarded", "true"));
    await page1.goto("/");
    await expect(page1).toHaveURL("/", { timeout: 15_000 });
    await page1.close();
    await ctx1.close();

    // Second: verify that WITHOUT the flag, dashboard redirects to /onboarding
    const ctx2 = await browser.newContext({ baseURL });
    const page2 = await ctx2.newPage();
    await page2.route("**/api/preferences/profile**", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: emptyProfileResponse });
    });
    await page2.goto("/");
    await expect(page2).toHaveURL(/\/onboarding/, { timeout: 30_000 });
    await page2.close();
    await ctx2.close();
  });

  // ---- course features --------------------------------------------------

  test("course features persist in course metadata", async ({ page }) => {
    await skipOnboarding(page);
    const courseId = await createCourse(page, "Features Persist Course");

    const course = await getCourseViaApi(courseId);
    expect(course.metadata).toMatchObject({
      workspace_features: {
        notes: true,
        practice: true,
        free_qa: true,
      },
    });
  });

  // ---- auto-scrape preference -------------------------------------------

  test("auto-scrape metadata remains disabled when no URL source is submitted", async ({ page }) => {
    await skipOnboarding(page);

    // Create a course using the "both" mode (upload + URL) which enables auto-scrape by default
    await page.goto("/new");
    // Select "Both" mode
    await page.getByTestId("mode-option-both").click();
    await page.getByTestId("mode-continue").click();
    await page.getByTestId("project-name-input").fill("Auto Scrape Course");
    await page.getByTestId("start-parsing").click();
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();
    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//);

    const url = page.url();
    const match = url.match(/\/course\/([^/?#]+)/);
    const courseId = match ? match[1] : "";
    expect(courseId).toBeTruthy();

    const course = await getCourseViaApi(courseId);
    expect(course.metadata).toMatchObject({
      auto_scrape: {
        enabled: false,
      },
    });
  });

  // ---- NL instruction ---------------------------------------------------

  test("NL instruction is handed off to the workspace once", async ({ page }) => {
    await skipOnboarding(page);

    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();
    await page.getByTestId("project-name-input").fill("NL Instruction Course");
    await page.getByTestId("start-parsing").click();
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();

    // Fill in the NL instruction textarea on the features page
    const nlTextarea = page.locator("textarea");
    await nlTextarea.fill("Focus on algorithms and use bullet points");

    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//);

    const url = page.url();
    const match = url.match(/\/course\/([^/?#]+)/);
    const courseId = match ? match[1] : "";
    expect(courseId).toBeTruthy();

    const consumedFlag = await page.evaluate(
      (id) => sessionStorage.getItem(`course_init_prompt_consumed_${id}`),
      courseId,
    );
    expect(consumedFlag).toBe("true");
  });
});
