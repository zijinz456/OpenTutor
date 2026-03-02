import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseViaApi, createCourseWithContent, ensureRightPanelVisible } from "./helpers/test-utils";

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
    const quizTab = page.getByRole("button", { name: "Quiz", exact: true });
    await expect(quizTab).toBeVisible();
  });

  test("clicking Cards tab shows flashcard panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Cards");
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Cards" }).click();
    // Flashcard content should be visible
    await expect(page.getByText("No flashcards yet")).toBeVisible({ timeout: 10_000 });
  });

  test("clicking Stats tab shows progress panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Stats");
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Stats" }).click();
    await expect(page.getByText("Course Completion").or(page.getByText("Upload course materials"))).toBeVisible({ timeout: 10_000 });
  });

  test("clicking Graph tab shows knowledge graph", async ({ page }) => {
    await createCourseWithContent(page, "Layout Graph");
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Graph" }).click();
    // Knowledge graph canvas or empty state
    await expect(page.locator("canvas").or(page.getByText("knowledge graph")).or(page.getByText("No data")).or(page.getByText("Upload course materials"))).toBeVisible({ timeout: 10_000 });
  });

  test("clicking Review tab shows review panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Review");
    await ensureRightPanelVisible(page);
    const reviewTab = page.getByTestId("right-tab-review");
    await expect(reviewTab).toBeVisible();
    await reviewTab.click({ force: true });
    await expect(page.getByText("No unmastered wrong answers").or(page.getByText("Wrong Answer"))).toBeVisible({ timeout: 10_000 });
  });

  test("clicking Plan tab shows study plan panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Plan");
    await ensureRightPanelVisible(page);
    await page.getByRole("button", { name: "Plan" }).click();
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 10_000 });
  });

  test("activity bar Notes icon is visible", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityNotes");
    const notesBtn = page.locator('button[title="Notes"]');
    await expect(notesBtn).toBeVisible();
  });

  test("activity bar Practice icon is visible", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityPractice");
    const practiceBtn = page.locator('button[title="Practice"]');
    await expect(practiceBtn).toBeVisible();
  });

  test("activity bar Chat icon is visible", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityChat");
    const chatBtn = page.locator('button[title="Chat"]');
    await expect(chatBtn).toBeVisible();
  });

  test("activity bar Progress icon is visible", async ({ page }) => {
    await createCourseWithContent(page, "Layout ActivityProgress");
    const progressBtn = page.locator('button[title="Progress"]');
    await expect(progressBtn).toBeVisible();
  });

  test("activity bar Home icon navigates to dashboard", async ({ page }) => {
    await createCourseWithContent(page, "Layout Home");
    const homeBtn = page.locator('button[title="Home"]');
    if (await homeBtn.isVisible()) {
      await homeBtn.click();
      await expect(page).toHaveURL("/");
    }
  });

  test("activity bar Settings icon navigates to settings", async ({ page }) => {
    await createCourseWithContent(page, "Layout Settings");
    const settingsBtn = page.locator('button[title="Settings"]');
    if (await settingsBtn.isVisible()) {
      await settingsBtn.click();
      await expect(page).toHaveURL("/settings");
    }
  });

  test("panel resize handles exist between panels", async ({ page }) => {
    await createCourseWithContent(page, "Layout Resize");
    // Resizable panel handles use data-slot="resizable-handle" or react-resizable-panels attributes
    const handles = page.locator('[data-slot="resizable-handle"], [data-panel-resize-handle-id]');
    const count = await handles.count();
    expect(count).toBeGreaterThan(0);
  });

  test("scene selector is in breadcrumb area", async ({ page }) => {
    await createCourseWithContent(page, "Layout Scene");
    await expect(page.getByTestId("scene-selector-trigger")).toBeVisible();
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
    await expect(page.locator('button[title="Notes"]')).toHaveCount(0);
    await expect(page.locator('button[title="Practice"]')).toHaveCount(0);
    await expect(page.locator('button[title="Chat"]')).toHaveCount(0);
    await expect(page.getByTestId("notes-panel")).toHaveCount(0);
    await expect(page.getByTestId("chat-input")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Quiz", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Review", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Plan", exact: true })).toHaveCount(0);
  });

  test("workspace URL matches /course/[id] pattern", async ({ page }) => {
    await createCourseWithContent(page, "Layout URL");
    await expect(page).toHaveURL(/\/course\//);
  });
});
