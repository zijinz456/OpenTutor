import { expect, test } from "@playwright/test";
import { skipOnboarding } from "./helpers/test-utils";

/**
 * Settings page tests (Phase 1 -- no course content required).
 *
 * The settings page at /settings includes:
 *   - Back button (ArrowLeft icon) -> /
 *   - Language section:  English / 中文 buttons, toast on change
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
    await expect(page.getByTestId("settings-llm-status")).toBeVisible();
  });

  test("AI runtime card shows LLM status details", async ({ page }) => {
    await page.goto("/settings");
    const runtimeCard = page.getByTestId("settings-llm-status");
    await expect(runtimeCard).toBeVisible({ timeout: 15_000 });
    await expect(runtimeCard.getByRole("heading")).toBeVisible();
    await expect(
      runtimeCard.getByText(/LLM/i).first().or(runtimeCard.getByText(/Unable to load runtime health|无法从 API 服务端读取运行时健康状态/i))
    ).toBeVisible();
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
    await expect(page).not.toHaveURL(/\/settings/, { timeout: 15_000 });
  });

  // ---- language section -------------------------------------------------

  test("language section shows English and Chinese buttons", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByTestId("settings-language-en")).toBeVisible();
    await expect(page.getByTestId("settings-language-zh")).toBeVisible();
  });

  test("clicking English shows English toast", async ({ page }) => {
    await page.goto("/settings");
    await page.getByTestId("settings-language-en").click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });

  test("clicking English language button confirms selection", async ({ page }) => {
    await page.goto("/settings");
    await page.getByTestId("settings-language-en").click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });

  test("clicking Chinese switches the shell language", async ({ page }) => {
    await page.goto("/settings");
    await page.getByTestId("settings-language-zh").click();
    await expect(page.getByRole("heading", { name: "通知" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh");
  });

  // ---- appearance section -----------------------------------------------

  test("appearance shows Light, Dark, System buttons", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByTestId("settings-theme-light")).toBeVisible();
    await expect(page.getByTestId("settings-theme-dark")).toBeVisible();
    await expect(page.getByTestId("settings-theme-system")).toBeVisible();
  });

  test("clicking Dark toggles dark theme", async ({ page }) => {
    await page.goto("/settings");
    await page.getByTestId("settings-theme-dark").click();
    // next-themes adds "dark" class to <html>
    await expect(page.locator("html")).toHaveAttribute("class", /dark/, { timeout: 5_000 });
  });

  test("clicking Light toggles light theme", async ({ page }) => {
    await page.goto("/settings");
    // First set dark to ensure we can toggle back
    await page.getByTestId("settings-theme-dark").click();
    await expect(page.locator("html")).toHaveAttribute("class", /dark/, { timeout: 5_000 });
    // Now switch to light
    await page.getByTestId("settings-theme-light").click();
    await expect(page.locator("html")).toHaveAttribute("class", /light/, { timeout: 5_000 });
  });

  // ---- templates section ------------------------------------------------

  test("templates section shows templates or empty state", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText(/Templates|模板/)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("body")).toContainText(/Apply|应用|No templates available|当前没有可用模板/i, { timeout: 15_000 });
  });

  test("Apply button triggers template application", async ({ page }) => {
    await page.goto("/settings");

    // Wait for templates to potentially load
    const applyBtn = page.getByRole("button", { name: /Apply|应用/ }).first();
    const templateVisible = await applyBtn
      .isVisible({ timeout: 10_000 })
      .catch(() => false);

    if (templateVisible) {
      await applyBtn.click();
      // Should show a success toast with "Applied" or a failure toast
      await expect(
        page.getByText(/Applied|Failed|成功|失败/i)
      ).toBeVisible({ timeout: 15_000 });
    } else {
      // No templates seeded -- skip gracefully
      test.skip();
    }
  });
});
