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
  const match = url.match(/\/course\/([^/?#]+)/);
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
  await expect(page.getByTestId("chat-input")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("chat-session-select")).toBeEnabled({ timeout: 15_000 });
  await page.getByTestId("chat-input").fill(message);
  await expect(page.getByTestId("chat-send")).toBeEnabled({ timeout: 15_000 });
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("chat-message-user").last()).toContainText(message, { timeout: 15_000 });
  await expectAssistantMessage(page);
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

export async function expectAssistantMessage(page: Page) {
  const assistant = page.getByTestId("chat-message-assistant").last();
  await expect(assistant).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => ((await assistant.textContent()) || "").trim().length, {
    timeout: 30_000,
  }).toBeGreaterThan(0);
  return assistant;
}

export async function expectGeneratedNotes(page: Page) {
  const preview = page.getByTestId("notes-preview");
  await expect(preview).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => ((await preview.textContent()) || "").trim().length, {
    timeout: 30_000,
  }).toBeGreaterThan(20);
  return preview;
}

export async function expectGeneratedStudyPlan(page: Page) {
  const content = page.getByTestId("study-plan-content");
  await expect(content).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => ((await content.textContent()) || "").trim().length, {
    timeout: 30_000,
  }).toBeGreaterThan(20);
  return content;
}

/**
 * Ensure the right panel (Quiz/Cards/Stats/Graph/Review/Plan tabs) is visible.
 * The scene system may hide it on initial load. Clicking the Practice activity
 * bar button restores it.
 */
export async function ensureRightPanelVisible(page: Page): Promise<void> {
  // Use a specific locator for the Quiz tab button (small button in tab bar, not the generate button)
  const quizTab = page.getByRole("button", { name: "Quiz", exact: true }).first();
  const visible = await quizTab.isVisible({ timeout: 3_000 }).catch(() => false);
  if (!visible) {
    await page.locator('button[title="Practice"]').click();
    await expect(quizTab).toBeVisible({ timeout: 10_000 });
  }
}

export function hasRealLlmEnv(): boolean {
  return Boolean(
    process.env.OPENAI_API_KEY ||
      process.env.ANTHROPIC_API_KEY ||
      process.env.DEEPSEEK_API_KEY ||
      process.env.OPENROUTER_API_KEY ||
      process.env.GEMINI_API_KEY ||
      process.env.GROQ_API_KEY
  );
}
