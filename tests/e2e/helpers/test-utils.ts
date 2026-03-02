import fs from "node:fs/promises";
import path from "node:path";
import { expect, type Page } from "@playwright/test";

export const SAMPLE_COURSE_MD = path.join(process.cwd(), "tests/e2e/fixtures/sample-course.md");
export const SAMPLE_COURSE_2_MD = path.join(process.cwd(), "tests/e2e/fixtures/sample-course-2.md");
const useExistingServer = process.env.PLAYWRIGHT_USE_EXISTING_SERVER === "1";
const backendPort = Number(process.env.PLAYWRIGHT_BACKEND_PORT || (useExistingServer ? "8000" : "8005"));
const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || `http://127.0.0.1:${backendPort}/api`;
const LOCAL_REAL_PROVIDERS = ["ollama", "lmstudio", "textgenwebui"] as const;
type LocalRealProvider = (typeof LOCAL_REAL_PROVIDERS)[number];

/**
 * Set localStorage so onboarding redirect is skipped.
 * Must be called BEFORE navigating to any page.
 */
export async function skipOnboarding(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("opentutor_onboarded", "true");
  });
}

export async function createCourseViaApi(
  name: string,
  description?: string,
  metadata?: Record<string, unknown>,
): Promise<string> {
  const response = await fetch(`${apiBaseUrl}/courses/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description, metadata }),
  });
  if (!response.ok) {
    throw new Error(`API course creation failed (${response.status})`);
  }
  const payload = (await response.json()) as { id: string };
  return payload.id;
}

export async function getCourseViaApi(courseId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${apiBaseUrl}/courses/${courseId}`);
  if (!response.ok) {
    throw new Error(`API course fetch failed (${response.status})`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export async function seedOnboardingPreferencesViaApi(
  preferences: Record<string, string> = {
    language: "zh",
    learning_mode: "balanced",
    detail_level: "balanced",
    layout_preset: "balanced",
  },
): Promise<void> {
  for (const [dimension, value] of Object.entries(preferences)) {
    const response = await fetch(`${apiBaseUrl}/preferences/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dimension,
        value,
        scope: "global",
        source: "playwright",
      }),
    });
    if (!response.ok) {
      throw new Error(`API preference seed failed for ${dimension} (${response.status})`);
    }
  }
}

function treeHasMaterial(nodes: unknown): boolean {
  if (!Array.isArray(nodes)) {
    return false;
  }

  return nodes.some((node) => {
    if (!node || typeof node !== "object") {
      return false;
    }
    const candidate = node as { content?: string | null; children?: unknown };
    if ((candidate.content || "").trim().length > 0) {
      return true;
    }
    return treeHasMaterial(candidate.children);
  });
}

async function waitForCourseContent(courseId: string, timeoutMs = 30_000): Promise<void> {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const response = await fetch(`${apiBaseUrl}/courses/${courseId}/content-tree`);
    if (response.ok) {
      const payload = (await response.json()) as unknown;
      if (treeHasMaterial(payload)) {
        return;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error(`Course content tree did not become ready within ${timeoutMs}ms`);
}

export async function seedCourseFixture(courseId: string, fixturePath: string): Promise<void> {
  const fileBuffer = await fs.readFile(fixturePath);
  const form = new FormData();
  form.append("course_id", courseId);
  form.append("file", new Blob([fileBuffer], { type: "text/markdown" }), path.basename(fixturePath));

  const response = await fetch(`${apiBaseUrl}/content/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(`Fixture upload failed (${response.status})`);
  }
  await waitForCourseContent(courseId);
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
  try {
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
  } catch (error) {
    const courseId = await createCourseViaApi(name);
    await page.goto(`/course/${courseId}`);
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`));
    return courseId;
  }
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
  await seedCourseFixture(courseId, SAMPLE_COURSE_MD);
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Upload" })).toBeVisible({ timeout: 30_000 });
  return courseId;
}

/**
 * Upload a file into an existing workspace via the upload dialog.
 */
export async function uploadFixture(page: Page, fixturePath: string): Promise<void> {
  await page.getByTestId("workspace-upload-trigger").click();
  await page.getByTestId("workspace-upload-file-input").setInputFiles(fixturePath);
  const fileName = path.basename(fixturePath);
  await expect(
    page.getByText(`Uploaded ${fileName}`).or(page.getByText("Binary Search Basics").first()),
  ).toBeVisible({ timeout: 30_000 });
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
  const quizTab = page.getByTestId("right-tab-quiz").last();
  const visible = await quizTab.isVisible({ timeout: 3_000 }).catch(() => false);
  if (!visible) {
    await page.locator('button[title="Practice"]').click();
    await expect(quizTab).toBeVisible({ timeout: 10_000 });
  }
}

export async function openRightTab(page: Page, tab: string): Promise<void> {
  const tabButton = page.getByTestId(`right-tab-${tab}`).last();
  await expect(tabButton).toBeVisible({ timeout: 15_000 });
  await tabButton.click({ force: true });
}

export function hasRealLlmEnv(): boolean {
  return getRealLlmProvider() !== null;
}

export function isLocalRealLlmProvider(): boolean {
  const provider = getRealLlmProvider();
  return provider ? !provider.requiresKey : false;
}

export function getRealLlmTimeoutMs(defaultTimeoutMs = 30_000): number {
  return isLocalRealLlmProvider() ? Math.max(defaultTimeoutMs, 120_000) : defaultTimeoutMs;
}

export function getRealLlmProvider():
  | { provider: string; key?: string; model: string; requiresKey: boolean }
  | null {
  const cloudCandidates = [
    { provider: "openai", key: process.env.OPENAI_API_KEY, model: process.env.OPENAI_MODEL || "gpt-4o-mini" },
    { provider: "anthropic", key: process.env.ANTHROPIC_API_KEY, model: process.env.ANTHROPIC_MODEL || "claude-sonnet-4-20250514" },
    { provider: "deepseek", key: process.env.DEEPSEEK_API_KEY, model: process.env.DEEPSEEK_MODEL || "deepseek-chat" },
    { provider: "openrouter", key: process.env.OPENROUTER_API_KEY, model: process.env.OPENROUTER_MODEL || "openai/gpt-4o-mini" },
    { provider: "gemini", key: process.env.GEMINI_API_KEY, model: process.env.GEMINI_MODEL || "gemini-2.0-flash" },
    { provider: "groq", key: process.env.GROQ_API_KEY, model: process.env.GROQ_MODEL || "llama-3.3-70b-versatile" },
  ];
  const cloud = cloudCandidates.find((item) => item.key);
  if (cloud) {
    return { ...cloud, requiresKey: true };
  }

  const localProvider = (
    process.env.PLAYWRIGHT_REAL_LLM_PROVIDER ||
    process.env.REAL_LLM_PROVIDER ||
    process.env.LLM_PROVIDER ||
    ""
  ).toLowerCase() as LocalRealProvider | "";
  if (LOCAL_REAL_PROVIDERS.includes(localProvider as LocalRealProvider)) {
    const modelEnvKey = `${localProvider.toUpperCase()}_MODEL`;
    const fallbackModel =
      localProvider === "ollama" ? "llama3.2:1b" : "default";
    return {
      provider: localProvider,
      model: process.env[modelEnvKey] || process.env.LLM_MODEL || fallbackModel,
      requiresKey: false,
    };
  }

  return null;
}
