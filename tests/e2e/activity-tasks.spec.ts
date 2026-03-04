import { expect, test } from "@playwright/test";
import { createCourseWithContent, dispatchShortcut, skipOnboarding, switchScene } from "./helpers/test-utils";

const useExistingServer = process.env.PLAYWRIGHT_USE_EXISTING_SERVER === "1";
const backendPort = Number(process.env.PLAYWRIGHT_BACKEND_PORT || (useExistingServer ? "8000" : "8005"));
const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || `http://127.0.0.1:${backendPort}/api`;

async function openTasksView(page: import("@playwright/test").Page) {
  // Use switchScene which has retry logic for keyboard shortcut dispatch
  await switchScene(page, "exam_prep");

  const tasksTab = page.getByRole("button", { name: "Tasks", exact: true });
  await expect(tasksTab).toBeVisible({ timeout: 15_000 });
  await tasksTab.click();
}

async function reloadTasksView(page: import("@playwright/test").Page) {
  await page.reload();
  await openTasksView(page);
}

test.describe.serial("Activity task controls", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("approval controls update task status from the tasks view", async ({ page, request }) => {
    test.setTimeout(150_000);
    const courseId = await createCourseWithContent(page, "Activity Task Flow");
    await openTasksView(page);

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

    await reloadTasksView(page);
    await expect(page.getByText("Needs Approval (1)")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Browser approval task")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("button", { name: "Approve" }).click();

    await expect.poll(async () => {
      const taskResp = await request.get(`${apiBaseUrl}/tasks/?course_id=${courseId}`);
      const tasks = (await taskResp.json()) as Array<{ id: string; status: string }>;
      return tasks.find((task) => task.id === approvalTask.id)?.status ?? "";
    }, { timeout: 15_000 }).not.toBe("pending_approval");

    await reloadTasksView(page);
    await expect(page.getByText("Browser approval task")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/queued|running|completed/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("tasks view reflects cancel and resume state transitions", async ({ page, request }) => {
    test.setTimeout(150_000);
    const courseId = await createCourseWithContent(page, "Activity Resume Flow");
    await openTasksView(page);

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

    await reloadTasksView(page);
    await expect(page.getByText("Browser resumable task")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("cancelled").first()).toBeVisible({ timeout: 15_000 });

    const resumeResp = await request.post(`${apiBaseUrl}/tasks/${resumableTask.id}/resume`);
    expect(resumeResp.ok()).toBeTruthy();

    await reloadTasksView(page);
    await expect(page.getByText("Browser resumable task")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/resuming|queued|running|completed/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("tasks view lists goals created via the durable goals API", async ({ page, request }) => {
    test.setTimeout(150_000);
    const courseId = await createCourseWithContent(page, "Activity Goal Flow");

    const createResp = await request.post(`${apiBaseUrl}/goals/`, {
      data: {
        course_id: courseId,
        title: "Pass the final",
        objective: "Score above 85% and eliminate binary search mistakes.",
        next_action: "Review wrong answers from chapter 2",
      },
    });
    expect(createResp.ok()).toBeTruthy();
    const goal = await createResp.json();

    await openTasksView(page);
    await expect(page.getByText("Goals (1)")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(goal.title)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(goal.objective)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Next: Review wrong answers from chapter 2")).toBeVisible({ timeout: 15_000 });

    const completeResp = await request.patch(`${apiBaseUrl}/goals/${goal.id}`, {
      data: { status: "completed" },
    });
    expect(completeResp.ok()).toBeTruthy();

    await reloadTasksView(page);
    await expect(page.getByText(goal.title)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("completed").first()).toBeVisible({ timeout: 15_000 });
  });

  test("queued next action tasks appear in the tasks view", async ({ page, request }) => {
    test.setTimeout(150_000);
    const courseId = await createCourseWithContent(page, "Next Action Queue Flow");

    const createGoalResp = await request.post(`${apiBaseUrl}/goals/`, {
      data: {
        course_id: courseId,
        title: "Pass the final",
        objective: "Score above 85% and finish the review queue.",
        next_action: "Review wrong answers from chapter 2 tonight",
      },
    });
    expect(createGoalResp.ok()).toBeTruthy();

    const queueResp = await request.post(`${apiBaseUrl}/goals/${courseId}/next-action/queue`);
    expect(queueResp.ok()).toBeTruthy();
    const queuedTask = await queueResp.json();

    await openTasksView(page);
    await expect(page.getByText(queuedTask.title)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/queued|running|completed/i).first()).toBeVisible({ timeout: 15_000 });
  });
});
