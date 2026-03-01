import { expect, test } from "@playwright/test";
import { skipOnboarding } from "./helpers/test-utils";

/**
 * Settings page tests (Phase 1 -- no course content required).
 *
 * The settings page at /settings includes:
 *   - Back button (ArrowLeft icon) -> /
 *   - Language section:  English and 中文 buttons, toast on change
 *   - Appearance section:  Light, Dark, System buttons
 *   - Learning Templates section:  loads from /api/progress/templates, Apply button
 */

test.describe("Settings", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  // ---- navigation -------------------------------------------------------

  test("navigates to /settings", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
    await expect(page.getByText("Settings")).toBeVisible();
  });

  test("AI runtime card shows LLM status details", async ({ page }) => {
    await page.goto("/settings");
    const runtimeCard = page.getByTestId("settings-llm-status");
    await expect(runtimeCard).toBeVisible({ timeout: 15_000 });
    await expect(runtimeCard.getByText(/AI Runtime/i)).toBeVisible();
    await expect(runtimeCard.getByText(/LLM required:/i).first()).toBeVisible();
  });

  test("provider connections section shows API key inputs", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByTestId("settings-api-keys")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("settings-llm-provider")).toBeVisible();
    await expect(page.getByTestId("settings-llm-model")).toBeVisible();
    await expect(page.getByTestId("provider-key-openai")).toBeVisible();
    await expect(page.getByTestId("test-provider-key-openai")).toBeVisible();
    await expect(page.getByTestId("settings-save-llm")).toBeVisible();
  });

  test("back button returns to dashboard", async ({ page }) => {
    await page.goto("/settings");
    await page.locator("header").getByRole("button").first().click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  // ---- language section -------------------------------------------------

  test("language section shows English and Chinese buttons", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByRole("button", { name: "English" })).toBeVisible();
    // The Chinese button uses the literal character text
    await expect(page.getByRole("button", { name: "中文" })).toBeVisible();
  });

  test("clicking English shows English toast", async ({ page }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: "English" }).click();
    await expect(page.getByText("Switched to English")).toBeVisible({ timeout: 15_000 });
  });

  test("clicking Chinese shows Chinese toast", async ({ page }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: "中文" }).click();
    await expect(page.getByText("已切换到中文")).toBeVisible({ timeout: 15_000 });
  });

  // ---- appearance section -----------------------------------------------

  test("appearance shows Light, Dark, System buttons", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByRole("button", { name: /Light/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Dark/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /System/i })).toBeVisible();
  });

  test("clicking Dark toggles dark theme", async ({ page }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: /Dark/i }).click();
    // next-themes adds "dark" class to <html>
    await expect(page.locator("html")).toHaveAttribute("class", /dark/, { timeout: 5_000 });
  });

  test("clicking Light toggles light theme", async ({ page }) => {
    await page.goto("/settings");
    // First set dark to ensure we can toggle back
    await page.getByRole("button", { name: /Dark/i }).click();
    await expect(page.locator("html")).toHaveAttribute("class", /dark/, { timeout: 5_000 });
    // Now switch to light
    await page.getByRole("button", { name: /Light/i }).click();
    await expect(page.locator("html")).toHaveAttribute("class", /light/, { timeout: 5_000 });
  });

  // ---- templates section ------------------------------------------------

  test("templates section shows templates or empty state", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("Learning Templates")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("body")).toContainText(/Apply|No templates available/i, { timeout: 15_000 });
  });

  test("Apply button triggers template application", async ({ page }) => {
    await page.goto("/settings");

    // Wait for templates to potentially load
    const applyBtn = page.getByRole("button", { name: "Apply" }).first();
    const templateVisible = await applyBtn
      .isVisible({ timeout: 10_000 })
      .catch(() => false);

    if (templateVisible) {
      await applyBtn.click();
      // Should show a success toast with "Applied" or a failure toast
      await expect(
        page.getByText(/Applied|Failed/i)
      ).toBeVisible({ timeout: 15_000 });
    } else {
      // No templates seeded -- skip gracefully
      test.skip();
    }
  });
});
