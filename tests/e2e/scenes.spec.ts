import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

/**
 * Internal Scene Routing tests.
 *
 * In the block-based workspace, "scenes" are replaced by blocks.
 * The STEM Student template includes: chapter_list, notes, quiz,
 * knowledge_graph, and progress blocks. There is no explicit
 * scene selector — blocks handle each domain.
 */

test.describe.serial("Internal Scene Routing", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("scene selector trigger is not visible in the workspace", async ({ page }) => {
    await createCourseWithContent(page, "Scene Hidden");
    await expect(page.getByTestId("scene-selector-trigger")).toHaveCount(0);
  });

  test("quiz block provides practice workspace", async ({ page }) => {
    await createCourseWithContent(page, "Scene Assignment");
    // PracticeSection from quiz block should be visible with Quiz tab
    await expect(page.getByRole("tab", { name: "Quiz", exact: true }).first()).toBeVisible({ timeout: 15_000 });
  });

  test("notes block shows uploaded content", async ({ page }) => {
    await createCourseWithContent(page, "Scene Notes");
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
  });
});
