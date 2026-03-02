import path from "node:path";

import { expect, test } from "@playwright/test";
import {
  createCourse,
  expectAssistantMessage,
  expectGeneratedNotes,
  expectGeneratedStudyPlan,
  hasRealLlmEnv,
  seedCourseFixture,
} from "./helpers/test-utils";

const fixturePath = path.join(process.cwd(), "tests/e2e/fixtures/sample-course.md");
const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || "http://127.0.0.1:8005/api";

async function uploadFixture(page: import("@playwright/test").Page, courseId: string) {
  await seedCourseFixture(courseId, fixturePath);
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`/course/${courseId}`), { timeout: 30_000 });
  await expect(page.getByTestId("workspace-upload-trigger")).toBeVisible({ timeout: 30_000 });
}

async function createCourseViaApi(
  request: import("@playwright/test").APIRequestContext,
  name: string,
  metadata?: Record<string, unknown>,
) {
  const response = await request.post(`${apiBaseUrl}/courses/`, {
    data: {
      name,
      metadata,
    },
  });
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  return payload.id as string;
}

function buildSeedQuestion(question: string, sourceSection: string) {
  return {
    question_type: "mc",
    question,
    options: {
      A: "The array may be in any order",
      B: "The data must already be sorted",
      C: "The target must be at index 0",
      D: "The array must contain unique values",
    },
    correct_answer: "B",
    explanation: "Binary search relies on ordering to discard half of the search space each step.",
    difficulty_layer: 1,
    problem_metadata: {
      core_concept: "binary search prerequisites",
      bloom_level: "understand",
      potential_traps: ["thinking uniqueness is required"],
      layer_justification: "Checks core precondition knowledge",
      skill_focus: "concept check",
      source_section: sourceSection,
    },
  };
}

async function seedQuizSet(
  request: import("@playwright/test").APIRequestContext,
  courseId: string,
  questions = [buildSeedQuestion("What must be true before binary search can be used correctly?", "Binary Search Basics")],
) {
  const rawContent = JSON.stringify(questions);

  const response = await request.post(`${apiBaseUrl}/quiz/save-generated`, {
    data: {
      course_id: courseId,
      raw_content: rawContent,
      title: "E2E Quiz Seed",
    },
  });
  expect(response.ok()).toBeTruthy();
}

async function diagnoseLatestWrongAnswer(page: import("@playwright/test").Page) {
  const deriveButton = page.locator("[data-testid^='derive-']").first();
  await expect(deriveButton).toBeVisible({ timeout: 30_000 });
  await deriveButton.click();
  const diagnosticCard = page.locator("[data-testid^='diagnostic-']").first();
  await expect(diagnosticCard).toBeVisible({ timeout: 30_000 });
  await diagnosticCard.locator("[data-testid*='-B']").click();
  await expect(page.locator("[data-testid^='diagnosis-']").first()).toContainText("trap vulnerability", {
    timeout: 30_000,
  });
}

