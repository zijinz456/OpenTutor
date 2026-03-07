/**
 * Golden Task E2E Tests
 *
 * Representative learning scenario tests that exercise the full stack:
 * course creation → content upload → AI generation → practice → review.
 * These are the "happy path" smoke tests that must pass before any release.
 */
import path from "node:path";

import { expect, test } from "@playwright/test";
import {
  createCourseWithContent,
  dispatchShortcut,
  expectAssistantMessage,
  skipOnboarding,
  switchScene,
} from "./helpers/test-utils";

const useExistingServer = process.env.PLAYWRIGHT_USE_EXISTING_SERVER === "1";
const backendPort = Number(process.env.PLAYWRIGHT_BACKEND_PORT || (useExistingServer ? "8000" : "8005"));
const apiBaseUrl = process.env.PLAYWRIGHT_API_URL || `http://127.0.0.1:${backendPort}/api`;

test.describe.serial("Golden tasks — core learning journey", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("GT-1: Upload content → content tree populated", async ({ page, request }) => {
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Upload");

    // Verify content tree has nodes
    const treeResp = await request.get(`${apiBaseUrl}/courses/${courseId}/content-tree`);
    expect(treeResp.ok()).toBeTruthy();
    const tree = await treeResp.json();
    expect(tree.length).toBeGreaterThan(0);
  });

  test("GT-2: Chat sends message and receives response", async ({ page }) => {
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Chat");

    // Find the chat input and type a message
    const chatInput = page.getByTestId("chat-input");
    await expect(chatInput).toBeVisible({ timeout: 30_000 });
    await chatInput.fill("What is this course about?");
    await chatInput.press("Enter");

    // Wait for assistant response
    await expectAssistantMessage(page, { timeout: 60_000 });
  });

  test("GT-3: Submit exam prep task from exam scene", async ({ page, request }) => {
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Plan");

    // Switch to exam_prep scene first to validate scene routing UX.
    await switchScene(page, "exam_prep");

    const resp = await request.post(`${apiBaseUrl}/tasks/submit`, {
      data: {
        task_type: "exam_prep",
        title: "Golden exam prep task",
        course_id: courseId,
        input_json: { course_id: courseId, days_until_exam: 3 },
        requires_approval: true,
        max_attempts: 2,
      },
    });
    expect(resp.ok()).toBeTruthy();
    const task = await resp.json();
    expect(task.status).toBe("pending_approval");
    expect(task.task_type).toBe("exam_prep");
  });

  test("GT-4: Create goal → submit task → verify in tasks view", async ({ page, request }) => {
    test.setTimeout(150_000);
    const courseId = await createCourseWithContent(page, "Golden Goal");

    // Create a study goal with a deadline
    const goalResp = await request.post(`${apiBaseUrl}/goals/`, {
      data: {
        course_id: courseId,
        title: "Master Chapter 1",
        objective: "Achieve 90% accuracy on Chapter 1 quiz",
        target_date: new Date(Date.now() + 3 * 86_400_000).toISOString(),
        next_action: "Review key concepts",
      },
    });
    expect(goalResp.ok()).toBeTruthy();
    const goal = await goalResp.json();
    expect(goal.id).toBeTruthy();

    // Submit a task linked to the goal
    const taskResp = await request.post(`${apiBaseUrl}/tasks/submit`, {
      data: {
        task_type: "exam_prep",
        title: "Golden task: review prep",
        course_id: courseId,
        input_json: { course_id: courseId, days_until_exam: 3 },
        requires_approval: true,
        max_attempts: 2,
      },
    });
    expect(taskResp.ok()).toBeTruthy();
    const task = await taskResp.json();
    expect(task.status).toBe("pending_approval");

    // Verify task appears in the tasks view
    await switchScene(page, "exam_prep");
    const tasksTab = page.getByRole("button", { name: "Tasks", exact: true });
    await expect(tasksTab).toBeVisible({ timeout: 15_000 });
    await tasksTab.click();
    await page.reload();
    await switchScene(page, "exam_prep");
    await tasksTab.click();
    await expect(page.getByText("Golden task: review prep")).toBeVisible({ timeout: 15_000 });
  });

  test("GT-5: Preference dismiss and restore round-trip", async ({ page, request }) => {
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Prefs");

    // Set a preference via API
    const prefResp = await request.post(`${apiBaseUrl}/preferences/`, {
      data: {
        dimension: "explanation_style",
        value: "detailed",
        scope: "course",
        course_id: courseId,
        source: "golden_test",
      },
    });
    expect(prefResp.ok()).toBeTruthy();
    const pref = await prefResp.json();

    // Dismiss it
    const dismissResp = await request.post(`${apiBaseUrl}/preferences/${pref.id}/dismiss`, {
      data: { reason: "test dismissal" },
    });
    expect(dismissResp.ok()).toBeTruthy();
    const dismissed = await dismissResp.json();
    expect(dismissed.dismissed_at).toBeTruthy();

    // Restore it
    const restoreResp = await request.post(`${apiBaseUrl}/preferences/${pref.id}/restore`);
    expect(restoreResp.ok()).toBeTruthy();
    const restored = await restoreResp.json();
    expect(restored.dismissed_at).toBeNull();
  });

  test("GT-6: Health endpoint returns healthy status", async ({ request }) => {
    const resp = await request.get(`${apiBaseUrl}/health`);
    expect(resp.ok()).toBeTruthy();
    const health = await resp.json();
    expect(health.status).toBe("ok");
    expect(health.database).toBe("connected");
  });
});
