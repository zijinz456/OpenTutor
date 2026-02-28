import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourse } from "./helpers/test-utils";

/**
 * Dashboard tests (Phase 1 -- no course content required).
 *
 * The dashboard at / shows:
 *   - Header with OpenTutor branding, settings icon, analytics icon
 *   - Title "Your Courses" (en) / "你的课程" (zh)
 *   - Big indigo create button -> /new
 *   - Course card grid with initials, name, date, "0 files" fallback
 *   - Empty state with Brain icon when no courses
 *   - Loading text while fetching
 */

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  // ---- header -----------------------------------------------------------

  test("renders header with OpenTutor branding", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("OpenTutor")).toBeVisible({ timeout: 15_000 });
  });

  // ---- empty state ------------------------------------------------------

  test("shows empty state or course list on dashboard", async ({ page }) => {
    await page.goto("/");
    // Either shows empty state or existing courses (DB may have data from other tests)
    const emptyState = page.getByText("No courses yet", { exact: false });
    const courseList = page.locator(".grid");
    await expect(emptyState.or(courseList)).toBeVisible({ timeout: 15_000 });
  });

  // ---- create button ----------------------------------------------------

  test("create button navigates to /new", async ({ page }) => {
    await page.goto("/");
    // The big indigo button contains the translated "Create Course" text
    await page.getByText("Create Course").click();
    await expect(page).toHaveURL(/\/new/, { timeout: 15_000 });
  });

  // ---- settings icon ----------------------------------------------------

  test("settings icon navigates to /settings", async ({ page }) => {
    await page.goto("/");
    // Settings icon is a button in the header area
    await page.locator("button").filter({ has: page.locator('svg.lucide-settings') }).click();
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
  });

  // ---- analytics icon ---------------------------------------------------

  test("analytics icon navigates to /analytics", async ({ page }) => {
    await page.goto("/");
    // Analytics is the first icon button in the header right area (BarChart3)
    const headerBtns = page.locator("button.text-gray-500");
    await headerBtns.first().click();
    await expect(page).toHaveURL(/\/analytics/, { timeout: 15_000 });
  });

  // ---- loading state ----------------------------------------------------

  test("shows loading text while fetching", async ({ page }) => {
    // Slow down API to observe the loading state
    await page.route("**/api/courses*", async (route) => {
      await new Promise((r) => setTimeout(r, 2000));
      await route.continue();
    });
    await page.goto("/");
    // The loading text uses i18n general.loading key - check for any loading indicator
    const loadingIndicator = page.getByText("Loading").or(page.getByText("加载中"));
    await expect(loadingIndicator.first()).toBeVisible({ timeout: 5_000 });
  });

  // ---- course card after creation ---------------------------------------

  test("course card appears after creating a course", async ({ page }) => {
    await createCourse(page, "Dashboard Test Course");
    // Navigate back to dashboard
    await page.goto("/");
    await expect(page.getByText("Dashboard Test Course")).toBeVisible({ timeout: 15_000 });
  });

  test("clicking course card navigates to workspace", async ({ page }) => {
    const courseId = await createCourse(page, "Click Test Course");
    await page.goto("/");
    await page.getByText("Click Test Course").click();
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 15_000 });
  });

  test("course card shows initials from name", async ({ page }) => {
    await createCourse(page, "Quantum Physics");
    await page.goto("/");
    // Initials should be "QP"
    await expect(page.getByText("QP")).toBeVisible({ timeout: 15_000 });
  });

  test("course card shows creation date", async ({ page }) => {
    await createCourse(page, "Date Check Course");
    await page.goto("/");
    // The card shows "Created: <date>" -- verify at least one is present
    await expect(page.getByText("Created:", { exact: false }).first()).toBeVisible({ timeout: 15_000 });
  });

  test("course card shows '0 files' description fallback", async ({ page }) => {
    await createCourse(page, "Empty Files Course");
    await page.goto("/");
    await expect(page.getByText("0 files").first()).toBeVisible({ timeout: 15_000 });
  });

  test("multiple courses render in grid", async ({ page }) => {
    await createCourse(page, "Grid Course A");
    await page.goto("/new");
    await createCourse(page, "Grid Course B");
    await page.goto("/");
    await expect(page.getByText("Grid Course A")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Grid Course B")).toBeVisible({ timeout: 15_000 });
    // The grid container uses CSS grid classes
    const grid = page.locator(".grid");
    await expect(grid).toBeVisible();
  });

  test("newly created course appears on dashboard", async ({ page }) => {
    // Create a course first
    await createCourse(page, "Brand New Course");
    // Return to dashboard
    await page.goto("/");
    await expect(page.getByText("Brand New Course")).toBeVisible({ timeout: 15_000 });
  });

  test("dashboard re-fetches courses on mount", async ({ page }) => {
    await createCourse(page, "Refetch Course");
    // Navigate to settings then back to dashboard
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
    await page.goto("/");
    // The course should still appear (re-fetched on mount)
    await expect(page.getByText("Refetch Course")).toBeVisible({ timeout: 15_000 });
  });
});
