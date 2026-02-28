import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

test.describe.serial("Quiz Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("quiz tab is visible in right panel", async ({ page }) => {
    await createCourseWithContent(page);
    // The Quiz tab button should be visible in the right panel tab bar
    const quizTab = page.getByRole("button", { name: "Quiz" });
    await expect(quizTab).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state when no problems exist", async ({ page }) => {
    await createCourseWithContent(page);
    // Click Quiz tab to ensure it's active
    await page.getByRole("button", { name: "Quiz" }).click();
    // Should show the empty state message
    await expect(page.getByText("No quiz questions yet")).toBeVisible({ timeout: 15_000 });
  });

  test("extract quiz button triggers generation", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    // Click the generate quiz button
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    // Wait for generation to complete — toast should appear with question count
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
  });

  test("generated toast shows question count", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    // Toast message format: "Generated N questions"
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
  });

  test("question text and type badge display", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Type badge (e.g., "MC", "TF") should be visible
    const typeBadge = page.locator('[class*="badge"]').first();
    await expect(typeBadge).toBeVisible({ timeout: 15_000 });
    // Question text should be displayed
    const questionText = page.locator("p.text-sm.font-medium").first();
    await expect(questionText).toBeVisible({ timeout: 15_000 });
  });

  test("question counter shows 'Question X of Y'", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // "Question X of Y" counter (English locale: "Question 1 of N")
    await expect(page.getByText(/Question\s+1\s+of\s+\d+/)).toBeVisible({ timeout: 15_000 });
  });

  test("score badge shows correct count", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Score badge: "0/0 correct" initially
    await expect(page.getByText(/\d+\/\d+\s+correct/)).toBeVisible({ timeout: 15_000 });
  });

  test("MC options render as clickable buttons", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // MC options should be displayed as buttons with letter prefixes (A., B., C., D.)
    const optionBtn = page.locator("button").filter({ hasText: /^[A-D]\./ }).first();
    await expect(optionBtn).toBeVisible({ timeout: 15_000 });
    await expect(optionBtn).toBeEnabled();
  });

  test("clicking an option selects it visually", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Click the first option — it should get selected (border-primary class)
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    // After clicking, the option submits and shows result feedback (green or red border)
    await expect(firstOption).toHaveClass(/border-(primary|green|red)/, { timeout: 15_000 });
  });

  test("submitting answer shows correct/incorrect feedback", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Click the first option to submit answer
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    // Should show either CheckCircle (green) or XCircle (red) icon
    const feedback = page.locator("svg.text-green-600, svg.text-red-600").first();
    await expect(feedback).toBeVisible({ timeout: 15_000 });
  });

  test("correct answer shows green indicator", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Click the first option
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    // After submission, the correct answer option should have green border/background
    const greenOption = page.locator("button.border-green-500").first();
    await expect(greenOption).toBeVisible({ timeout: 15_000 });
  });

  test("options disabled after answering", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Click to answer
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    // Wait for the result feedback
    await expect(page.locator("button.border-green-500, button.border-red-500").first()).toBeVisible({
      timeout: 15_000,
    });
    // All MC option buttons should be disabled after answering
    const allOptions = page.locator("button").filter({ hasText: /^[A-D]\./ });
    const count = await allOptions.count();
    for (let i = 0; i < count; i++) {
      await expect(allOptions.nth(i)).toBeDisabled();
    }
  });

  test("explanation appears after answering", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Answer the question
    const firstOption = page.locator("button").filter({ hasText: /^A\./ }).first();
    await expect(firstOption).toBeVisible({ timeout: 15_000 });
    await firstOption.click();
    // Explanation section should appear
    await expect(page.getByText("Explanation:")).toBeVisible({ timeout: 15_000 });
  });

  test("Next button advances to next question", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Verify we start at question 1
    await expect(page.getByText(/Question\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    // Click Next button
    await page.getByRole("button", { name: "Next" }).click();
    // Should now show question 2
    await expect(page.getByText(/Question\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
  });

  test("Prev button goes to previous question", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Quiz" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Quiz from Content/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ questions/)).toBeVisible({ timeout: 30_000 });
    // Go to question 2
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Question\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
    // Go back to question 1
    await page.getByRole("button", { name: "Prev" }).click();
    await expect(page.getByText(/Question\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
  });
});
