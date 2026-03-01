import { expect, test } from "@playwright/test";
import {
  createCourseWithContent,
  expectAssistantMessage,
  expectGeneratedNotes,
  expectGeneratedStudyPlan,
  hasRealLlmEnv,
  sendChatMessage,
  skipOnboarding,
  switchScene,
} from "./helpers/test-utils";

const FALLBACK_RE = /No LLM API key configured|local fallback response/i;

function getRealProvider() {
  const candidates = [
    { provider: "openai", key: process.env.OPENAI_API_KEY, model: process.env.OPENAI_MODEL || "gpt-4o-mini" },
    { provider: "anthropic", key: process.env.ANTHROPIC_API_KEY, model: process.env.ANTHROPIC_MODEL || "claude-sonnet-4-20250514" },
    { provider: "deepseek", key: process.env.DEEPSEEK_API_KEY, model: process.env.DEEPSEEK_MODEL || "deepseek-chat" },
    { provider: "openrouter", key: process.env.OPENROUTER_API_KEY, model: process.env.OPENROUTER_MODEL || "openai/gpt-4o-mini" },
    { provider: "gemini", key: process.env.GEMINI_API_KEY, model: process.env.GEMINI_MODEL || "gemini-2.0-flash" },
    { provider: "groq", key: process.env.GROQ_API_KEY, model: process.env.GROQ_MODEL || "llama-3.3-70b-versatile" },
  ];
  const selected = candidates.find((item) => item.key);
  if (!selected) {
    throw new Error("No real LLM API key found in environment");
  }
  return selected as { provider: string; key: string; model: string };
}

test.describe.serial("Real LLM browser flows @llm", () => {
  test.skip(!hasRealLlmEnv(), "Requires a real LLM API key");

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("settings can store a provider key and transition runtime status", async ({ page }) => {
    const llm = getRealProvider();

    await page.goto("/settings");
    await expect(page.getByTestId("settings-llm-status")).toContainText(/mock_fallback|configuration_required/i, {
      timeout: 15_000,
    });

    await page.getByTestId("settings-llm-provider").selectOption(llm.provider);
    await page.getByTestId("settings-llm-model").fill(llm.model);
    const requiredToggle = page.getByTestId("settings-llm-required");
    await requiredToggle.click();
    await page.getByTestId(`provider-key-${llm.provider}`).fill(llm.key);
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
    await createCourseWithContent(page, "LLM Browser Notes");
    await page.getByTestId("notes-generate").click();
    const preview = await expectGeneratedNotes(page);
    await expect(preview).not.toContainText(FALLBACK_RE);
  });

  test("study plan generation uses a real provider response", async ({ page }) => {
    await createCourseWithContent(page, "LLM Browser Plan");
    await switchScene(page, "exam_prep");
    await page.getByTestId("study-plan-generate").click();
    const content = await expectGeneratedStudyPlan(page);
    await expect(content).not.toContainText(FALLBACK_RE);
  });

  test("exercise generation can be saved into the quiz bank", async ({ page }) => {
    await createCourseWithContent(page, "LLM Browser Exercise");
    await sendChatMessage(
      page,
      "Return only a valid JSON array of 3 multiple-choice binary search practice questions using the shared schema with question_type, question, options, correct_answer, explanation, difficulty_layer, and problem_metadata.",
    );

    const assistant = await expectAssistantMessage(page);
    await expect(assistant).not.toContainText(FALLBACK_RE);
    await expect(page.getByText(/generated questions detected/i)).toBeVisible({ timeout: 30_000 });

    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText(/Saved 3 questions to the course quiz bank/i)).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "Practice" }).click();
    await expect(page.getByTestId("quiz-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("quiz-question")).toBeVisible({ timeout: 15_000 });
  });
});
