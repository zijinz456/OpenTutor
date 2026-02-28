import path from "node:path";

import { expect, test } from "@playwright/test";

const fixturePath = path.join(process.cwd(), "tests/e2e/fixtures/sample-course.md");

async function createCourse(page: import("@playwright/test").Page, projectName: string) {
  await page.goto("/new");
  await page.getByTestId("mode-option-upload").click();
  await page.getByTestId("mode-continue").click();
  await page.getByTestId("project-name-input").fill(projectName);
  await page.getByTestId("start-parsing").click();
  await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
  await page.getByTestId("continue-to-features").click();
  await page.getByTestId("enter-workspace").click();
  await expect(page).toHaveURL(/\/course\//);
}

function getCourseIdFromUrl(page: import("@playwright/test").Page): string {
  const match = page.url().match(/\/course\/([^/?#]+)/);
  if (!match) throw new Error(`Course ID not found in URL: ${page.url()}`);
  return match[1];
}

async function uploadFixture(page: import("@playwright/test").Page) {
  await page.getByTestId("workspace-upload-trigger").click();
  await page.getByTestId("workspace-upload-file-input").setInputFiles(fixturePath);
  await expect(page.getByText("Uploaded sample-course.md")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("notes-panel")).toContainText("Binary Search Basics", { timeout: 30_000 });
}

async function seedQuizSet(request: import("@playwright/test").APIRequestContext, courseId: string) {
  const rawContent = JSON.stringify([
    {
      question_type: "mc",
      question: "What must be true before binary search can be used correctly?",
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
        source_section: "Binary Search Basics",
      },
    },
  ]);

  const response = await request.post("http://127.0.0.1:8005/api/quiz/save-generated", {
    data: {
      course_id: courseId,
      raw_content: rawContent,
      title: "E2E Quiz Seed",
    },
  });
  expect(response.ok()).toBeTruthy();
}

test.describe("OpenTutor e2e flows", () => {
  test("create course, chat, switch scene, and generate a study plan", async ({ page }) => {
    await createCourse(page, "E2E Study Flow");
    await uploadFixture(page);

    await page.getByTestId("chat-input").fill("Summarize binary search in one paragraph.");
    await page.getByTestId("chat-send").click();
    await expect(page.getByText("No LLM API key configured. This is a local fallback response.")).toBeVisible({
      timeout: 30_000,
    });

    await page.getByTestId("scene-selector-trigger").click();
    await page.getByTestId("scene-option-exam_prep").click();
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("study-plan-generate").click();
    await expect(page.getByTestId("study-plan-content")).toContainText("No LLM API key configured", {
      timeout: 30_000,
    });

    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved study plan")).toBeVisible({ timeout: 15_000 });
  });

  test("generate and save AI notes from uploaded content", async ({ page }) => {
    await createCourse(page, "E2E Notes Flow");
    await uploadFixture(page);
    await page.getByTestId("notes-generate").click();
    await expect(page.getByTestId("notes-preview")).toContainText("No LLM API key configured", {
      timeout: 30_000,
    });

    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved AI notes")).toBeVisible({ timeout: 15_000 });
  });

  test("replace generated study plan, restore chat session, and persist active scene across reload", async ({ page }) => {
    await createCourse(page, "E2E Restore Flow");
    await uploadFixture(page);

    const firstPrompt = "Summarize binary search in one paragraph.";
    await page.getByTestId("chat-input").fill(firstPrompt);
    await page.getByTestId("chat-send").click();
    await expect(page.getByText("No LLM API key configured. This is a local fallback response.")).toBeVisible({
      timeout: 30_000,
    });

    await expect(page.getByTestId("chat-session-select")).toHaveValue(/.+/, { timeout: 15_000 });

    await page.getByRole("button", { name: "New" }).click();
    await expect(page.getByText("Start a conversation about your course materials")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("chat-session-select").selectOption({ label: firstPrompt });
    await expect(page.getByText(`Your message was: ${firstPrompt}`)).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("scene-selector-trigger").click();
    await page.getByTestId("scene-option-exam_prep").click();
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("study-plan-days-input").fill("5");
    await page.getByTestId("study-plan-generate").click();
    await expect(page.getByTestId("study-plan-content")).toContainText("No LLM API key configured", {
      timeout: 30_000,
    });
    await page.getByRole("button", { name: "Save New" }).click();
    await expect(page.getByText("Saved study plan")).toBeVisible({ timeout: 15_000 });

    await page.getByTestId("study-plan-days-input").fill("3");
    await page.getByTestId("study-plan-generate").click();
    await expect(page.getByTestId("study-plan-content")).toContainText("Your message was", {
      timeout: 30_000,
    });
    await page.getByRole("button", { name: "Replace Latest" }).click();
    await expect(page.getByText("Replaced plan with version 2")).toBeVisible({ timeout: 15_000 });

    await page.reload();
    await expect(page.getByTestId("scene-selector-trigger")).toContainText("Exam Prep", { timeout: 15_000 });
    await expect(page.getByTestId("study-plan-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("chat-session-select")).toHaveValue(/.+/, { timeout: 15_000 });
    await expect(page.getByText(`Your message was: ${firstPrompt}`)).toBeVisible({ timeout: 15_000 });
  });

  test("scrape URL into content tree from upload dialog", async ({ page }) => {
    await createCourse(page, "E2E Scrape Flow");

    await page.getByTestId("workspace-upload-trigger").click();
    await page.getByTestId("workspace-upload-url-tab").click();
    await page.getByTestId("workspace-upload-url-input").fill("https://opentutor-e2e.local/binary-search");
    await page.getByTestId("workspace-upload-url-submit").click();

    await expect(page.getByText("Scraped URL:")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Binary Search Notes" })).toBeVisible({ timeout: 30_000 });
  });

  test("wrong-answer diagnosis flows through review, progress, and analytics", async ({ page, request }) => {
    await createCourse(page, "E2E Diagnosis Flow");
    await uploadFixture(page);

    const courseId = getCourseIdFromUrl(page);
    await seedQuizSet(request, courseId);
    await page.reload();

    await expect(page.getByTestId("quiz-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("quiz-question")).toContainText("binary search can be used correctly", { timeout: 15_000 });
    await page.getByTestId("quiz-option-A").click();
    await expect(page.getByText("Binary search relies on ordering")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: "Review" }).click();
    await expect(page.getByTestId("review-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("review-stats")).toContainText("Unmastered: 1", { timeout: 15_000 });

    const deriveButton = page.locator("[data-testid^='derive-']").first();
    await deriveButton.click();
    const diagnosticCard = page.locator("[data-testid^='diagnostic-']").first();
    await expect(diagnosticCard).toBeVisible({ timeout: 15_000 });
    await diagnosticCard.locator("[data-testid*='-B']").click();
    await expect(page.locator("[data-testid^='diagnosis-']").first()).toContainText("trap vulnerability", {
      timeout: 15_000,
    });
    await expect(page.getByTestId("review-stats")).toContainText("trap vulnerability: 1", { timeout: 15_000 });

    await page.getByRole("button", { name: "Stats" }).click();
    await expect(page.getByTestId("progress-panel")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("progress-gap-breakdown")).toContainText("fundamental gap: 1", {
      timeout: 15_000,
    });

    await page.goto("/analytics");
    await expect(page.getByTestId("analytics-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("analytics-breakdown-diagnoses")).toContainText(/trap vulnerability: [1-9]\d*/, {
      timeout: 15_000,
    });
    await expect(page.getByTestId(`analytics-course-${courseId}`)).toContainText("E2E Diagnosis Flow", { timeout: 15_000 });
  });
});