test.describe("OpenTutor e2e flows", () => {
  test("create course, chat, open the plan workspace, and generate a study plan", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    const courseId = await createCourse(page, "E2E Study Flow");
    await uploadFixture(page, courseId);

    await page.getByTestId("chat-input").fill("Summarize binary search in one paragraph.");
    await page.getByTestId("chat-send").click();
    await expectAssistantMessage(page);

    await page.locator('button[title="Plan"]').first().click();
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("study-plan-generate").click();
    await expectGeneratedStudyPlan(page);

    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved study plan")).toBeVisible({ timeout: 15_000 });
  });

  test("generate and save AI notes from uploaded content", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    const courseId = await createCourse(page, "E2E Notes Flow");
    await uploadFixture(page, courseId);
    await page.getByTestId("notes-generate").click();
    await expectGeneratedNotes(page);

    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved AI notes")).toBeVisible({ timeout: 15_000 });
  });

  test("replace generated study plan and restore chat session across reload", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    const courseId = await createCourse(page, "E2E Restore Flow");
    await uploadFixture(page, courseId);

    const firstPrompt = "Summarize binary search in one paragraph.";
    await page.getByTestId("chat-input").fill(firstPrompt);
    await page.getByTestId("chat-send").click();
    await expectAssistantMessage(page);

    await expect(page.getByTestId("chat-session-select")).toHaveValue(/.+/, { timeout: 15_000 });

    await page.getByRole("button", { name: "New" }).click();
    await expect(page.getByText("Start a conversation about your course materials")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("chat-session-select").selectOption({ label: firstPrompt });
    await expect(page.getByTestId("chat-message-user").last()).toContainText(firstPrompt, { timeout: 15_000 });

    await page.locator('button[title="Plan"]').first().click();
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("study-plan-days-input").fill("5");
    await page.getByTestId("study-plan-generate").click();
    await expectGeneratedStudyPlan(page);
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved study plan")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("study-plan-days-input").fill("3");
    await page.getByTestId("study-plan-generate").click();
    await expectGeneratedStudyPlan(page);
    await page.getByRole("button", { name: "Replace Latest" }).click();
    await expect(page.getByText("Replaced plan with version 2")).toBeVisible({ timeout: 15_000 });

    await page.reload();
    await page.locator('button[title="Plan"]').first().click();
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("chat-session-select")).toHaveValue(/.+/, { timeout: 15_000 });
    await expect(page.getByTestId("chat-message-user").last()).toContainText(firstPrompt, { timeout: 15_000 });
  });

  test("scrape URL into content tree from upload dialog", async ({ page }) => {
    await createCourse(page, "E2E Scrape Flow");

    await page.getByTestId("workspace-upload-trigger").click();
    await page.getByTestId("workspace-upload-url-tab").click();
    await page.getByTestId("workspace-upload-url-input").fill("https://opentutor-e2e.local/binary-search");
    await page.getByTestId("workspace-upload-url-submit").click();

    await expect(page.getByText("Scraped URL:")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Binary Search Notes").first()).toBeVisible({ timeout: 30_000 });
  });

  test("rejected internal URL shows SSRF error", async ({ page }) => {
    await createCourse(page, "E2E Scrape Reject");

    await page.getByTestId("workspace-upload-trigger").click();
    await page.getByTestId("workspace-upload-url-tab").click();
    await page.getByTestId("workspace-upload-url-input").fill("http://127.0.0.1/private");
    await page.getByTestId("workspace-upload-url-submit").click();

    await expect(page.getByTestId("workspace-upload-url-error")).toContainText("Internal URLs are not allowed", {
      timeout: 15_000,
    });
  });

  test("wrong-answer diagnosis flows through review, progress, and analytics", async ({ page, request }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    const courseId = await createCourseViaApi(request, "E2E Diagnosis Flow", {
      workspace_features: {
        wrong_answer: true,
      },
    });
    await page.goto(`/course/${courseId}`);
    await uploadFixture(page, courseId);
    await seedQuizSet(request, courseId);
    await page.reload();

    await expect(page.getByTestId("quiz-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("quiz-question")).toContainText("binary search can be used correctly", { timeout: 15_000 });
    await page.getByTestId("quiz-option-A").click();
    await expect(page.getByText("Binary search relies on ordering")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("right-tab-review").last().click();
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("review-stats")).toContainText("Unmastered: 1", { timeout: 30_000 });

    await diagnoseLatestWrongAnswer(page);
    await expect(page.getByTestId("review-stats")).toContainText("trap vulnerability: 1", { timeout: 30_000 });

    await page.locator('button[title="Analytics"]').first().click();
    await page.getByTestId("right-tab-progress").click();
    await expect(page.getByTestId("progress-panel")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("progress-gap-breakdown")).toContainText("fundamental gap: 1", {
      timeout: 30_000,
    });

    await page.goto("/analytics");
    await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("analytics-breakdown-diagnoses")).toContainText(/trap vulnerability: [1-9]\d*/, {
      timeout: 15_000,
    });
    await expect(page.getByTestId(`analytics-course-${courseId}`)).toContainText("E2E Diagnosis Flow", { timeout: 15_000 });
  });

  test("multiple diagnoses accumulate into course analytics", async ({ page, request }) => {
    test.skip(!hasRealLlmEnv(), "Requires a real LLM provider");
    const courseId = await createCourseViaApi(request, "E2E Diagnosis Trend", {
      workspace_features: {
        wrong_answer: true,
      },
    });
    await page.goto(`/course/${courseId}`);
    await uploadFixture(page, courseId);
    await seedQuizSet(request, courseId, [
      buildSeedQuestion("What must be true before binary search can be used correctly?", "Binary Search Basics"),
      buildSeedQuestion("Why does binary search require sorted data before halving the range?", "Binary Search Basics"),
    ]);
    await page.reload();

    await expect(page.getByTestId("quiz-panel")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("quiz-option-A").click();
    await expect(page.getByText("Binary search relies on ordering")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("right-tab-review").last().click();
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 30_000 });
    await diagnoseLatestWrongAnswer(page);
    await expect(page.getByTestId("review-stats")).toContainText("trap vulnerability: 1", { timeout: 30_000 });

    await page.getByTestId("right-tab-quiz").last().click();
    const quizQuestion = page.getByTestId("quiz-question");
    await expect(quizQuestion).toBeVisible({ timeout: 15_000 });
    const questionText = (await quizQuestion.textContent()) || "";
    if (!questionText.includes("binary search require sorted data")) {
      await page.keyboard.press("ArrowRight");
      await expect(quizQuestion).toContainText("binary search require sorted data", { timeout: 15_000 });
    }
    await page.getByTestId("quiz-option-A").click();
    await expect(page.getByText("Binary search relies on ordering")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("right-tab-review").last().click();
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 30_000 });
    await diagnoseLatestWrongAnswer(page);
    await expect(page.getByTestId("review-stats")).toContainText("trap vulnerability: 2", { timeout: 30_000 });

    await page.goto("/analytics");
    await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId(`analytics-course-${courseId}`)).toContainText("Diagnosed: 2", { timeout: 15_000 });
  });
});
