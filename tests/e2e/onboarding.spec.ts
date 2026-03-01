import { expect, test } from "@playwright/test";

/**
 * Onboarding flow tests (Phase 1 -- no course content required).
 *
 * The onboarding page at /onboarding has 5 steps:
 *   1. Language  (English, Chinese, Bilingual)
 *   2. Learning Mode  (concept_first, practice_first, balanced)
 *   3. Detail Level  (concise, balanced, detailed)
 *   4. Layout Preset  (balanced, notesFocused, chatFocused)
 *   5. Completion summary with "Finish Setup" button
 */

test.describe("Onboarding flow", () => {
  // ---- redirect behaviour -----------------------------------------------

  test("redirects to /onboarding when opentutor_onboarded is not set", async ({ page }) => {
    // Do NOT call skipOnboarding -- localStorage has no flag.
    await page.goto("/");
    await expect(page).toHaveURL(/\/onboarding/, { timeout: 15_000 });
  });

  test("does NOT redirect when opentutor_onboarded is set", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("opentutor_onboarded", "true");
    });
    await page.goto("/");
    // Should stay on dashboard (URL must NOT contain /onboarding).
    await page.waitForLoadState("networkidle");
    expect(page.url()).not.toContain("/onboarding");
  });

  // ---- step 1 -----------------------------------------------------------

  test("displays step 1 language options", async ({ page }) => {
    await page.goto("/onboarding");
    // Title
    await expect(page.getByText("What language do you prefer?")).toBeVisible();
    // Three option labels (use first() since label + description both contain the text)
    await expect(page.getByText("English", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("Chinese", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("Bilingual", { exact: false }).first()).toBeVisible();
  });

  test("Continue button is disabled until option is selected", async ({ page }) => {
    await page.goto("/onboarding");
    const continueBtn = page.getByRole("button", { name: /Continue/i });
    await expect(continueBtn).toBeVisible();
    await expect(continueBtn).toBeDisabled();
  });

  test("selecting an option enables Continue button", async ({ page }) => {
    await page.goto("/onboarding");
    const continueBtn = page.getByRole("button", { name: /Continue/i });
    await expect(continueBtn).toBeDisabled();
    // Select "English"
    await page.getByText("English", { exact: false }).first().click();
    await expect(continueBtn).toBeEnabled();
  });

  // ---- full walkthrough -------------------------------------------------

  test("navigates through all 5 steps", async ({ page }) => {
    await page.goto("/onboarding");

    // Step 1 -- Language
    await expect(page.getByText("What language do you prefer?")).toBeVisible();
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Step 2 -- Learning Mode
    await expect(page.getByText("How do you prefer to learn?")).toBeVisible();
    await page.getByText("Concept First").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Step 3 -- Detail Level
    await expect(page.getByText("How detailed should notes be?")).toBeVisible();
    await page.getByText("Concise").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Step 4 -- Layout Preset
    await expect(page.getByText("Choose your workspace layout")).toBeVisible();
    await page.getByText("Split + Chat").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Step 5 -- Summary / Finish
    await expect(page.getByText("You're all set!")).toBeVisible();
    await expect(page.getByRole("button", { name: /Finish Setup/i })).toBeVisible();
  });

  // ---- step indicators --------------------------------------------------

  test("step indicators show active/done states", async ({ page }) => {
    await page.goto("/onboarding");

    // Step 1 is current -- sidebar should show "1" as active.
    const sidebar = page.locator("aside");
    // The first step button should have bg-white/15 (active marker).
    // After completing step 1, it should get green checkmark.
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Now on step 2 -- step 1 indicator should be green / done (contains SVG check).
    const step1Indicator = sidebar.locator("button").first();
    await expect(step1Indicator.locator("svg")).toBeVisible(); // green check icon
  });

  // ---- back button ------------------------------------------------------

  test("Back button returns to previous step", async ({ page }) => {
    await page.goto("/onboarding");

    // Move to step 2
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByText("How do you prefer to learn?")).toBeVisible();

    // Press Back
    await page.getByRole("button", { name: /Back/i }).click();
    await expect(page.getByText("What language do you prefer?")).toBeVisible();
  });

  // ---- clicking completed step in sidebar -------------------------------

  test("clicking completed step navigates back", async ({ page }) => {
    await page.goto("/onboarding");

    // Complete step 1
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();
    await expect(page.getByText("How do you prefer to learn?")).toBeVisible();

    // Click step 1 in the sidebar (the Language button)
    const sidebar = page.locator("aside");
    await sidebar.getByText("Language").click();
    await expect(page.getByText("What language do you prefer?")).toBeVisible();
  });

  // ---- final step summary -----------------------------------------------

  test("final step shows preferences summary", async ({ page }) => {
    await page.goto("/onboarding");

    // Walk through all 4 selection steps
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Concept First").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Concise").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Split + Chat").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Step 5 -- summary
    await expect(page.getByText("Your preferences:")).toBeVisible();
    // Each selected dimension should appear in the summary
    await expect(page.getByText("language:")).toBeVisible();
    await expect(page.getByText("learning mode:")).toBeVisible();
    await expect(page.getByText("detail level:")).toBeVisible();
    await expect(page.getByText("layout preset:")).toBeVisible();
  });

  // ---- Finish Setup saves & redirects -----------------------------------

  test("Finish Setup saves and redirects to dashboard", async ({ page }) => {
    await page.goto("/onboarding");

    // Complete all steps quickly
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Balanced Mix").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Moderate").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Focus Mode").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    // Step 5 -- Finish
    await page.getByRole("button", { name: /Finish Setup/i }).click();

    // Wait for API calls to save each preference + redirect to dashboard
    await expect(page).toHaveURL("/", { timeout: 60_000 });
  });

  // ---- localStorage flag ------------------------------------------------

  test("localStorage flag is set after completing onboarding", async ({ page }) => {
    await page.goto("/onboarding");

    // Complete all steps
    await page.getByText("English", { exact: false }).first().click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Practice First").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Detailed", { exact: true }).click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByText("Triple Panel").click();
    await page.getByRole("button", { name: /Continue/i }).click();

    await page.getByRole("button", { name: /Finish Setup/i }).click();
    await expect(page).toHaveURL("/", { timeout: 60_000 });

    const flag = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
    expect(flag).toBe("true");
  });
});
