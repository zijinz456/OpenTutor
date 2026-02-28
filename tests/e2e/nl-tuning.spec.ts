import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

test.describe.serial("NL Tuning FAB", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("FAB button is visible in workspace", async ({ page }) => {
    await createCourseWithContent(page, "FAB Visible");
    const fab = page.locator('button[title="Fine-tune Agent"]');
    await expect(fab).toBeVisible();
  });

  test("clicking FAB opens the tuning popup", async ({ page }) => {
    await createCourseWithContent(page, "FAB Open");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await expect(page.getByText("Fine-tune Agent").first()).toBeVisible();
    await expect(page.getByPlaceholder('e.g. "simplify notes"')).toBeVisible();
  });

  test("popup shows input field with placeholder", async ({ page }) => {
    await createCourseWithContent(page, "FAB Input");
    await page.locator('button[title="Fine-tune Agent"]').click();
    const input = page.getByPlaceholder('e.g. "simplify notes"');
    await expect(input).toBeVisible();
    await expect(input).toBeFocused();
  });

  test("typing and pressing Enter transitions to clarify view", async ({ page }) => {
    await createCourseWithContent(page, "FAB Clarify");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("make notes shorter");
    await page.keyboard.press("Enter");
    // Should show clarify view with options
    await expect(page.getByText("What would you like to adjust?")).toBeVisible();
    await expect(page.getByText("make notes shorter")).toBeVisible();
  });

  test("clarify view shows 3 options", async ({ page }) => {
    await createCourseWithContent(page, "FAB Options");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("change style");
    await page.keyboard.press("Enter");
    // 3 clarify options
    await expect(page.getByText("Notes panel: change formatting style")).toBeVisible();
    await expect(page.getByText("AI responses: adjust detail level")).toBeVisible();
    await expect(page.getByText("AI responses: adjust tone and style")).toBeVisible();
  });

  test("clarify view shows user's original input text", async ({ page }) => {
    await createCourseWithContent(page, "FAB UserText");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("my custom request");
    await page.keyboard.press("Enter");
    await expect(page.getByText("my custom request")).toBeVisible();
  });

  test("selecting a clarify option shows sub-options", async ({ page }) => {
    await createCourseWithContent(page, "FAB SubOpts");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("change format");
    await page.keyboard.press("Enter");
    await page.getByText("Notes panel: change formatting style").click();
    // Sub-options for note_format
    await expect(page.getByText("Bullet Points")).toBeVisible();
    await expect(page.getByText("Table")).toBeVisible();
    await expect(page.getByText("Mind Map")).toBeVisible();
    await expect(page.getByText("Step-by-Step")).toBeVisible();
    await expect(page.getByText("Summary")).toBeVisible();
  });

  test("selecting a sub-option calls setPreference and shows toast", async ({ page }) => {
    await createCourseWithContent(page, "FAB Apply");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("change format");
    await page.keyboard.press("Enter");
    await page.getByText("Notes panel: change formatting style").click();
    await page.getByText("Bullet Points").click();
    // Should show success toast and close popup
    await expect(page.getByText('Set note_format to "Bullet Points"')).toBeVisible({ timeout: 10_000 });
  });

  test("Back button in sub-options returns to clarify view", async ({ page }) => {
    await createCourseWithContent(page, "FAB Back");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("change");
    await page.keyboard.press("Enter");
    await page.getByText("AI responses: adjust detail level").click();
    // Should be in sub-options view with Back button
    await expect(page.getByText("Back")).toBeVisible();
    await page.getByText("Back").click();
    // Should return to clarify view
    await expect(page.getByText("What would you like to adjust?")).toBeVisible();
  });

  test("close button dismisses the popup", async ({ page }) => {
    await createCourseWithContent(page, "FAB Close");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await expect(page.getByText("Fine-tune Agent").first()).toBeVisible();
    // Click the X close button
    await page.locator(".lucide-x").first().click();
    // Popup should be gone, but FAB should still be visible
    await expect(page.getByPlaceholder('e.g. "simplify notes"')).not.toBeVisible();
    await expect(page.locator('button[title="Fine-tune Agent"]')).toBeVisible();
  });
});
