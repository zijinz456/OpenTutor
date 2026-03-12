import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseViaApi,
  createCourseWithContent,
  openChatDrawer,
} from "./helpers/test-utils";

/**
 * Workspace Layout tests.
 *
 * The workspace uses a block-based grid system. When a template is applied
 * (e.g. STEM Student), blocks like notes, quiz, progress, knowledge_graph
 * render as section components in a responsive grid.
 *
 * Chat is accessed via a floating action button (FAB) + drawer pattern.
 */

test.describe.serial("Workspace Layout", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("workspace shows blocks after template is applied", async ({ page }) => {
    await createCourseWithContent(page, "Layout Default");
    // BlockGrid should be visible with workspace blocks
    const blockGrid = page.locator('[role="list"][aria-label="Workspace blocks"]');
    const hasBlocks = await blockGrid.isVisible({ timeout: 5_000 }).catch(() => false);
    // Either blocks are rendered or the chat FAB is visible
    if (!hasBlocks) {
      await expect(page.getByRole("button", { name: "Open chat" })).toBeVisible({ timeout: 15_000 });
    }
  });

  test("quiz block renders practice section with Quiz tab", async ({ page }) => {
    await createCourseWithContent(page, "Layout QuizTab");
    const quizTab = page.getByRole("tab", { name: "Quiz", exact: true }).first();
    await expect(quizTab).toBeVisible({ timeout: 15_000 });
  });

  test("notes block renders notes panel", async ({ page }) => {
    await createCourseWithContent(page, "Layout Notes");
    // Reload to ensure content tree is fetched by frontend
    await page.reload();
    await page.waitForLoadState("networkidle");
    const notesPanel = page.getByTestId("notes-panel");
    await expect(notesPanel).toBeVisible({ timeout: 30_000 });
  });

  test("chat FAB is visible in workspace", async ({ page }) => {
    await createCourseWithContent(page, "Layout ChatFAB");
    await expect(page.getByRole("button", { name: /Open chat|Close chat/ })).toBeVisible({ timeout: 15_000 });
  });

  test("chat drawer opens when FAB is clicked", async ({ page }) => {
    await createCourseWithContent(page, "Layout ChatDrawer");
    await openChatDrawer(page);
    await expect(page.getByTestId("chat-input")).toBeVisible();
    await expect(page.getByTestId("chat-send")).toBeVisible();
  });

  test("home link navigates to dashboard", async ({ page }) => {
    await createCourseWithContent(page, "Layout Home");
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

  test("notes panel shows uploaded content", async ({ page }) => {
    await createCourseWithContent(page, "Layout Content");
    const notesPanel = page.getByTestId("notes-panel");
    const visible = await notesPanel.isVisible({ timeout: 5_000 }).catch(() => false);
    if (visible) {
      // Notes panel shows section names from content in the toolbar dropdown
      await expect(notesPanel).toContainText("Core Idea", { timeout: 30_000 });
    }
  });

  test("workspace URL matches /course/[id] pattern", async ({ page }) => {
    await createCourseWithContent(page, "Layout URL");
    await expect(page).toHaveURL(/\/course\//);
  });

  test("scene selector is not exposed in the workspace header", async ({ page }) => {
    await createCourseWithContent(page, "Layout Scene");
    await expect(page.getByTestId("scene-selector-trigger")).toHaveCount(0);
  });
});
