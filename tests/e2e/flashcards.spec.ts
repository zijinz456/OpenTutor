import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseWithContent,
  ensureRightPanelVisible,
  hasRealLlmEnv,
  openRightTab,
} from "./helpers/test-utils";

test.describe.serial("Flashcard Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Cards tab is visible in right panel", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    const cardsTab = page.getByTestId("right-tab-flashcards").last();
    await expect(cardsTab).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state with generate button", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    await expect(page.getByText("No flashcards yet")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /Generate Flashcards/ })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("generate button triggers flashcard creation", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
  });
});

test.describe.serial("Flashcard Panel — LLM-dependent", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires real LLM API key for flashcard generation");
    await skipOnboarding(page);
  });

  test("card counter shows 'Card X of Y'", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Card\s+1\s+of\s+\d+/)).toBeVisible({ timeout: 15_000 });
  });

  test("shows front text by default", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Question")).toBeVisible({ timeout: 15_000 });
  });

  test("clicking card flips to back", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    const cardArea = page.locator(".cursor-pointer").first();
    await expect(cardArea).toBeVisible({ timeout: 15_000 });
    await cardArea.click();
    await expect(page.getByText("Answer")).toBeVisible({ timeout: 15_000 });
  });

  test("FSRS rating buttons appear after flip", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    const cardArea = page.locator(".cursor-pointer").first();
    await cardArea.click();
    await expect(page.getByText("Answer")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Again" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Hard" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Good" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Easy" })).toBeVisible({ timeout: 15_000 });
  });

  test("clicking Good rating advances to next card", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    const cardArea = page.locator(".cursor-pointer").first();
    await cardArea.click();
    await expect(page.getByRole("button", { name: "Good" })).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Good" }).click();
    await expect(page.getByText(/Card\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
  });

  test("Prev/Next buttons navigate between cards", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Card\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Prev" }).click();
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
  });

  test("Prev disabled on first card", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Prev" })).toBeDisabled();
  });

  test("flip state resets on navigation", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Card\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Prev" }).click();
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Question")).toBeVisible({ timeout: 15_000 });
  });

  test("Save New button saves flashcards", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await openRightTab(page, "flashcards");
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved flashcard set")).toBeVisible({ timeout: 15_000 });
  });

  test("difficulty and due count badges display", async ({ page }) => {
    await createCourseWithContent(page);
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Due for review/)).toBeVisible({ timeout: 15_000 });
    const difficultyBadge = page.locator('[data-slot="badge"]').filter({ hasText: /\d/ });
    await expect(difficultyBadge.first()).toBeVisible({ timeout: 15_000 });
  });
});
