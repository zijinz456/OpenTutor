import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseWithContent,
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

  test("dedicated plan page shows the current planning workspace", async ({ page }) => {
    const courseId = await createCourseWithContent(page);
    await page.goto(`/course/${courseId}/plan`);
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /Add Goal/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("tab", { name: /Calendar/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("tab", { name: /Tasks/i })).toBeVisible({ timeout: 15_000 });
  });
});
