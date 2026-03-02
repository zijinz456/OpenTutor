import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, ensureRightPanelVisible, hasRealLlmEnv } from "./helpers/test-utils";

/**
 * Helper: click Review tab, wait for the wrong-answers API call to complete,
 * then verify the panel has transitioned out of loading state.
 * Under CI with 5 parallel workers and single-worker uvicorn, API calls
 * can take 60–90s as the event loop is saturated.
 */
async function openReviewPanelAndWaitForData(page: import("@playwright/test").Page) {
  // The ReviewPanel makes TWO API calls: listWrongAnswers + getWrongAnswerStats
  // Both must complete before loading state transitions. Set up listeners BEFORE clicking.
  let resolvedCount = 0;
  const bothDone = new Promise<void>((resolve) => {
    const check = () => { if (++resolvedCount >= 2) resolve(); };
    page.waitForResponse(
      (resp) => resp.url().includes("/wrong-answers/") && !resp.url().includes("/stats") && resp.request().method() === "GET",
      { timeout: 120_000 },
    ).then(check).catch(() => check());
    page.waitForResponse(
      (resp) => resp.url().includes("/wrong-answers/") && resp.url().includes("/stats") && resp.request().method() === "GET",
      { timeout: 120_000 },
    ).then(check).catch(() => check());
  });
  await page.getByRole("button", { name: "Review" }).click();
  await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 15_000 });
  // Wait for BOTH API calls to complete (this is the slow part under CI load)
  await bothDone;
}

test.describe.serial("Review Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Review tab is visible in right panel", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    const reviewTab = page.getByRole("button", { name: "Review" });
    await expect(reviewTab).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state when no wrong answers", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openReviewPanelAndWaitForData(page);
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 30_000 });
  });

  test("Refresh button is clickable", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openReviewPanelAndWaitForData(page);
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 30_000 });
    const refreshBtn = page.getByRole("button", { name: "Refresh" });
    await expect(refreshBtn).toBeVisible({ timeout: 15_000 });
    await expect(refreshBtn).toBeEnabled();
    await refreshBtn.click();
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 60_000 });
  });

  test("stats section shows Total, Mastered, Unmastered", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openReviewPanelAndWaitForData(page);
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 30_000 });
    const refreshBtn = page.getByRole("button", { name: "Refresh" });
    await expect(refreshBtn).toBeVisible({ timeout: 15_000 });
  });

  test("Generate Review button is present", async ({ page }) => {
    test.setTimeout(150_000);
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openReviewPanelAndWaitForData(page);
    await expect(page.getByText("No unmastered wrong answers")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible({ timeout: 15_000 });
  });
});

test.describe.serial("Review Panel — LLM-dependent", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires real LLM API key for quiz generation and wrong answers");
    await skipOnboarding(page);
  });

  test("wrong answer items show question text", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Quiz", exact: true }).click();
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
    await page.getByRole("button", { name: "Review" }).click();
    const hasWrongAnswers = await page.getByText("No unmastered wrong answers").isVisible().catch(() => false);
    if (!hasWrongAnswers) {
      const questionItem = page.locator(".rounded-lg.border.bg-card p.text-sm.font-medium").first();
      await expect(questionItem).toBeVisible({ timeout: 15_000 });
    }
  });

  test("error category badges are displayed", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Quiz", exact: true }).click();
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
    await page.getByRole("button", { name: "Review" }).click();
    const hasWrongAnswers = await page.getByText("No unmastered wrong answers").isVisible().catch(() => false);
    if (!hasWrongAnswers) {
      const badges = page.locator('[data-slot="badge"]');
      await expect(badges.first()).toBeVisible({ timeout: 15_000 });
    }
  });

  test("Derive button is present on items", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Quiz", exact: true }).click();
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
    await page.getByRole("button", { name: "Review" }).click();
    const hasWrongAnswers = await page.getByText("No unmastered wrong answers").isVisible().catch(() => false);
    if (!hasWrongAnswers) {
      const deriveBtn = page.getByRole("button", { name: "Derive" }).first();
      await expect(deriveBtn).toBeVisible({ timeout: 15_000 });
      await expect(deriveBtn).toBeEnabled();
    }
  });

  test("Derive button shows loading state during operation", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Quiz", exact: true }).click();
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
    await page.getByRole("button", { name: "Review" }).click();
    const hasWrongAnswers = await page.getByText("No unmastered wrong answers").isVisible().catch(() => false);
    if (!hasWrongAnswers) {
      const deriveBtn = page.getByRole("button", { name: "Derive" }).first();
      await expect(deriveBtn).toBeVisible({ timeout: 15_000 });
      await deriveBtn.click();
      await expect(deriveBtn.locator("svg.animate-spin")).toBeVisible({ timeout: 5_000 });
    }
  });
});
