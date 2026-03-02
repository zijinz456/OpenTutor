import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, switchScene } from "./helpers/test-utils";

test.describe.serial("Internal Scene Routing", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("scene selector trigger is not visible in the workspace", async ({ page }) => {
    await createCourseWithContent(page, "Scene Hidden");
    await expect(page.getByTestId("scene-selector-trigger")).toHaveCount(0);
  });

  test("exam prep workflow opens the study plan panel", async ({ page }) => {
    await createCourseWithContent(page, "Scene ExamPrep");
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
  });

  test("assignment workflow opens the practice workspace", async ({ page }) => {
    await createCourseWithContent(page, "Scene Assignment");
    await switchScene(page, "assignment");
    await expect(page.getByTestId("practice-section")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Quiz", exact: true })).toBeVisible();
  });

  test("review workflow keeps review tools available", async ({ page }) => {
    await createCourseWithContent(page, "Scene Review");
    await switchScene(page, "review_drill");
    await expect(page.getByTestId("right-tab-review")).toBeVisible({ timeout: 15_000 });
  });

  test("note organize workflow returns to notes", async ({ page }) => {
    await createCourseWithContent(page, "Scene Notes");
    await switchScene(page, "note_organize");
    await expect(page.getByTestId("notes-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Binary Search Basics" })).toBeVisible({ timeout: 15_000 });
  });
});
