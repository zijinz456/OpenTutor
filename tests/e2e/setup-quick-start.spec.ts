import { expect, test } from "@playwright/test";
import { SAMPLE_COURSE_MD } from "./helpers/test-utils";

async function openContentStep(page: import("@playwright/test").Page) {
  await page.goto("/setup");

  const courseNameInput = page.getByTestId("setup-course-name");
  const alreadyOnContentStep = await courseNameInput.isVisible({ timeout: 5_000 }).catch(() => false);
  if (alreadyOnContentStep) {
    return;
  }

  const skipForNow = page.getByRole("button", { name: /skip for now/i });
  await expect(skipForNow).toBeVisible({ timeout: 30_000 });
  await skipForNow.click();

  await expect(courseNameInput).toBeVisible({ timeout: 30_000 });
}

test.describe.serial("Setup quick start", () => {
  test("file upload can quick-start into a working workspace", async ({ page }) => {
    test.setTimeout(120_000);

    await openContentStep(page);
    await page.getByTestId("setup-course-name").fill("Quick Start E2E");
    await page.getByTestId("setup-file-input").setInputFiles(SAMPLE_COURSE_MD);

    await expect(page.getByText(/sample-course/i)).toBeVisible({ timeout: 15_000 });

    const quickStartButton = page.getByTestId("setup-quick-start");
    await expect(quickStartButton).toBeEnabled({ timeout: 15_000 });
    await quickStartButton.click();

    const enterWorkspaceButton = page.getByTestId("setup-enter-workspace");
    await expect(enterWorkspaceButton).toBeVisible({ timeout: 90_000 });
    await expect(enterWorkspaceButton).toBeEnabled({ timeout: 90_000 });
    await enterWorkspaceButton.click();

    await expect(page).toHaveURL(/\/course\//, { timeout: 30_000 });
    await expect(page.getByRole("list", { name: "Workspace blocks" })).toBeVisible({ timeout: 30_000 });

    const onboarded = await page.evaluate(() => localStorage.getItem("opentutor_onboarded"));
    expect(onboarded).toBe("true");
  });

  test("url import can quick-start into a working workspace", async ({ page }) => {
    test.setTimeout(120_000);

    await openContentStep(page);
    await page.getByTestId("setup-course-name").fill("Quick Start URL E2E");
    await page.getByTestId("setup-tab-url").click();
    await expect(page.getByTestId("setup-url-input")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("setup-url-input").fill("https://opentutor-e2e.local/binary-search");

    const quickStartButton = page.getByTestId("setup-quick-start");
    await expect(quickStartButton).toBeEnabled({ timeout: 15_000 });
    await quickStartButton.click();

    const enterWorkspaceButton = page.getByTestId("setup-enter-workspace");
    await expect(enterWorkspaceButton).toBeVisible({ timeout: 90_000 });
    await expect(enterWorkspaceButton).toBeEnabled({ timeout: 90_000 });
    await enterWorkspaceButton.click();

    await expect(page).toHaveURL(/\/course\//, { timeout: 30_000 });
    await expect(page.getByRole("list", { name: "Workspace blocks" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Binary Search Notes/i)).toBeVisible({ timeout: 30_000 });
  });
});
