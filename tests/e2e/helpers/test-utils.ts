import path from "node:path";
import { expect, type Page } from "@playwright/test";

export const SAMPLE_COURSE_MD = path.join(process.cwd(), "tests/e2e/fixtures/sample-course.md");
export const SAMPLE_COURSE_2_MD = path.join(process.cwd(), "tests/e2e/fixtures/sample-course-2.md");

/**
 * Set localStorage so onboarding redirect is skipped.
 * Must be called BEFORE navigating to any page.
 */
export async function skipOnboarding(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("opentutor_onboarded", "true");
  });
}

/**
 * Create a course through the new-project wizard and arrive at the workspace.
 * Returns the courseId extracted from the URL.
 */
export async function createCourse(page: Page, name: string): Promise<string> {
  await page.goto("/new");
  await page.getByTestId("mode-option-upload").click();
  await page.getByTestId("mode-continue").click();
  await page.getByTestId("project-name-input").fill(name);
  await page.getByTestId("start-parsing").click();
  await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
  await page.getByTestId("continue-to-features").click();
  await page.getByTestId("enter-workspace").click();
  await expect(page).toHaveURL(/\/course\//);
  const url = page.url();
  const match = url.match(/\/course\/(\d+)/);
  return match ? match[1] : "";
}

/**
 * Create a course and upload the sample fixture file.
 */
export async function createCourseWithContent(page: Page, name = "Test Course"): Promise<string> {
  const courseId = await createCourse(page, name);
  await uploadFixture(page, SAMPLE_COURSE_MD);
  return courseId;
}

/**
 * Upload a file into an existing workspace via the upload dialog.
 */
export async function uploadFixture(page: Page, fixturePath: string): Promise<void> {
  await page.getByTestId("workspace-upload-trigger").click();
  await page.getByTestId("workspace-upload-file-input").setInputFiles(fixturePath);
  const fileName = path.basename(fixturePath);
  await expect(page.getByText(`Uploaded ${fileName}`)).toBeVisible({ timeout: 30_000 });
}

/**
 * Send a chat message and wait for the assistant response.
 */
export async function sendChatMessage(page: Page, message: string): Promise<void> {
  await page.getByTestId("chat-input").fill(message);
  await page.getByTestId("chat-send").click();
  // Wait for mock LLM response (or real response)
  await expect(
    page.locator('[class*="assistant"], [data-role="assistant"]').last()
  ).toBeVisible({ timeout: 30_000 });
}

/**
 * Switch scene via the scene selector dropdown.
 */
export async function switchScene(page: Page, sceneId: string): Promise<void> {
  await page.getByTestId("scene-selector-trigger").click();
  await page.getByTestId(`scene-option-${sceneId}`).click();
  // Wait for scene switch to complete (dropdown closes)
  await expect(page.getByTestId("scene-selector-trigger")).toBeEnabled({ timeout: 15_000 });
}
