import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

/**
 * Keyboard Shortcuts tests.
 *
 * The block-based workspace renders sections as blocks in a grid.
 * The STEM Student template creates notes, quiz, progress, and knowledge_graph blocks.
 * Cmd+K opens the search dialog.
 */
test.describe.serial("Keyboard Shortcuts", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("notes block is visible after template is applied", async ({ page }) => {
    await createCourseWithContent(page, "KB Notes");
    // Notes panel should be visible as a block in the grid
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 15_000 });
  });

  test("quiz block renders quiz tab", async ({ page }) => {
    await createCourseWithContent(page, "KB Quiz");
    // Quiz tab should be visible in the practice section block
    await expect(page.getByRole("tab", { name: "Quiz", exact: true }).first()).toBeVisible({ timeout: 15_000 });
  });

  test("Cmd+K opens search dialog", async ({ page }) => {
    await createCourseWithContent(page, "KB Search");
    // Dispatch Cmd+K
    const useMeta = process.platform === "darwin";
    await page.evaluate(
      ({ useMeta }) => {
        window.dispatchEvent(
          new KeyboardEvent("keydown", {
            key: "k",
            code: "KeyK",
            metaKey: useMeta,
            ctrlKey: !useMeta,
            bubbles: true,
            cancelable: true,
          }),
        );
      },
      { useMeta },
    );
    // Search dialog should open
    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
  });
});
