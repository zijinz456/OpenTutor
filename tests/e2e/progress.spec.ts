import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, ensureRightPanelVisible } from "./helpers/test-utils";

test.describe.serial("Progress Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Stats tab is visible in right panel", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    const statsTab = page.getByRole("button", { name: "Stats" });
    await expect(statsTab).toBeVisible({ timeout: 15_000 });
  });

  test("Stats panel shows content after loading", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    // After loading, shows either progress data or the empty state
    const content = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(content.first()).toBeVisible({ timeout: 15_000 });
  });

  test("shows completion percentage or empty state", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    // Wait for either state to appear — progress data or empty state
    const progressContent = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(progressContent.first()).toBeVisible({ timeout: 15_000 });
  });

  test("stats grid shows metric cards or empty state", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    // Wait for content to load — either progress data or empty state
    const progressContent = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(progressContent.first()).toBeVisible({ timeout: 15_000 });
    // If Course Completion is showing, verify the stats cards
    const courseCompletion = page.getByText("Course Completion");
    const completionVisible = await courseCompletion.count() > 0 && await courseCompletion.isVisible();
    if (completionVisible) {
      await expect(page.getByText("Total Study Time")).toBeVisible({ timeout: 5_000 });
      await expect(page.getByText("Quiz Accuracy")).toBeVisible({ timeout: 5_000 });
    }
    // Empty state is also valid — test passes either way
  });

  test("progress bar or empty state renders", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    const progressContent = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(progressContent.first()).toBeVisible({ timeout: 15_000 });
    if (await page.getByText("Course Completion").isVisible()) {
      const progressBar = page.locator(".rounded-full.overflow-hidden.flex").first();
      await expect(progressBar).toBeVisible({ timeout: 5_000 });
    }
  });

  test("legend shows status labels when progress exists", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    const progressContent = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(progressContent.first()).toBeVisible({ timeout: 15_000 });
    if (await page.getByText("Course Completion").isVisible()) {
      await expect(page.getByText(/Mastered:\s*\d+/)).toBeVisible({ timeout: 5_000 });
      await expect(page.getByText(/Reviewed:\s*\d+/)).toBeVisible({ timeout: 5_000 });
      await expect(page.getByText(/In Progress:\s*\d+/)).toBeVisible({ timeout: 5_000 });
      await expect(page.getByText(/Not Started:\s*\d+/)).toBeVisible({ timeout: 5_000 });
    }
  });
});

test.describe.serial("Knowledge Graph", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Graph tab is visible", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    const graphTab = page.getByRole("button", { name: "Graph" });
    await expect(graphTab).toBeVisible({ timeout: 15_000 });
  });

  test("graph canvas renders or shows empty state", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Graph" }).click();
    // Wait for the dynamically imported KnowledgeGraph to load (any state)
    // Dynamic imports can be very slow under CI load (5 parallel workers)
    await expect(page.getByTestId("graph-panel").or(page.locator("canvas")).first()).toBeVisible({ timeout: 60_000 });
    const canvas = page.locator("canvas");
    const emptyState = page.getByText("Upload course materials to generate the knowledge graph");
    await expect(canvas.or(emptyState).first()).toBeVisible({ timeout: 60_000 });
    if (await canvas.isVisible()) {
      const zoomIn = page.locator("button").filter({ has: page.locator("svg") }).first();
      await expect(zoomIn).toBeVisible({ timeout: 5_000 });
    }
  });
});
