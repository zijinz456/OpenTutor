import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourse } from "./helpers/test-utils";

/**
 * Dashboard tests (Phase 1 -- no course content required).
 *
 * The dashboard at / shows:
 *   - Header with OpenTutor branding, settings icon, analytics icon
 *   - Title "Your Courses"
 *   - Big indigo create button -> /new
 *   - Course card grid with initials, name, updated date, and real file/task counts
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
    await expect(page.getByText("OpenTutor").first()).toBeVisible({ timeout: 15_000 });
  });

  // ---- empty state ------------------------------------------------------

  test("shows empty state or course list on dashboard", async ({ page }) => {
    await page.goto("/");
    // Either shows empty state or existing courses (DB may have data from other tests)
    const emptyState = page.getByText("No courses yet", { exact: false });
    const courseList = page.locator(".grid").first();
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

  test("settings button navigates to /settings", async ({ page }) => {
    await page.goto("/");
    await page.getByText("Settings").first().click();
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
  });

  // ---- analytics icon ---------------------------------------------------

  test("analytics button navigates to /analytics", async ({ page }) => {
    await page.goto("/");
    await page.getByText("Analytics").first().click();
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
    const loadingIndicator = page.getByText("Loading");
    await expect(loadingIndicator.first()).toBeVisible({ timeout: 5_000 });
  });

  // ---- course card after creation ---------------------------------------

  test("course card appears after creating a course", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `DashCard ${uid}`);
    await page.goto("/");
    await expect(page.getByText(`DashCard ${uid}`)).toBeVisible({ timeout: 15_000 });
  });

  test("clicking course card navigates to workspace", async ({ page }) => {
    const uid = Date.now();
    const courseId = await createCourse(page, `ClickNav ${uid}`);
    await page.goto("/");
    await page.getByText(`ClickNav ${uid}`).click();
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 15_000 });
  });

  test("course card shows initials from name", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `Quantum Physics ${uid}`);
    await page.goto("/");
    // Initials should be "QP" (first letters of first two words)
    await expect(page.getByText("QP").first()).toBeVisible({ timeout: 15_000 });
  });

  test("course card shows a date", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `DateCheck ${uid}`);
    await page.goto("/");
    // The date is shown in toLocaleDateString() format (e.g. "3/2/2026")
    await expect(page.getByText(`DateCheck ${uid}`)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("button").filter({ hasText: `DateCheck ${uid}` }).locator(".text-muted-foreground").first()).toBeVisible();
  });

  test("course card shows scene description fallback", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `EmptyFiles ${uid}`);
    await page.goto("/");
    // Courses without description show "Scene: study_session" fallback
    await expect(page.getByText("Scene:").first()).toBeVisible({ timeout: 15_000 });
  });

  test("multiple courses render in grid", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `GridA ${uid}`);
    await page.goto("/new");
    await createCourse(page, `GridB ${uid}`);
    await page.goto("/");
    await expect(page.getByText(`GridA ${uid}`)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(`GridB ${uid}`)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: new RegExp(`GridA ${uid}`) })).toBeVisible();
    await expect(page.getByRole("button", { name: new RegExp(`GridB ${uid}`) })).toBeVisible();
  });

  test("newly created course appears on dashboard", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `BrandNew ${uid}`);
    await page.goto("/");
    await expect(page.getByText(`BrandNew ${uid}`)).toBeVisible({ timeout: 15_000 });
  });

  test("dashboard re-fetches courses on mount", async ({ page }) => {
    const uid = Date.now();
    await createCourse(page, `Refetch ${uid}`);
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
    await page.goto("/");
    await expect(page.getByText(`Refetch ${uid}`)).toBeVisible({ timeout: 15_000 });
  });
});
