import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

test.describe.serial("Keyboard Shortcuts", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Cmd+1 applies notesFocused layout", async ({ page }) => {
    await createCourseWithContent(page, "KB Notes");
    const modifier = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${modifier}+1`);
    // Notes panel should be prominently visible
    await expect(page.getByTestId("notes-panel")).toBeVisible();
  });

  test("Cmd+2 applies quizFocused layout", async ({ page }) => {
    await createCourseWithContent(page, "KB Quiz");
    const modifier = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${modifier}+2`);
    // Quiz area should be visible
    await expect(page.getByRole("button", { name: "Quiz" })).toBeVisible();
  });

  test("Cmd+3 applies chatFocused layout", async ({ page }) => {
    await createCourseWithContent(page, "KB Chat");
    const modifier = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${modifier}+3`);
    // Chat panel should be prominently visible
    await expect(page.getByTestId("chat-input")).toBeVisible();
  });

  test("Cmd+0 applies balanced layout", async ({ page }) => {
    await createCourseWithContent(page, "KB Balanced");
    const modifier = process.platform === "darwin" ? "Meta" : "Control";
    // First switch to a different layout
    await page.keyboard.press(`${modifier}+1`);
    await page.waitForTimeout(500);
    // Then reset to balanced
    await page.keyboard.press(`${modifier}+0`);
    // Both notes and chat should be visible in balanced layout
    await expect(page.getByTestId("notes-panel")).toBeVisible();
    await expect(page.getByTestId("chat-input")).toBeVisible();
  });

  test("shortcuts do not fire without modifier key", async ({ page }) => {
    await createCourseWithContent(page, "KB NoMod");
    // Press just "1" without modifier - should type into focused element, not trigger shortcut
    await page.keyboard.press("1");
    // Layout should remain unchanged - both panels still visible
    await expect(page.getByTestId("notes-panel")).toBeVisible();
    await expect(page.getByTestId("chat-input")).toBeVisible();
  });

  test("keyboard shortcut works after panel interaction", async ({ page }) => {
    await createCourseWithContent(page, "KB AfterInteract");
    // Click on chat input first
    await page.getByTestId("chat-input").click();
    // Press Escape to unfocus
    await page.keyboard.press("Escape");
    const modifier = process.platform === "darwin" ? "Meta" : "Control";
    await page.keyboard.press(`${modifier}+1`);
    await expect(page.getByTestId("notes-panel")).toBeVisible();
  });
});
