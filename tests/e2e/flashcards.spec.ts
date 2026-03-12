import { expect, test } from "@playwright/test";
import {
  createCourseWithContent,
  getRealLlmTimeoutMs,
  hasRealLlmEnv,
  seedFlashcardsViaApi,
  skipOnboarding,
} from "./helpers/test-utils";

/**
 * Navigate to the practice page and open the flashcards tab.
 */
async function openFlashcards(page: import("@playwright/test").Page, courseId: string) {
  await page.goto(`/course/${courseId}/practice`);
  await page.waitForLoadState("networkidle");
  // Click the Cards/Flashcards tab
  const tab = page.getByRole("tab", { name: /Cards|Flashcards|闪卡/i }).first();
  await expect(tab).toBeVisible({ timeout: 15_000 });
  await tab.click();
}

test.describe.serial("Flashcard Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("flashcards tab is accessible from practice workspace", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await openFlashcards(page, courseId);
    await expect(page.getByRole("heading", { name: /Flashcards|闪卡/i })).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state when no flashcards exist", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await openFlashcards(page, courseId);
    await expect(page.getByText(/No flashcards yet|没有闪卡/i)).toBeVisible({ timeout: 15_000 });
  });
});

test.describe.serial("Flashcard Panel — LLM-dependent", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider for flashcard generation");
    await skipOnboarding(page);
  });

  test("review counter shows seeded flashcards", async ({ page }) => {
    test.setTimeout(getRealLlmTimeoutMs(90_000) + 30_000);
    const courseId = await createCourseWithContent(page);
    await seedFlashcardsViaApi(courseId, 3);
    await page.reload();
    await openFlashcards(page, courseId);
    await expect(page.getByText(/0\/3 reviewed/)).toBeVisible({ timeout: 30_000 });
  });

  test("shows question text by default", async ({ page }) => {
    test.setTimeout(getRealLlmTimeoutMs(90_000) + 30_000);
    const courseId = await createCourseWithContent(page);
    await seedFlashcardsViaApi(courseId, 3);
    await page.reload();
    await openFlashcards(page, courseId);
    await expect(page.getByText("Question")).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".flashcard-face").first()).toBeVisible({ timeout: 30_000 });
  });

  test("clicking card flips to answer", async ({ page }) => {
    test.setTimeout(getRealLlmTimeoutMs(90_000) + 30_000);
    const courseId = await createCourseWithContent(page);
    await seedFlashcardsViaApi(courseId, 3);
    await page.reload();
    await openFlashcards(page, courseId);
    const cardArea = page.getByRole("button").filter({ has: page.locator(".flashcard-inner") }).first();
    await expect(cardArea).toBeVisible({ timeout: 30_000 });
    await cardArea.click();
    await expect(page.getByText("Answer")).toBeVisible({ timeout: 30_000 });
  });

  test("rating buttons appear after flip", async ({ page }) => {
    test.setTimeout(getRealLlmTimeoutMs(90_000) + 30_000);
    const courseId = await createCourseWithContent(page);
    await seedFlashcardsViaApi(courseId, 3);
    await page.reload();
    await openFlashcards(page, courseId);
    const cardArea = page.getByRole("button").filter({ has: page.locator(".flashcard-inner") }).first();
    await cardArea.click();
    await expect(page.getByRole("button", { name: "Again" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Hard" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Good" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Easy" })).toBeVisible({ timeout: 30_000 });
  });

  test("clicking Good advances the review counter", async ({ page }) => {
    test.setTimeout(getRealLlmTimeoutMs(90_000) + 30_000);
    const courseId = await createCourseWithContent(page);
    await seedFlashcardsViaApi(courseId, 3);
    await page.reload();
    await openFlashcards(page, courseId);
    const cardArea = page.getByRole("button").filter({ has: page.locator(".flashcard-inner") }).first();
    await cardArea.click();
    await page.getByRole("button", { name: "Good" }).click();
    await expect(page.getByText(/1\/3 reviewed/)).toBeVisible({ timeout: 30_000 });
  });
});
