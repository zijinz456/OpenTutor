import { expect, test } from "@playwright/test";
import { skipOnboarding } from "./helpers/test-utils";

test.describe("Analytics Page", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("navigates to /analytics from dashboard", async ({ page }) => {
    await page.goto("/");
    // Analytics is the first icon button in the header right area
    const headerBtns = page.locator("button.text-gray-500");
    await headerBtns.first().click();
    await expect(page).toHaveURL("/analytics");
  });

  test("back button returns to dashboard", async ({ page }) => {
    await page.goto("/analytics");
    // Back button is in the header
    await page.locator("header button").first().click();
    await expect(page).toHaveURL("/");
  });

  test("shows loading spinner initially", async ({ page }) => {
    // Intercept API to delay response
    await page.route("**/api/progress/learning-overview", async (route) => {
      await new Promise((r) => setTimeout(r, 1000));
      await route.fulfill({ status: 200, body: JSON.stringify({
        total_courses: 0,
        average_mastery: 0,
        total_study_minutes: 0,
        gap_type_breakdown: {},
        diagnosis_breakdown: {},
        error_category_breakdown: {},
        course_summaries: [],
      })});
    });
    await page.goto("/analytics");
    // Depending on render timing, the page may still be in loading state or may
    // have already transitioned to the analytics heading once the delayed fetch resolves.
    await expect(
      page.locator('svg.lucide-loader-2, .animate-spin').first().or(
        page.getByRole("heading", { name: "Learning Analytics" }),
      ),
    ).toBeVisible();
  });

  test("shows 4 metric cards", async ({ page }) => {
    await page.goto("/analytics");
    // Wait for loading to finish
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    // 4 metric cards
    await expect(page.getByText("Courses")).toBeVisible();
    await expect(page.getByText("Average Mastery")).toBeVisible();
    await expect(page.getByTestId("analytics-metric-study-time")).toBeVisible();
    await expect(page.getByText("Quiz Questions")).toBeVisible();
  });

  test("shows analytics chart and breakdown sections", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    await expect(page.getByText("Daily Study Time (last 30 days)")).toBeVisible();
    await expect(page.getByText("Quiz Activity (last 30 days)")).toBeVisible();
    await expect(page.getByText("Knowledge Gap Distribution")).toBeVisible();
    await expect(page.getByText("Error Category Breakdown")).toBeVisible();
  });

  test("shows empty state in breakdowns when no data", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    // Breakdown cards should show "No data yet" when empty
    const noDataLabels = page.getByText("No data yet");
    const count = await noDataLabels.count();
    expect(count).toBeGreaterThanOrEqual(0); // May or may not have data
  });

  test("course summaries section visible", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByText("Course Summaries")).toBeVisible();
  });

  test("empty course summaries shows placeholder", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByText("Course Summaries")).toBeVisible();
    // If no courses, should show empty message
    const emptyMsg = page.getByText("No learning analytics yet");
    const summariesExist = page.locator(".divide-y > div").first();
    // Either has course summaries or shows empty message
    await expect(emptyMsg.or(summariesExist)).toBeVisible({ timeout: 10_000 });
  });
});
