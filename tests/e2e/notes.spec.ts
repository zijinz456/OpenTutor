import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseWithContent,
  expectGeneratedNotes,
  hasRealLlmEnv,
} from "./helpers/test-utils";

test.describe.serial("Notes Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("notes panel is visible with data-testid", async ({ page }) => {
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
  });

  test("shows uploaded content title 'Binary Search Basics'", async ({ page }) => {
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toContainText("Binary Search Basics", {
      timeout: 30_000,
    });
  });

  test("content tree shows sections: Core Idea, Why It Matters, Common Pitfalls", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await expect(panel).toContainText("Core Idea", { timeout: 15_000 });
    await expect(panel).toContainText("Why It Matters", { timeout: 15_000 });
    await expect(panel).toContainText("Common Pitfalls", { timeout: 15_000 });
  });

  test("TOC sidebar shows collapsible navigation", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // TOC sidebar should show "Table of Contents" header
    await expect(panel.getByText("Table of Contents")).toBeVisible({ timeout: 15_000 });
    // Section titles should be visible in the TOC
    await expect(panel.locator("button", { hasText: "Binary Search Basics" }).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("clicking TOC item highlights it", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Click a TOC item
    const tocItem = panel.locator("button", { hasText: "Core Idea" }).first();
    await expect(tocItem).toBeVisible({ timeout: 15_000 });
    await tocItem.click();
    // After clicking, the item should have the active style (bg-muted + font-medium)
    await expect(tocItem).toHaveClass(/font-medium/, { timeout: 5_000 });
  });

  test("Hide TOC button toggles sidebar visibility", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // TOC should be visible initially
    await expect(panel.getByText("Table of Contents")).toBeVisible({ timeout: 15_000 });
    // Click "Hide TOC" button
    await panel.getByRole("button", { name: /Hide TOC/ }).click();
    // TOC header should be hidden
    await expect(panel.getByText("Table of Contents")).not.toBeVisible({ timeout: 5_000 });
  });

  test("Generate button triggers AI note generation", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("notes-generate").click();
    // Wait for the generation to complete (preview should appear)
    await expect(page.getByTestId("notes-preview")).toBeVisible({ timeout: 30_000 });
  });

  test("generated notes preview appears", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("notes-generate").click();
    const preview = page.getByTestId("notes-preview");
    await expect(preview).toBeVisible({ timeout: 30_000 });
    // Preview should contain the "AI note preview" label
    await expect(preview).toContainText("AI note preview", { timeout: 15_000 });
  });

  test("preview shows generated notes content", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("notes-generate").click();
    await expectGeneratedNotes(page);
  });

  test("Save New button saves notes and shows toast", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("notes-generate").click();
    await expect(page.getByTestId("notes-preview")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved AI notes")).toBeVisible({ timeout: 15_000 });
  });

  test("generate button disabled during generation", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    await createCourseWithContent(page);
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("notes-generate").click();
    // The button should be disabled immediately after clicking
    await expect(page.getByTestId("notes-generate")).toBeDisabled();
    // Wait for generation to finish so the button re-enables
    await expect(page.getByTestId("notes-preview")).toBeVisible({ timeout: 30_000 });
  });

  test("markdown content renders headings correctly", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // The content tree renders headings as h1, h2, h3 elements
    // "Binary Search Basics" is the top-level heading
    await expect(panel.locator("h1, h2, h3").first()).toBeVisible({ timeout: 15_000 });
  });

  test("notes panel scrolls when content is long", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // The scroll area should exist and be functional
    const scrollArea = panel.locator('[data-radix-scroll-area-viewport], [class*="overflow"]').first();
    await expect(scrollArea).toBeVisible({ timeout: 15_000 });
  });

  test("Show TOC button restores sidebar", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Hide the TOC first
    await panel.getByRole("button", { name: /Hide TOC/ }).click();
    await expect(panel.getByText("Table of Contents")).not.toBeVisible({ timeout: 5_000 });
    // Now click "Show TOC" to restore it
    await panel.getByRole("button", { name: /Show TOC/ }).click();
    await expect(panel.getByText("Table of Contents")).toBeVisible({ timeout: 5_000 });
  });
});
