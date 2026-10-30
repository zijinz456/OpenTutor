import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

/**
 * Progress / Knowledge Graph tests.
 *
 * Workspace blocks are summary cards; the full ProgressView and GraphView
 * live under /course/[id]/profile (tabs "progress" and "graph").
 */

test.describe.serial("Progress Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("progress view is visible on the profile route", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await page.goto(`/course/${courseId}/profile?tab=progress`);
    // ProgressView renders course completion or empty state
    const content = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(content.first()).toBeVisible({ timeout: 30_000 });
  });

  test("shows completion percentage or empty state", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await page.goto(`/course/${courseId}/profile?tab=progress`);
    const progressContent = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(progressContent.first()).toBeVisible({ timeout: 30_000 });
  });
});

test.describe.serial("Knowledge Graph", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("knowledge graph is visible on the profile route", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await page.goto(`/course/${courseId}/profile?tab=graph`);
    // GraphView renders SVG, loading text, or empty state
    const graphContent = page
      .getByText("Loading graph...")
      .or(page.getByText("knowledge graph"))
      .or(page.locator("svg.bg-background"));
    await expect(graphContent.first()).toBeVisible({ timeout: 30_000 });
  });
});
