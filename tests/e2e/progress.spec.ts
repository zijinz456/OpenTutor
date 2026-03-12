import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

/**
 * Progress Panel tests.
 *
 * In the block-based workspace, the STEM Student template includes a
 * "progress" block (renders ProgressView) and a "knowledge_graph" block
 * (renders GraphView). These are shown as separate blocks in the grid.
 */

test.describe.serial("Progress Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("progress block is visible in workspace", async ({ page }) => {
    await createCourseWithContent(page);
    // ProgressView renders course completion or empty state
    const content = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(content.first()).toBeVisible({ timeout: 30_000 });
  });

  test("shows completion percentage or empty state", async ({ page }) => {
    await createCourseWithContent(page);
    const progressContent = page.getByText("Course Completion").or(page.getByText("Upload course materials"));
    await expect(progressContent.first()).toBeVisible({ timeout: 30_000 });
  });
});

test.describe.serial("Knowledge Graph", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("knowledge graph block is visible", async ({ page }) => {
    await createCourseWithContent(page);
    // GraphView renders SVG, loading text, or empty state
    const graphContent = page
      .getByText("Loading graph...")
      .or(page.getByText("knowledge graph"))
      .or(page.locator("svg.bg-background"));
    await expect(graphContent.first()).toBeVisible({ timeout: 30_000 });
  });
});
