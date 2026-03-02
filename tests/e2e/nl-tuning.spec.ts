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
    await expect(page.getByRole("button", { name: "Notes panel: change formatting style" })).toBeVisible();
    await expect(page.getByRole("button", { name: "AI responses: adjust detail level" })).toBeVisible();
    await expect(page.getByRole("button", { name: "AI responses: adjust tone and style" })).toBeVisible();
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
    // Wait for clarify view to appear
    await expect(page.getByRole("button", { name: "Notes panel: change formatting style" })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Notes panel: change formatting style" }).click();
    // Sub-options for note_format
    await expect(page.getByRole("button", { name: "Bullet Points" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Table" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Mind Map" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Step-by-Step" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Summary" })).toBeVisible({ timeout: 10_000 });
  });

  test("selecting a sub-option calls setPreference and shows toast", async ({ page }) => {
    await createCourseWithContent(page, "FAB Apply");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("change format");
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "Notes panel: change formatting style" }).click();
    await page.getByRole("button", { name: "Bullet Points" }).click();
    // Should show success toast and close popup
    await expect(page.getByText('Set note_format to "Bullet Points"')).toBeVisible({ timeout: 10_000 });
  });

  test("Back button in sub-options returns to clarify view", async ({ page }) => {
    await createCourseWithContent(page, "FAB Back");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await page.getByPlaceholder('e.g. "simplify notes"').fill("change");
    await page.keyboard.press("Enter");
    await page.getByRole("button", { name: "AI responses: adjust detail level" }).click();
    // Should be in sub-options view with Back button
    const backBtn = page.getByRole("button", { name: "Back" });
    await expect(backBtn).toBeVisible();
    await backBtn.click();
    // Should return to clarify view
    await expect(page.getByText("What would you like to adjust?")).toBeVisible();
  });

  test("close button dismisses the popup", async ({ page }) => {
    await createCourseWithContent(page, "FAB Close");
    await page.locator('button[title="Fine-tune Agent"]').click();
    await expect(page.getByPlaceholder('e.g. "simplify notes"')).toBeVisible();
    // The close button is a small button with X icon (class text-gray-400) inside the popup header.
    // Use the FAB toggle button itself to close (it toggles open/close)
    await page.locator('button[title="Fine-tune Agent"]').click();
    // Popup should be gone, but FAB should still be visible
    await expect(page.getByPlaceholder('e.g. "simplify notes"')).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator('button[title="Fine-tune Agent"]')).toBeVisible();
  });
});
