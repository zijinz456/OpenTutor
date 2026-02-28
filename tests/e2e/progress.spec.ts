import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

test.describe.serial("Progress Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Stats tab is visible in right panel", async ({ page }) => {
    await createCourseWithContent(page);
    // The "Stats" tab button should be visible in the right panel tab bar
    const statsTab = page.getByRole("button", { name: "Stats" });
    await expect(statsTab).toBeVisible({ timeout: 15_000 });
  });

  test("shows loading state initially", async ({ page }) => {
    await createCourseWithContent(page);
    // Click Stats tab
    await page.getByRole("button", { name: "Stats" }).click();
    // The panel initially shows a loading spinner (Loader2) or transitions quickly to content.
    // We verify that either the spinner appears briefly or progress content loads.
    const spinnerOrContent = page.locator("svg.animate-spin, [class*='completion']").first();
    await expect(spinnerOrContent).toBeVisible({ timeout: 15_000 });
  });

  test("shows completion percentage", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Stats" }).click();
    // After loading, should show "Course Completion" heading and a percentage badge
    await expect(page.getByText("Course Completion")).toBeVisible({ timeout: 15_000 });
    // Percentage badge (e.g., "0%", "50%")
    await expect(page.getByText(/%$/)).toBeVisible({ timeout: 15_000 });
  });

  test("stats grid shows metric cards", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Stats" }).click();
    await expect(page.getByText("Course Completion")).toBeVisible({ timeout: 15_000 });
    // Stats grid should contain metric cards: Total Study Time, Quiz Accuracy, Topics, Mastered
    await expect(page.getByText("Total Study Time")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Quiz Accuracy")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Topics")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Mastered")).toBeVisible({ timeout: 15_000 });
  });

  test("progress bar renders with segments", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Stats" }).click();
    await expect(page.getByText("Course Completion")).toBeVisible({ timeout: 15_000 });
    // The progress bar should be present (rounded-full overflow-hidden flex container)
    const progressBar = page.locator(".rounded-full.overflow-hidden.flex").first();
    await expect(progressBar).toBeVisible({ timeout: 15_000 });
  });

  test("legend shows status labels", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Stats" }).click();
    await expect(page.getByText("Course Completion")).toBeVisible({ timeout: 15_000 });
    // Legend should show the four status labels
    await expect(page.getByText(/Mastered:\s*\d+/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Reviewed:\s*\d+/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/In Progress:\s*\d+/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Not Started:\s*\d+/)).toBeVisible({ timeout: 15_000 });
  });
});

test.describe.serial("Knowledge Graph", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Graph tab is visible", async ({ page }) => {
    await createCourseWithContent(page);
    // The "Graph" tab button should be visible in the right panel tab bar
    const graphTab = page.getByRole("button", { name: "Graph" });
    await expect(graphTab).toBeVisible({ timeout: 15_000 });
  });

  test("graph canvas renders or shows empty state", async ({ page }) => {
    await createCourseWithContent(page);
    // Click Graph tab
    await page.getByRole("button", { name: "Graph" }).click();
    // Should either render the canvas element or show an empty state message.
    // After content upload, the knowledge graph should have nodes.
    const canvas = page.locator("canvas");
    const emptyState = page.getByText("Upload course materials to generate the knowledge graph");
    // Wait for either canvas or empty state to appear
    await expect(canvas.or(emptyState)).toBeVisible({ timeout: 15_000 });
    // If canvas is visible, check for zoom controls
    if (await canvas.isVisible()) {
      // Zoom controls should be present
      const zoomIn = page.locator("button").filter({ has: page.locator("svg") }).first();
      await expect(zoomIn).toBeVisible({ timeout: 5_000 });
    }
  });
});
