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
    test.setTimeout(120_000);
    await page.goto("/");
    // Dashboard -> /new via "New Space" button
    await page.getByRole("button", { name: /New Space/i }).first().click();
    await expect(page).toHaveURL(/\/new/, { timeout: 15_000 });

    // /new -> create course -> workspace
    const courseId = await createCourse(page, "Nav Round Trip");
    expect(courseId).toBeTruthy();
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 15_000 });
  });

  // ---- workspace home icon ----------------------------------------------

  test("workspace home icon navigates to dashboard", async ({ page }) => {
    await createCourse(page, "Home Icon Course");
    await page.getByRole("link", { name: /Back/i }).click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- workspace settings icon ------------------------------------------

  test("workspace settings icon navigates to settings", async ({ page }) => {
    await createCourse(page, "Settings Icon Course");
    await page.getByRole("link", { name: "Settings" }).click();
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
    // The back button may say "Back to Projects", "← Back", or just "Back"
    await page.getByRole("button", { name: /Back/i }).first().click();
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
    await expect(page.getByRole("link", { name: /Back/i })).toBeVisible({ timeout: 15_000 });
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

  test("navigating to non-existent course shows error or loads workspace", async ({ page }) => {
    await page.goto("/course/00000000-0000-0000-0000-000000000000");
    await page.waitForLoadState("networkidle");
    const hasError = await page
      .getByText(/error|not found|something went wrong/i)
      .first()
      .isVisible({ timeout: 5_000 })
      .catch(() => false);
    const redirectedAway = !page.url().includes("/course/00000000");
    const hasWorkspace = await page
      .getByTestId("chat-input")
      .isVisible({ timeout: 5_000 })
      .catch(() => false);
    expect(hasError || redirectedAway || hasWorkspace).toBeTruthy();
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

    // Setup (was /onboarding)
    await page.goto("/setup");
    expect(page.url()).toContain("/setup");
  });
});
