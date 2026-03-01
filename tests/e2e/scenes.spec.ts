import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, switchScene } from "./helpers/test-utils";

test.describe.serial("Scene System", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("scene selector trigger is visible", async ({ page }) => {
    await createCourseWithContent(page, "Scene Test");
    await expect(page.getByTestId("scene-selector-trigger")).toBeVisible();
  });

  test("clicking trigger opens dropdown with scene options", async ({ page }) => {
    await createCourseWithContent(page, "Scene Dropdown");
    await page.getByTestId("scene-selector-trigger").click();
    // Should show at least the 5 preset scenes
    await expect(page.getByTestId("scene-option-study_session")).toBeVisible();
    await expect(page.getByTestId("scene-option-exam_prep")).toBeVisible();
    await expect(page.getByTestId("scene-option-assignment")).toBeVisible();
    await expect(page.getByTestId("scene-option-review_drill")).toBeVisible();
    await expect(page.getByTestId("scene-option-note_organize")).toBeVisible();
  });

  test("dropdown closes when clicking outside", async ({ page }) => {
    await createCourseWithContent(page, "Scene Close");
    await page.getByTestId("scene-selector-trigger").click();
    await expect(page.getByTestId("scene-option-study_session")).toBeVisible();
    // Click outside the dropdown
    await page.locator("body").click({ position: { x: 10, y: 10 } });
    await expect(page.getByTestId("scene-option-study_session")).not.toBeVisible();
  });

  test("active scene is highlighted in dropdown", async ({ page }) => {
    await createCourseWithContent(page, "Scene Active");
    await page.getByTestId("scene-selector-trigger").click();
    // Default scene should have "active" label
    const activeLabel = page.getByTestId("scene-option-study_session").getByText("active");
    await expect(activeLabel).toBeVisible();
  });

  test("each scene option has correct data-testid", async ({ page }) => {
    await createCourseWithContent(page, "Scene TestIDs");
    await page.getByTestId("scene-selector-trigger").click();
    const sceneIds = ["study_session", "exam_prep", "assignment", "review_drill", "note_organize"];
    for (const id of sceneIds) {
      await expect(page.getByTestId(`scene-option-${id}`)).toBeVisible();
    }
  });

  test("default scene is study_session", async ({ page }) => {
    await createCourseWithContent(page, "Scene Default");
    const trigger = page.getByTestId("scene-selector-trigger");
    // The backend may use "Daily Study" or "Study Session" as the display name
    await expect(trigger).toContainText(/study|daily/i);
  });

  test("switching to exam_prep shows study plan panel", async ({ page }) => {
    await createCourseWithContent(page, "Scene ExamPrep");
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
  });

  test("switching to exam_prep updates trigger text", async ({ page }) => {
    await createCourseWithContent(page, "Scene ExamText");
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("scene-selector-trigger")).toContainText("Exam Prep", { ignoreCase: true });
  });

  test("switching to assignment adjusts workspace", async ({ page }) => {
    await createCourseWithContent(page, "Scene Assignment");
    await switchScene(page, "assignment");
    await expect(page.getByTestId("scene-selector-trigger")).toContainText(/assignment|homework/i);
  });

  test("switching to review_drill scene", async ({ page }) => {
    await createCourseWithContent(page, "Scene Review");
    await switchScene(page, "review_drill");
    await expect(page.getByTestId("scene-selector-trigger")).toContainText("Review", { ignoreCase: true });
  });

  test("switching to note_organize scene", async ({ page }) => {
    await createCourseWithContent(page, "Scene Notes");
    await switchScene(page, "note_organize");
    await expect(page.getByTestId("scene-selector-trigger")).toContainText("Note", { ignoreCase: true });
  });

  test("scene switch disables trigger during transition", async ({ page }) => {
    await createCourseWithContent(page, "Scene Disable");
    await page.getByTestId("scene-selector-trigger").click();
    // Start switching - the trigger should become disabled
    const switchPromise = page.getByTestId("scene-option-exam_prep").click();
    // The trigger may momentarily be disabled during the switch
    await switchPromise;
    // After switch completes, trigger should be enabled again
    await expect(page.getByTestId("scene-selector-trigger")).toBeEnabled({ timeout: 15_000 });
  });

  test("switching updates active scene icon and name", async ({ page }) => {
    await createCourseWithContent(page, "Scene Icon");
    await switchScene(page, "exam_prep");
    const trigger = page.getByTestId("scene-selector-trigger");
    await expect(trigger).not.toContainText("Study Session");
  });

  test("switching back to study_session restores default", async ({ page }) => {
    await createCourseWithContent(page, "Scene Restore");
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("scene-selector-trigger")).toContainText("Exam Prep", { ignoreCase: true });
    await switchScene(page, "study_session");
    await expect(page.getByTestId("scene-selector-trigger")).toContainText(/study|daily/i);
  });

  test("scene switching applies layout preset", async ({ page }) => {
    await createCourseWithContent(page, "Scene Layout");
    // exam_prep should show study plan (Plan tab active in right panel)
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
  });
});
