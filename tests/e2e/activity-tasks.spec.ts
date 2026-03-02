import { expect, test } from "@playwright/test";
import { createCourseWithContent, skipOnboarding } from "./helpers/test-utils";

const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || "http://127.0.0.1:8005/api";

async function openActivityPanel(page: import("@playwright/test").Page) {
  await page.getByTitle("Activity").click();
  await expect(page.getByTestId("activity-panel")).toBeVisible({ timeout: 15_000 });
}

test.describe.serial("Activity task controls", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("approval and resume controls mutate durable task state from the activity panel", async ({ page, request }) => {
    const courseId = await createCourseWithContent(page, "Activity Task Flow");
    await openActivityPanel(page);

    const approvalResp = await request.post(`${apiBaseUrl}/tasks/submit`, {
      data: {
        task_type: "exam_prep",
        title: "Browser approval task",
        course_id: courseId,
        input_json: { course_id: courseId, days_until_exam: 5 },
        requires_approval: true,
        max_attempts: 2,
      },
    });
    expect(approvalResp.ok()).toBeTruthy();
    const approvalTask = await approvalResp.json();

    await expect(page.getByTestId(`approval-inbox-task-${approvalTask.id}`)).toContainText("pending approval", { timeout: 15_000 });
    await page.getByTestId(`approval-inbox-approve-${approvalTask.id}`).click();
    await expect(page.getByTestId(`agent-task-${approvalTask.id}`)).toContainText(/queued|running|completed/, { timeout: 15_000 });

    const resumableResp = await request.post(`${apiBaseUrl}/tasks/submit`, {
      data: {
        task_type: "weekly_prep",
        title: "Browser resumable task",
        course_id: courseId,
        input_json: { course_id: courseId },
        max_attempts: 1,
      },
    });
    expect(resumableResp.ok()).toBeTruthy();
    const resumableTask = await resumableResp.json();

    const cancelResp = await request.post(`${apiBaseUrl}/tasks/${resumableTask.id}/cancel`);
    expect(cancelResp.ok()).toBeTruthy();

    await page.reload();
    await openActivityPanel(page);
    await expect(page.getByTestId(`agent-task-${resumableTask.id}`)).toContainText("cancelled", { timeout: 15_000 });
    await page.getByTestId(`agent-task-resume-${resumableTask.id}`).click();
    await expect(page.getByTestId(`agent-task-${resumableTask.id}`)).toContainText(/resuming|queued|running|completed/, {
      timeout: 15_000,
    });
  });

  test("activity panel can create, display, and complete a study goal", async ({ page }) => {
    await createCourseWithContent(page, "Activity Goal Flow");
    await openActivityPanel(page);

    await page.getByTestId("goal-title-input").fill("Pass the final");
    await page.getByTestId("goal-objective-input").fill("Score above 85% and eliminate binary search mistakes.");
    await page.getByTestId("goal-next-action-input").fill("Review wrong answers from chapter 2");
    await page.getByRole("button", { name: "Create Goal" }).click();

    const goalCard = page.getByTestId(/^study-goal-/).first();
    await expect(goalCard).toContainText("Pass the final", { timeout: 15_000 });
    await expect(goalCard).toContainText("Review wrong answers from chapter 2", { timeout: 15_000 });
    await goalCard.getByRole("button", { name: "Complete" }).click();
    await expect(goalCard).toContainText("completed", { timeout: 15_000 });
  });

  test("next best action can be queued into a durable task from the activity panel", async ({ page }) => {
    await createCourseWithContent(page, "Next Action Queue Flow");
    await openActivityPanel(page);

    await page.getByTestId("goal-title-input").fill("Pass the final");
    await page.getByTestId("goal-objective-input").fill("Score above 85% and finish the review queue.");
    await page.getByTestId("goal-next-action-input").fill("Review wrong answers from chapter 2 tonight");
    await page.getByRole("button", { name: "Create Goal" }).click();

    await expect(page.getByTestId("next-action-queue-button")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("next-action-queue-button").click();

    const queuedTask = page.getByTestId(/agent-task-/).filter({ hasText: "Execute next step: Pass the final" }).first();
    await expect(queuedTask).toBeVisible({ timeout: 15_000 });
    await expect(queuedTask).toContainText(/queued|running|completed/i, { timeout: 15_000 });
  });

  test("completed task review can queue a follow-up directly from the activity panel", async ({ page, request }) => {
    const courseId = await createCourseWithContent(page, "Completed Review Flow");

    const workflowResp = await request.post(`${apiBaseUrl}/workflows/exam-prep`, {
      data: {
        course_id: courseId,
        days_until_exam: 5,
      },
    });
    expect(workflowResp.ok()).toBeTruthy();

    const tasksResp = await request.get(`${apiBaseUrl}/tasks/?course_id=${courseId}`);
    expect(tasksResp.ok()).toBeTruthy();
    const [completedTask] = await tasksResp.json();
    expect(completedTask.id).toBeTruthy();

    await openActivityPanel(page);

    await expect(page.getByTestId(`agent-task-review-${completedTask.id}`)).toContainText("Next recommended action", { timeout: 15_000 });
    await page.getByTestId(`agent-task-follow-up-${completedTask.id}`).click();

    const followUpTask = page.getByTestId(/agent-task-/).filter({ hasText: "Follow-up: Generated exam prep plan" }).first();
    await expect(followUpTask).toBeVisible({ timeout: 15_000 });
  });
});
