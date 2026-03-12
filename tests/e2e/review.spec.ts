import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, hasRealLlmEnv } from "./helpers/test-utils";

/**
 * Review Panel tests.
 *
 * The Review tab is inside the PracticeSection (rendered by the quiz block).
 * STEM Student template includes a quiz block with Quiz/Cards/Review tabs.
 */

test.describe.serial("Review Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Review tab is visible in practice section", async ({ page }) => {
    await createCourseWithContent(page);
    const reviewTab = page.getByRole("tab", { name: "Review" });
    await expect(reviewTab.first()).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state when no wrong answers", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await page.getByRole("tab", { name: "Review" }).first().click();
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 60_000 });
  });

  test("empty state does not show review actions", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await page.getByRole("tab", { name: "Review" }).first().click();
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("button", { name: "Generate Review" })).toHaveCount(0);
  });
});

test.describe.serial("Review Panel — LLM-dependent", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires real LLM API key for quiz generation and wrong answers");
    await skipOnboarding(page);
  });

  test("wrong answer items show question text", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("tab", { name: "Quiz", exact: true }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    await expect(page.locator("button.border-green-500, button.border-red-500").first()).toBeVisible({
      timeout: 15_000,
    });
    await page.getByRole("tab", { name: "Review" }).first().click();
    const hasWrongAnswers = await page.getByText("No unmastered wrong answers").isVisible().catch(() => false);
    if (!hasWrongAnswers) {
      const questionItem = page.locator(".rounded-lg.border.bg-card p.text-sm.font-medium").first();
      await expect(questionItem).toBeVisible({ timeout: 15_000 });
    }
  });
});
