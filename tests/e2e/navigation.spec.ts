import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourse } from "./helpers/test-utils";

/**
 * Cross-page navigation tests (Phase 1 -- no course content required).
 *
 * Verifies that the major navigation flows between dashboard, new project,
 * workspace, settings, and analytics pages work as expected.
 */

test.describe("Navigation", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  // ---- round-trip -------------------------------------------------------

  test("dashboard -> new project -> workspace round-trip", async ({ page }) => {
    await page.goto("/");
    // Dashboard -> /new
    await page.getByText("Create Course").click();
    await expect(page).toHaveURL(/\/new/, { timeout: 15_000 });

    // /new -> create course -> workspace
    const courseId = await createCourse(page, "Nav Round Trip");
    expect(courseId).toBeTruthy();
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 15_000 });
  });

  // ---- workspace home icon ----------------------------------------------

  test("workspace home icon navigates to dashboard", async ({ page }) => {
    await createCourse(page, "Home Icon Course");
    // The activity bar has a Home button (title="Home")
    await page.locator('button[title="Home"]').click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- workspace settings icon ------------------------------------------

  test("workspace settings icon navigates to settings", async ({ page }) => {
    await createCourse(page, "Settings Icon Course");
    // The activity bar has a Settings button (title="Settings")
    await page.locator('button[title="Settings"]').click();
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
  });

  // ---- settings back button ---------------------------------------------

  test("settings back button navigates to dashboard", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
    // Back button is the ArrowLeft icon button in the header
    await page.locator("header").getByRole("button").first().click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- analytics back button --------------------------------------------

  test("analytics back button navigates to dashboard", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page).toHaveURL(/\/analytics/, { timeout: 15_000 });
    // Back button is the ArrowLeft icon button in the header
    await page.locator("header").getByRole("button").first().click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- new project back button ------------------------------------------

  test("new project back button navigates to dashboard", async ({ page }) => {
    await page.goto("/new");
    await expect(page).toHaveURL(/\/new/, { timeout: 15_000 });
    // The "Back to Projects" button on the mode selection step
    await page.getByRole("button", { name: /Back to Projects/i }).click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- direct workspace navigation -------------------------------------

  test("navigating directly to /course/[id] loads workspace", async ({ page }) => {
    const courseId = await createCourse(page, "Direct Nav Course");
    // Navigate away first
    await page.goto("/");
    await expect(page).toHaveURL("/", { timeout: 15_000 });
    // Navigate directly to the workspace URL
    await page.goto(`/course/${courseId}`);
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 15_000 });
    // The workspace should load -- activity bar home button should be visible
    await expect(page.locator('button[title="Home"]')).toBeVisible({ timeout: 15_000 });
  });

  // ---- browser back/forward ---------------------------------------------

  test("browser back/forward buttons work", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    // Navigate to settings
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });

    // Navigate to analytics
    await page.goto("/analytics");
    await expect(page).toHaveURL(/\/analytics/, { timeout: 15_000 });

    // Browser back -> settings
    await page.goBack();
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });

    // Browser back -> dashboard
    await page.goBack();
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    // Browser forward -> settings
    await page.goForward();
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
  });

  // ---- non-existent course ----------------------------------------------

  test("navigating to non-existent course shows error or redirects", async ({ page }) => {
    await page.goto("/course/999999");
    // The app should either show an error message or the page should indicate
    // that something went wrong. We check for either an error text or that
    // the workspace does not fully load (no activity bar home button visible
    // within a short timeout, or an error/redirect occurs).
    const hasError = await page
      .getByText(/error|not found|something went wrong/i)
      .isVisible({ timeout: 10_000 })
      .catch(() => false);
    const redirectedAway = !page.url().includes("/course/999999");
    expect(hasError || redirectedAway).toBeTruthy();
  });

  // ---- correct URL paths ------------------------------------------------

  test("all pages maintain correct URL paths", async ({ page }) => {
    // Dashboard
    await page.goto("/");
    expect(page.url()).toMatch(/\/$/);

    // Settings
    await page.goto("/settings");
    expect(page.url()).toContain("/settings");

    // Analytics
    await page.goto("/analytics");
    expect(page.url()).toContain("/analytics");

    // New
    await page.goto("/new");
    expect(page.url()).toContain("/new");

    // Onboarding (accessible even with flag set; page itself renders)
    await page.goto("/onboarding");
    expect(page.url()).toContain("/onboarding");
  });
});
