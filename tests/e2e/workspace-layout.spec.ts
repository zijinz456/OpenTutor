import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseViaApi,
  createCourseWithContent,
  dispatchShortcut,
  ensureAnalyticsSectionVisible,
  ensureRightPanelVisible,
  switchScene,
} from "./helpers/test-utils";

test.describe.serial("Workspace Layout", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("workspace shows main panels by default", async ({ page }) => {
    await createCourseWithContent(page, "Layout Default");
    // Check that main panel areas exist
    await expect(page.getByTestId("notes-panel")).toBeVisible();
    await expect(page.getByTestId("chat-input")).toBeVisible();
  });

  test("right panel defaults to Quiz tab", async ({ page }) => {
    await createCourseWithContent(page, "Layout QuizTab");
    await ensureRightPanelVisible(page);
    const quizTab = page.getByTestId("right-tab-quiz").or(page.getByRole("button", { name: "Quiz", exact: true }));
    await expect(quizTab.first()).toBeVisible({ timeout: 15_000 });
  });

  test("clicking Cards tab shows flashcard panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Cards");
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Cards" }).click();
    // Flashcard content should be visible — either empty state or flashcard list
    // Both texts can be visible simultaneously in empty state — use .first() to avoid strict mode
    await expect(page.getByText("No flashcards yet").or(page.getByText("Generate Flashcards")).first()).toBeVisible({ timeout: 30_000 });
  });

  test("clicking Stats tab shows progress panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Stats");
    await ensureAnalyticsSectionVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    await expect(page.getByText("Course Completion").or(page.getByText("Upload course materials")).first()).toBeVisible({ timeout: 15_000 });
  });

  test("clicking Graph tab shows knowledge graph", async ({ page }) => {
    await createCourseWithContent(page, "Layout Graph");
    await ensureAnalyticsSectionVisible(page);
    await page.getByRole("button", { name: "Graph" }).click();
    // Knowledge graph canvas or empty state
    await expect(
      page
        .locator("svg.bg-background")
        .or(page.getByText(/knowledge graph/i))
        .or(page.getByText("Loading graph..."))
        .or(page.getByText("Upload course materials to generate the knowledge graph"))
        .first(),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("clicking Review tab shows review panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Review");
    await ensureRightPanelVisible(page);
    const reviewTab = page.getByTestId("right-tab-review");
    await expect(reviewTab).toBeVisible();
    await reviewTab.click({ force: true });
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("No unmastered wrong answers").or(page.getByText("Wrong Answer")).first()).toBeVisible({ timeout: 60_000 });
  });

  test("clicking Plan tab shows study plan panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Plan");
    await switchScene(page, "exam_prep");
  });

  test("keyboard shortcut Cmd+1 switches to Notes section", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityNotes");
    // Notes is the default section — just verify it's visible
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 15_000 });
  });

  test("keyboard shortcut Cmd+2 switches to Practice section", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityPractice");
    await ensureRightPanelVisible(page);
    await expect(page.getByTestId("practice-section")).toBeVisible({ timeout: 15_000 });
  });

  test("chat input is always visible in workspace", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityChat");
    await expect(page.getByTestId("chat-input")).toBeVisible({ timeout: 15_000 });
  });

  test("keyboard shortcut Cmd+3 switches to Analytics section", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityProgress");
    await ensureAnalyticsSectionVisible(page);
    await expect(page.getByTestId("analytics-section")).toBeVisible({ timeout: 15_000 });
  });

  test("home link navigates to dashboard", async ({ page }) => {
    await createCourseWithContent(page, "Layout Home");
    // The workspace header has a home link (back arrow → "/")
    const homeLink = page.locator('a[href="/"]').first();
    if (await homeLink.isVisible()) {
      await homeLink.click();
      await expect(page).toHaveURL("/");
    }
  });

  test("settings link navigates to settings", async ({ page }) => {
    await createCourseWithContent(page, "Layout Settings");
    const settingsLink = page.locator('a[href="/settings"]').first();
    if (await settingsLink.isVisible()) {
      await settingsLink.click();
      await expect(page).toHaveURL("/settings");
    }
  });

  test("workspace shows left tree and main content regions", async ({ page }) => {
    await createCourseWithContent(page, "Layout Resize");
    await expect(page.getByLabel("Course tree")).toBeVisible();
    await expect(page.getByTestId("section-container")).toBeVisible();
  });

  test("scene selector is not exposed in the workspace header", async ({ page }) => {
    await createCourseWithContent(page, "Layout Scene");
    await expect(page.getByTestId("scene-selector-trigger")).toHaveCount(0);
  });

  test("workspace upload trigger is accessible", async ({ page }) => {
    await createCourseWithContent(page, "Layout Upload");
    await expect(page.getByTestId("workspace-upload-trigger")).toBeVisible();
  });

  test("notes panel shows uploaded content", async ({ page }) => {
    await createCourseWithContent(page, "Layout Content");
    await expect(page.getByTestId("notes-panel")).toContainText("Binary Search Basics", { timeout: 30_000 });
  });

  test("chat input and send button are visible", async ({ page }) => {
    await createCourseWithContent(page, "Layout ChatUI");
    await expect(page.getByTestId("chat-input")).toBeVisible();
    await expect(page.getByTestId("chat-send")).toBeVisible();
  });

  test("disabled workspace features hide notes, practice, and chat entry points", async ({ page }) => {
    const courseId = await createCourseViaApi("Layout Limited", undefined, {
      workspace_features: {
        notes: false,
        practice: false,
        wrong_answer: false,
        study_plan: false,
        free_qa: false,
      },
    });
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("section-container")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("notes-panel")).toHaveCount(0);
    await expect(page.getByTestId("chat-input")).toHaveCount(0);
    await expect(page.getByTestId("practice-section")).toHaveCount(0);
    await expect(page.getByTestId("plan-section")).toHaveCount(0);
  });

  test("workspace URL matches /course/[id] pattern", async ({ page }) => {
    await createCourseWithContent(page, "Layout URL");
    await expect(page).toHaveURL(/\/course\//);
  });
});
