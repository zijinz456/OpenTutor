import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

test.describe.serial("Flashcard Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("Cards tab is visible in right panel", async ({ page }) => {
    await createCourseWithContent(page);
    // The "Cards" tab button should be visible in the right panel tab bar
    const cardsTab = page.getByRole("button", { name: "Cards" });
    await expect(cardsTab).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state with generate button", async ({ page }) => {
    await createCourseWithContent(page);
    // Click Cards tab to switch to flashcards
    await page.getByRole("button", { name: "Cards" }).click();
    // Should show the empty state message
    await expect(page.getByText("No flashcards yet")).toBeVisible({ timeout: 15_000 });
    // Generate button should be present
    await expect(page.getByRole("button", { name: /Generate Flashcards/ })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("generate button triggers flashcard creation", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    // Toast should show generated count
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
  });

  test("card counter shows 'Card X of Y'", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Counter text: "Card 1 of N"
    await expect(page.getByText(/Card\s+1\s+of\s+\d+/)).toBeVisible({ timeout: 15_000 });
  });

  test("shows front text by default", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Front label ("Question") should be shown on the card
    await expect(page.getByText("Question")).toBeVisible({ timeout: 15_000 });
  });

  test("clicking card flips to back", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Click the card area to flip it
    const cardArea = page.locator(".cursor-pointer").first();
    await expect(cardArea).toBeVisible({ timeout: 15_000 });
    await cardArea.click();
    // After flip, should show "Answer" label
    await expect(page.getByText("Answer")).toBeVisible({ timeout: 15_000 });
  });

  test("FSRS rating buttons appear after flip", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Flip the card
    const cardArea = page.locator(".cursor-pointer").first();
    await cardArea.click();
    await expect(page.getByText("Answer")).toBeVisible({ timeout: 15_000 });
    // FSRS rating buttons should appear: Again, Hard, Good, Easy
    await expect(page.getByRole("button", { name: "Again" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Hard" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Good" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Easy" })).toBeVisible({ timeout: 15_000 });
  });

  test("clicking Good rating advances to next card", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Verify we start at card 1
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    // Flip the card
    const cardArea = page.locator(".cursor-pointer").first();
    await cardArea.click();
    await expect(page.getByRole("button", { name: "Good" })).toBeVisible({ timeout: 15_000 });
    // Click Good rating
    await page.getByRole("button", { name: "Good" }).click();
    // Should advance to card 2
    await expect(page.getByText(/Card\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
  });

  test("Prev/Next buttons navigate between cards", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Navigate to card 2 using Next
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Card\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
    // Navigate back to card 1 using Prev
    await page.getByRole("button", { name: "Prev" }).click();
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
  });

  test("Prev disabled on first card", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // On card 1, Prev should be disabled
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Prev" })).toBeDisabled();
  });

  test("flip state resets on navigation", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Navigate to card 2, then back to card 1
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText(/Card\s+2\s+of/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Prev" }).click();
    await expect(page.getByText(/Card\s+1\s+of/)).toBeVisible({ timeout: 15_000 });
    // Card should show front ("Question") after navigation, not back ("Answer")
    await expect(page.getByText("Question")).toBeVisible({ timeout: 15_000 });
  });

  test("Save New button saves flashcards", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Click Save New button
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved flashcard set")).toBeVisible({ timeout: 15_000 });
  });

  test("difficulty and due count badges display", async ({ page }) => {
    await createCourseWithContent(page);
    await page.getByRole("button", { name: "Cards" }).click();
    const generateBtn = page.getByRole("button", { name: /Generate Flashcards/ });
    await expect(generateBtn).toBeVisible({ timeout: 15_000 });
    await generateBtn.click();
    await expect(page.getByText(/Generated \d+ flashcards/)).toBeVisible({ timeout: 30_000 });
    // Due count badge should be visible (e.g., "N Due for review")
    await expect(page.getByText(/Due for review/)).toBeVisible({ timeout: 15_000 });
    // Difficulty badge should also be visible in the header
    const difficultyBadge = page.locator('[class*="badge"]').filter({ hasText: /\d/ });
    await expect(difficultyBadge.first()).toBeVisible({ timeout: 15_000 });
  });
});
