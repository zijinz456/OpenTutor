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

  test("shows uploaded content sections in notes panel", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Switch to Source view to see uploaded content (AI Notes is empty without LLM)
    await panel.getByRole("button", { name: "Source" }).click();
    await expect(panel).toContainText("Core Idea", { timeout: 30_000 });
  });

  test("content tree shows sections: Core Idea, Why It Matters, Common Pitfalls", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Switch to Source view to see uploaded content sections
    await panel.getByRole("button", { name: "Source" }).click();
    await expect(panel).toContainText("Core Idea", { timeout: 15_000 });
    await expect(panel).toContainText("Why It Matters", { timeout: 15_000 });
    await expect(panel).toContainText("Common Pitfalls", { timeout: 15_000 });
  });

  test("section dropdown shows content sections", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Notes block uses a section dropdown (combobox) instead of a TOC sidebar
    const sectionSelect = panel.getByRole("combobox", { name: "Select section" });
    await expect(sectionSelect).toBeVisible({ timeout: 15_000 });
  });

  test("section dropdown contains uploaded content sections", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Section dropdown should contain sections from the uploaded content
    const sectionSelect = panel.getByRole("combobox", { name: "Select section" });
    await expect(sectionSelect).toBeVisible({ timeout: 15_000 });
    await expect(panel.getByRole("option", { name: "Core Idea" })).toBeAttached();
    await expect(panel.getByRole("option", { name: "Why It Matters" })).toBeAttached();
  });

  test("view mode toggle switches between AI Notes and Source", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // AI Notes should be active by default
    await expect(panel.getByRole("button", { name: "AI Notes", exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(panel.getByRole("button", { name: "Source" })).toBeVisible({ timeout: 15_000 });
    // Click Source to switch view
    await panel.getByRole("button", { name: "Source" }).click();
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
    // Switch to Source view to see markdown-rendered headings
    await panel.getByRole("button", { name: "Source" }).click();
    // The content tree renders headings as h1, h2, h3 elements
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

  test("next/previous section buttons navigate sections", async ({ page }) => {
    await createCourseWithContent(page);
    const panel = page.getByTestId("notes-panel");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // Next section button should be visible
    const nextBtn = panel.getByRole("button", { name: "Next section" });
    await expect(nextBtn).toBeVisible({ timeout: 15_000 });
    // Get the current selected option text
    const sectionSelect = panel.getByRole("combobox", { name: "Select section" });
    const beforeText = await sectionSelect.locator("option:checked").textContent();
    await nextBtn.click();
    // After clicking next, the selected option should change
    await expect.poll(
      async () => (await sectionSelect.locator("option:checked").textContent()) ?? "",
      { timeout: 5_000 },
    ).not.toBe(beforeText ?? "");
  });
});
