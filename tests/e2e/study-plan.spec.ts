import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseWithContent,
  hasRealLlmEnv,
} from "./helpers/test-utils";

/**
 * Study Plan Panel tests.
 *
 * The study plan renders via the "plan" block. Since STEM Student
 * template doesn't include it, these tests add it via the block palette
 * or navigate to the dedicated /course/[id]/plan page.
 */

test.describe.serial("Study Plan Panel", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("plan section visible on dedicated plan page", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    // Navigate to the dedicated plan page
    await page.goto(`/course/${courseId}/plan`);
    await expect(page.getByTestId("plan-section").or(page.getByTestId("study-plan-panel"))).toBeVisible({ timeout: 15_000 });
  });

  test("generate button triggers plan creation", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    const courseId = await createCourseWithContent(page);
    await page.goto(`/course/${courseId}/plan`);
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("study-plan-generate").click();
    await expect(page.getByTestId("study-plan-content")).toBeVisible({ timeout: 30_000 });
  });
});
