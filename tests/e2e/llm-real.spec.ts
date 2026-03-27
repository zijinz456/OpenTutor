import { expect, test } from "@playwright/test";
import {
  createCourseWithContent,
  dispatchShortcut,
  expectAssistantMessage,
  expectGeneratedNotes,
  getRealLlmProvider,
  hasRealLlmEnv,
  sendChatMessage,
  skipOnboarding,
  switchScene,
} from "./helpers/test-utils";

const FALLBACK_RE = /No LLM API key configured|local fallback response/i;

function supportsLongFormValidation(llm: ReturnType<typeof getRealLlmProvider>): boolean {
  if (!llm) return false;
  return llm.requiresKey || llm.provider === "lmstudio";
}

test.describe.serial("Real LLM browser flows @llm", () => {
  test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("settings can store a provider key and transition runtime status", async ({ page }) => {
    const llm = getRealLlmProvider();
    if (!llm) {
      throw new Error("No real LLM provider found in environment");
    }

    await page.goto("/settings");
    await expect(page.getByTestId("settings-llm-status")).toContainText(/mock_fallback|configuration_required|ready|degraded/i, {
      timeout: 15_000,
    });

    await page.getByTestId("settings-llm-provider").selectOption(llm.provider);
    await page.getByTestId("settings-llm-model").fill(llm.model);
    const requiredToggle = page.getByTestId("settings-llm-required");
    if ((await requiredToggle.textContent())?.includes("Off")) {
      await requiredToggle.click();
    }
    if (llm.requiresKey && llm.key) {
      await page.getByTestId(`provider-key-${llm.provider}`).fill(llm.key);
    }
    await page.getByTestId("settings-save-llm").click();

    await expect(page.getByText(/Saved local LLM configuration/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("settings-llm-status")).toContainText(/ready|degraded/i, {
      timeout: 15_000,
    });
  });

  test("chat uses a real provider response", async ({ page }) => {
    await createCourseWithContent(page, "LLM Browser Chat");
    await sendChatMessage(page, "Explain binary search in exactly 2 short bullet points.");
    const assistant = await expectAssistantMessage(page);
    await expect(assistant).not.toContainText(FALLBACK_RE);
  });

  test("notes generation uses a real provider response", async ({ page }) => {
    const llm = getRealLlmProvider();
    if (!llm) {
      throw new Error("No real LLM provider found in environment");
    }
    test.skip(!supportsLongFormValidation(llm), "Long-form notes generation validation requires a higher-capacity provider");

    await createCourseWithContent(page, "LLM Browser Notes");
    await page.getByTestId("notes-generate").click();
    const preview = await expectGeneratedNotes(page);
    await expect(preview).not.toContainText(FALLBACK_RE);
  });

  test("study plan generation uses a real provider response", async ({ page }) => {
    await createCourseWithContent(page, "LLM Browser Plan");
    await sendChatMessage(page, "I have an exam soon. Give me 2 short priorities for studying binary search.");
    const assistant = await expectAssistantMessage(page);
    await expect(assistant).not.toContainText(FALLBACK_RE);

    await switchScene(page, "exam_prep");
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: /Add Goal/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("tab", { name: /Calendar/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("tab", { name: /Tasks/i })).toBeVisible({ timeout: 15_000 });
  });

  test("exercise generation can be saved into the quiz bank", async ({ page }) => {
    test.setTimeout(180_000);
    const llm = getRealLlmProvider();
    if (!llm) {
      throw new Error("No real LLM provider found in environment");
    }
    test.skip(!supportsLongFormValidation(llm), "Structured quiz-save validation requires a higher-capacity provider");

    await createCourseWithContent(page, "LLM Browser Exercise");
    await sendChatMessage(
      page,
      "Return only a valid JSON array of 3 multiple-choice binary search practice questions using the shared schema with question_type, question, options, correct_answer, explanation, difficulty_layer, and problem_metadata.",
    );

    const assistant = await expectAssistantMessage(page);
    await expect(page.getByRole("button", { name: /Stop generating/i })).not.toBeVisible({ timeout: 120_000 });
    await expect(assistant).not.toContainText(FALLBACK_RE);

    await expect(page.getByText(/generated questions detected/i)).toBeVisible({ timeout: 30_000 });

    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText(/Saved \d+ questions to the course quiz bank/i)).toBeVisible({ timeout: 15_000 });

    await page.keyboard.press("Escape");
    await dispatchShortcut(page, "2");
    await expect(page.getByTestId("practice-section")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("quiz-question")).toBeVisible({ timeout: 15_000 });
  });
});
