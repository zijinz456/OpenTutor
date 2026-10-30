import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

/**
 * Keyboard Shortcuts tests.
 *
 * Workspace blocks are summary cards that link to dedicated routes.
 * Cmd+K opens the search dialog.
 */
test.describe.serial("Keyboard Shortcuts", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("notes route renders the notes panel", async ({ page }) => {
    await createCourseWithContent(page, "KB Notes", "notes");
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 15_000 });
  });

  test("practice route renders quiz tab", async ({ page }) => {
    await createCourseWithContent(page, "KB Quiz", "practice");
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
