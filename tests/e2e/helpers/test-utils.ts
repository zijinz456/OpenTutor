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
  // Retry on 503 (server overload) — common under parallel test workers
  for (let attempt = 0; attempt < 5; attempt++) {
    const response = await fetch(`${apiBaseUrl}/courses/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description, metadata }),
    });
    if (response.ok) {
      const payload = (await response.json()) as { id: string };
      return payload.id;
    }
    if (response.status === 503 && attempt < 4) {
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
      continue;
    }
    throw new Error(`API course creation failed (${response.status})`);
  }
  throw new Error("API course creation failed after retries");
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

async function waitForCourseContent(courseId: string, timeoutMs = 60_000): Promise<void> {
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

export async function seedFlashcardsViaApi(courseId: string, count = 3): Promise<void> {
  const generateResponse = await fetch(`${apiBaseUrl}/flashcards/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course_id: courseId, count }),
  });
  if (!generateResponse.ok) {
    throw new Error(`Flashcard generation failed (${generateResponse.status})`);
  }
  const generated = (await generateResponse.json()) as { cards?: unknown[] };
  if (!Array.isArray(generated.cards) || generated.cards.length === 0) {
    throw new Error("Flashcard generation returned no cards");
  }

  const saveResponse = await fetch(`${apiBaseUrl}/flashcards/generated/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      course_id: courseId,
      cards: generated.cards,
      title: "Playwright Flashcards",
    }),
  });
  if (!saveResponse.ok) {
    throw new Error(`Flashcard save failed (${saveResponse.status})`);
  }
}

/**
 * Create a course through the new-project wizard and arrive at the workspace.
 * Returns the courseId extracted from the URL.
 */
export async function createCourse(page: Page, name: string): Promise<string> {
  try {
    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();
    // Wait for the step transition — the name input appears on step 2
    await expect(page.getByTestId("project-name-input")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("project-name-input").fill(name);
    await page.getByTestId("start-parsing").click();
    try {
      await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    } catch {
      // Parsing step may fail if no files were uploaded — fall through to API
      throw new Error("Wizard parsing step did not complete");
    }
    await page.getByTestId("continue-to-features").click();
    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//);
    const url = page.url();
    const match = url.match(/\/course\/([^/?#]+)/);
    return match ? match[1] : "";
  } catch {
    // Fallback: create course via API when the wizard flow fails
    const courseId = await createCourseViaApi(name);
    await page.goto(`/course/${courseId}`);
    await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 30_000 });
    return courseId;
  }
}

/**
 * Create a course and upload the sample fixture file.
 */
export async function createCourseWithContent(page: Page, name = "Test Course"): Promise<string> {
  const courseId = await createCourseViaApi(name);
  await seedCourseFixture(courseId, SAMPLE_COURSE_MD);
  await page.goto(`/course/${courseId}`);
  await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 30_000 });
  await expect
    .poll(
      async () =>
        (
          await Promise.all([
            page.getByRole("button", { name: "Upload" }).isVisible().catch(() => false),
            page.getByTestId("workspace-upload-trigger").isVisible().catch(() => false),
            page.getByTestId("chat-input").isVisible().catch(() => false),
            page.getByRole("textbox", { name: /Ask anything/i }).isVisible().catch(() => false),
          ])
        ).some(Boolean),
      { timeout: 30_000 },
    )
    .toBe(true);
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
  await page.getByTestId("chat-input").fill(message);
  await expect(page.getByTestId("chat-send")).toBeEnabled({ timeout: 30_000 });
  await page.getByTestId("chat-send").click();
  await expect(page.getByTestId("chat-message-user").last()).toContainText(message, { timeout: 15_000 });
  await expectAssistantMessage(page);
}

/**
 * Keyboard shortcut map: section label → Cmd/Ctrl + digit.
 * Matches useKeyboardShortcuts in the app: 1=notes, 2=practice, 3=analytics, 4=plan.
 */
const SECTION_SHORTCUT_KEY: Record<string, string> = {
  Notes: "1",
  Practice: "2",
  Analytics: "3",
  Plan: "4",
};

/**
 * Dispatch a Cmd/Ctrl+key shortcut directly on the window object.
 * page.keyboard.press("Meta+N") is intercepted by Chromium as a
 * browser tab-switching shortcut and never reaches page JS listeners.
 */
export async function dispatchShortcut(page: Page, key: string): Promise<void> {
  const useMeta = process.platform === "darwin";
  await page.evaluate(
    ({ key, useMeta }) => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key,
          code: `Digit${key}`,
          metaKey: useMeta,
          ctrlKey: !useMeta,
          bubbles: true,
          cancelable: true,
        }),
      );
    },
    { key, useMeta },
  );
}

async function activateSection(page: Page, label: "Practice" | "Plan" | "Analytics" | "Notes", targetTestId: string): Promise<void> {
  await expect(page.getByTestId("section-container")).toBeVisible({ timeout: 30_000 });

  const shortcutKey = SECTION_SHORTCUT_KEY[label];

  // Unfocus any active input so the keyboard shortcut fires on window
  await page.keyboard.press("Escape");

  // Retry shortcut dispatch — the React useKeyboardShortcuts hook may not
  // have attached its listener yet when the page just finished loading.
  for (let attempt = 0; attempt < 5; attempt++) {
    await dispatchShortcut(page, shortcutKey);
    const visible = await page.getByTestId(targetTestId).isVisible().catch(() => false);
    if (visible) return;
    await page.waitForTimeout(500);
  }

  await expect(page.getByTestId(targetTestId)).toBeVisible({ timeout: 15_000 });
}

/**
 * Route to the UI area that previously matched a scene-oriented workflow.
 * Scene selection is now internal — switch via keyboard shortcuts (Cmd+1~4).
 */
export async function switchScene(page: Page, sceneId: string): Promise<void> {
  if (sceneId === "exam_prep") {
    await activateSection(page, "Plan", "plan-section");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    return;
  }

  if (sceneId === "assignment" || sceneId === "review_drill") {
    await activateSection(page, "Practice", "practice-section");
    return;
  }

  await activateSection(page, "Notes", "notes-panel");
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
 * Ensure the practice section (Quiz/Cards/Review tabs) is visible.
 * Uses Cmd+2 keyboard shortcut to switch to the practice section.
 */
export async function ensureRightPanelVisible(page: Page): Promise<void> {
  const practiceSection = page.getByTestId("practice-section");
  const alreadyVisible = await practiceSection.isVisible({ timeout: 3_000 }).catch(() => false);
  if (alreadyVisible) {
    return;
  }

  await activateSection(page, "Practice", "practice-section");
}

export async function ensureAnalyticsSectionVisible(page: Page): Promise<void> {
  const analyticsSection = page.getByTestId("analytics-section");
  const visible = await analyticsSection.isVisible({ timeout: 2_000 }).catch(() => false);
  if (visible) {
    return;
  }

  await activateSection(page, "Analytics", "analytics-section");
  await expect(analyticsSection).toBeVisible({ timeout: 15_000 });
}

export async function openRightTab(page: Page, tab: string): Promise<void> {
  // Stats and Graph live in the analytics section; everything else in practice
  if (tab === "progress" || tab === "graph") {
    await ensureAnalyticsSectionVisible(page);
  } else {
    await ensureRightPanelVisible(page);
  }

  const tabId =
    tab === "flashcards" ? "right-tab-cards" :
    tab === "progress" ? "right-tab-progress" :
    tab === "graph" ? "right-tab-graph" :
    `right-tab-${tab}`;
  const tabButton = page.getByTestId(tabId).last();
  const tabVisible = await tabButton.isVisible({ timeout: 5_000 }).catch(() => false);
  if (tabVisible) {
    await tabButton.click({ force: true });
    return;
  }

  // Fallback: try matching by accessible name
  const label =
    tab === "flashcards" ? /Cards|Flashcards|闪卡/i :
    tab === "quiz" ? /Quiz|测验/i :
    tab === "review" ? /Review|复盘/i :
    tab === "progress" ? /Stats|Progress/i :
    tab === "graph" ? /Graph/i :
    new RegExp(tab, "i");

  const namedButton = page.getByRole("button", { name: label }).first();
  await expect(namedButton).toBeVisible({ timeout: 15_000 });
  await namedButton.click({ force: true });
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
