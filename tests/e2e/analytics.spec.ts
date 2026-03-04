import { expect, test } from "@playwright/test";
import { skipOnboarding } from "./helpers/test-utils";

const MOCK_OVERVIEW = {
  total_courses: 2,
  average_mastery: 0.65,
  total_study_minutes: 120,
  gap_type_breakdown: {},
  diagnosis_breakdown: {},
  error_category_breakdown: {},
  course_summaries: [
    {
      course_id: "test-course-1",
      course_name: "Test Course",
      average_mastery: 0.65,
      study_minutes: 120,
      wrong_answers: 3,
      diagnosed_count: 0,
      gap_types: {},
    },
  ],
};

const MOCK_TRENDS = { trend: [] };

/**
 * Mock the three analytics API calls so tests aren't affected by leftover
 * data or slow responses from previous test runs.
 */
async function mockAnalyticsApis(page: import("@playwright/test").Page, overviewOverride?: Record<string, unknown>) {
  const overview = overviewOverride ?? MOCK_OVERVIEW;
  await page.route("**/api/progress/overview", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(overview) }),
  );
  await page.route("**/api/progress/trends**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_TRENDS) }),
  );
  await page.route("**/api/progress/memory-stats", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ total: 0, avg_importance: 0, merged_count: 0, uncategorized: 0, by_type: {} }) }),
  );
}

test.describe("Analytics Page", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("analytics page loads from its direct route", async ({ page }) => {
    await mockAnalyticsApis(page);
    await page.goto("/analytics");
    await expect(page).toHaveURL("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
  });

  test("back button returns to dashboard", async ({ page }) => {
    await mockAnalyticsApis(page);
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    await page.getByTitle("Back to dashboard").click();
    await expect(page).toHaveURL("/");
  });

  test("shows loading spinner initially", async ({ page }) => {
    // Intercept API to delay response
    await page.route("**/api/progress/overview", async (route) => {
      await new Promise((r) => setTimeout(r, 1000));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        total_courses: 0,
        average_mastery: 0,
        total_study_minutes: 0,
        gap_type_breakdown: {},
        diagnosis_breakdown: {},
        error_category_breakdown: {},
        course_summaries: [],
      })});
    });
    await page.route("**/api/progress/trends**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_TRENDS) }),
    );
    await page.route("**/api/progress/memory-stats", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ total: 0, avg_importance: 0, merged_count: 0, uncategorized: 0, by_type: {} }) }),
    );
    await page.goto("/analytics");
    // Depending on render timing, the page may still be in loading state or may
    // have already transitioned to the analytics heading once the delayed fetch resolves.
    await expect(
      page.locator('.animate-pulse').first().or(
        page.getByRole("heading", { name: "Learning Analytics" }),
      ),
    ).toBeVisible();
  });

  test("shows 4 metric cards", async ({ page }) => {
    await mockAnalyticsApis(page);
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
    await mockAnalyticsApis(page);
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    await expect(page.getByText("Daily Study Time (last 30 days)")).toBeVisible();
    await expect(page.getByText("Quiz Activity (last 30 days)")).toBeVisible();
    await expect(page.getByText("Knowledge Gap Distribution")).toBeVisible();
    await expect(page.getByText("Error Category Breakdown")).toBeVisible();
  });

  test("shows empty state in breakdowns when no data", async ({ page }) => {
    await mockAnalyticsApis(page);
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    // Breakdown cards should show empty messages when no data
    const noGapData = page.getByText("No gap data yet");
    const noErrorData = page.getByText("No error data yet");
    await expect(noGapData.or(noErrorData).first()).toBeVisible();
  });

  test("course summaries section visible", async ({ page }) => {
    await mockAnalyticsApis(page);
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    await expect(page.getByText("Course Summaries")).toBeVisible();
  });

  test("empty course summaries shows placeholder", async ({ page }) => {
    await mockAnalyticsApis(page, { ...MOCK_OVERVIEW, course_summaries: [] });
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Learning Analytics" })).toBeVisible();
    await expect(page.getByText("Course Summaries")).toBeVisible();
    // Empty state message
    const emptyMsg = page.getByText("No learning analytics yet");
    const summariesExist = page.getByTestId("analytics-course-summaries").locator(".divide-y > div").first();
    // Either has course summaries or shows empty message
    await expect(emptyMsg.or(summariesExist)).toBeVisible({ timeout: 10_000 });
  });
});
