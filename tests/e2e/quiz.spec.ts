import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, hasRealLlmEnv } from "./helpers/test-utils";

/**
 * Navigate to the practice page for a course.
 * The practice section is at /course/[id]/practice (not embedded in the block grid).
 */
async function navigateToPractice(page: import("@playwright/test").Page, courseId: string) {
  await page.goto(`/course/${courseId}/practice`);
  await page.waitForLoadState("networkidle");
}

test.describe.serial("Quiz Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("quiz tab is visible in right panel", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    const quizTab = page.getByRole("tab", { name: /Quiz|测验/i }).first();
    await expect(quizTab).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state when no problems exist", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    const quizTab = page.getByRole("tab", { name: /Quiz|测验/i }).first();
    await quizTab.click();
    await expect(page.getByText(/No quiz questions yet|没有测验/i)).toBeVisible({ timeout: 15_000 });
  });

  test("extract quiz button triggers generation", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires real LLM API key for quiz generation");
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByTestId("quiz-extract-status")).toHaveText(/Generated \d+ questions/, {
      timeout: 30_000,
    });
  });

  test("generated toast shows question count", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires real LLM API key for quiz generation");
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByTestId("quiz-extract-status")).toHaveText(/Generated \d+ questions/, {
      timeout: 30_000,
    });
  });
});

test.describe.serial("Quiz Panel — LLM-dependent", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires real LLM API key for quiz generation");
    await skipOnboarding(page);
  });

  test("question text and type badge display", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const typeBadge = page.locator('[data-slot="badge"]').first();
    await expect(typeBadge).toBeVisible({ timeout: 15_000 });
    const questionText = page.locator("p.text-sm.font-medium").first();
    await expect(questionText).toBeVisible({ timeout: 15_000 });
  });

  test("question counter shows 'Question X of Y'", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Question\s+1\s+of\s+\d+/)).toBeVisible({ timeout: 15_000 });
  });

  test("score badge shows correct count", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/\d+\/\d+\s+correct/)).toBeVisible({ timeout: 15_000 });
  });

  test("MC options render as clickable buttons", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const optionBtn = page.locator("button").filter({ hasText: /^[A-D]\./ }).first();
    await expect(optionBtn).toBeVisible({ timeout: 15_000 });
    await expect(optionBtn).toBeEnabled();
  });

  test("clicking an option selects it visually", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    await expect(firstOption).toHaveClass(/border-(primary|green|red)/, { timeout: 15_000 });
  });

  test("submitting answer shows correct/incorrect feedback", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    const feedback = page.locator("svg.text-green-600, svg.text-red-600").first();
    await expect(feedback).toBeVisible({ timeout: 15_000 });
  });

  test("correct answer shows green indicator", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    const greenOption = page.locator("button.border-green-500").first();
    await expect(greenOption).toBeVisible({ timeout: 15_000 });
  });

  test("options disabled after answering", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
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
    const allOptions = page.locator("button").filter({ hasText: /^[A-D]\./ });
    const count = await allOptions.count();
    for (let i = 0; i < count; i++) {
      await expect(allOptions.nth(i)).toBeDisabled();
    }
  });

  test("explanation appears after answering", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    await expect(page.getByText("Explanation:")).toBeVisible({ timeout: 15_000 });
  });

  test("Next button advances to next question", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Question\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Question\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
  });

  test("Prev button goes to previous question", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await navigateToPractice(page, courseId);
    await page.getByRole("tab", { name: /Quiz|测验/i }).first().click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Question\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Prev" }).click();
    await expect(page.getByText(/Question\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
  });
});
