import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent, switchScene, expectGeneratedStudyPlan } from "./helpers/test-utils";

test.describe.serial("Study Plan Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("panel visible after switching to exam_prep scene", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
  });

  test("panel has data-testid='study-plan-panel'", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    const panel = page.getByTestId("study-plan-panel");
    await expect(panel).toBeVisible({ timeout: 15_000 });
    // Verify the panel contains "Exam prep plan" text
    await expect(panel).toContainText("Exam prep plan", { timeout: 15_000 });
  });

  test("days input has default value 7", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    const daysInput = page.getByTestId("study-plan-days-input");
    await expect(daysInput).toBeVisible({ timeout: 15_000 });
    await expect(daysInput).toHaveValue("7");
  });

  test("days input accepts new value", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    const daysInput = page.getByTestId("study-plan-days-input");
    await daysInput.fill("14");
    await expect(daysInput).toHaveValue("14");
  });

  test("generate button triggers plan creation", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("study-plan-generate").click();
    // Wait for generation to complete
    await expect(page.getByTestId("study-plan-content")).toBeVisible({ timeout: 30_000 });
  });

  test("generated plan content appears", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("study-plan-generate").click();
    const content = page.getByTestId("study-plan-content");
    await expect(content).toBeVisible({ timeout: 30_000 });
    // Content area should not be empty
    await expect(content).not.toBeEmpty();
  });

  test("plan shows generated content", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("study-plan-generate").click();
    await expectGeneratedStudyPlan(page);
  });

  test("Save New button saves plan and shows toast", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("study-plan-generate").click();
    await expect(page.getByTestId("study-plan-content")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved study plan")).toBeVisible({ timeout: 15_000 });
  });

  test("generate button disabled during loading", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("study-plan-generate").click();
    // The button should be disabled while the plan is being generated
    await expect(page.getByTestId("study-plan-generate")).toBeDisabled();
    // Wait for generation to complete
    await expect(page.getByTestId("study-plan-content")).toBeVisible({ timeout: 30_000 });
  });

  test("Replace Latest appears after saving and regenerating", async ({ page }) => {
    await createCourseWithContent(page);
    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    // Generate and save first plan
    await page.getByTestId("study-plan-generate").click();
    await expect(page.getByTestId("study-plan-content")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved study plan")).toBeVisible({ timeout: 15_000 });
    // Regenerate a second plan
    await page.getByTestId("study-plan-days-input").fill("3");
    await page.getByTestId("study-plan-generate").click();
    await expectGeneratedStudyPlan(page);
    // "Replace Latest" button should now be visible
    await expect(page.getByRole("button", { name: "Replace Latest" })).toBeVisible({ timeout: 15_000 });
  });
});
