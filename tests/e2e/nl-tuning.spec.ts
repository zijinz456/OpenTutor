import { expect, test } from "@playwright/test";
import { skipOnboarding, createCourseWithContent } from "./helpers/test-utils";

test.describe.serial("NL tuning entry point", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("workspace does not expose the retired fine-tune FAB", async ({ page }) => {
    await createCourseWithContent(page, "FAB Removed");
    await expect(page.locator('button[title="Fine-tune Agent"]')).toHaveCount(0);
  });

  test("retired tuning dialog content is absent from the workspace", async ({ page }) => {
    await createCourseWithContent(page, "FAB Dialog Removed");
    await expect(page.getByText("Fine-tune Agent")).toHaveCount(0);
    await expect(page.getByPlaceholder('e.g. "simplify notes"')).toHaveCount(0);
  });
});
