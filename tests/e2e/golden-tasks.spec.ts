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
  hasRealLlmEnv,
  openChatDrawer,
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

    // Verify content tree has nodes (poll to handle read-after-write lag under load)
    await expect.poll(async () => {
      const treeResp = await request.get(`${apiBaseUrl}/courses/${courseId}/content-tree`);
      if (!treeResp.ok()) return 0;
      const tree = await treeResp.json();
      return Array.isArray(tree) ? tree.length : 0;
    }, { timeout: 15_000 }).toBeGreaterThan(0);
  });

  test("GT-2: Chat sends message and receives response", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Chat");

    // Open the chat drawer first
    await openChatDrawer(page);
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("What is this course about?");
    await chatInput.press("Enter");

    // Wait for assistant response
    await expectAssistantMessage(page);
  });

  test("GT-3: Submit exam prep task", async ({ page, request }) => {
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Plan");

    // Retry on 503 (SQLite lock from concurrent ingestion) or 429 (rate limit)
    let resp!: Awaited<ReturnType<typeof request.post>>;
    for (let attempt = 0; attempt < 5; attempt++) {
      resp = await request.post(`${apiBaseUrl}/tasks/submit`, {
        data: {
          task_type: "exam_prep",
          title: "Golden exam prep task",
          course_id: courseId,
          input_json: { course_id: courseId, days_until_exam: 3 },
          requires_approval: true,
          max_attempts: 2,
        },
      });
      if (resp.ok() || (resp.status() !== 503 && resp.status() !== 429)) break;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
    expect(resp.ok()).toBeTruthy();
    const task = await resp.json();
    expect(task.status).toBe("pending_approval");
    expect(task.task_type).toBe("exam_prep");
  });

  test("GT-4: Create goal → submit task → verify in tasks view", async ({ page, request }) => {
    test.setTimeout(150_000);
    const courseId = await createCourseWithContent(page, "Golden Goal");

    // Create a study goal with a deadline (retry on 503 — SQLite lock from ingestion)
    let goalResp!: Awaited<ReturnType<typeof request.post>>;
    for (let attempt = 0; attempt < 5; attempt++) {
      goalResp = await request.post(`${apiBaseUrl}/goals/`, {
        data: {
          course_id: courseId,
          title: "Master Chapter 1",
          objective: "Achieve 90% accuracy on Chapter 1 quiz",
          target_date: new Date(Date.now() + 3 * 86_400_000).toISOString(),
          next_action: "Review key concepts",
        },
      });
      if (goalResp.ok() || (goalResp.status() !== 503 && goalResp.status() !== 429)) break;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
    expect(goalResp.ok()).toBeTruthy();
    const goal = await goalResp.json();
    expect(goal.id).toBeTruthy();

    // Submit a task linked to the goal (retry on 503/429)
    let taskResp!: Awaited<ReturnType<typeof request.post>>;
    for (let attempt = 0; attempt < 5; attempt++) {
      taskResp = await request.post(`${apiBaseUrl}/tasks/submit`, {
        data: {
          task_type: "exam_prep",
          title: "Golden task: review prep",
          course_id: courseId,
          input_json: { course_id: courseId, days_until_exam: 3 },
          requires_approval: true,
          max_attempts: 2,
        },
      });
      if (taskResp.ok() || (taskResp.status() !== 503 && taskResp.status() !== 429)) break;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
    expect(taskResp.ok()).toBeTruthy();
    const task = await taskResp.json();
    expect(task.status).toBe("pending_approval");

    // Verify task was created via API
    const listResp = await request.get(`${apiBaseUrl}/tasks/?course_id=${courseId}`);
    expect(listResp.ok()).toBeTruthy();
    const tasks = await listResp.json();
    const found = tasks.some((t: { title: string }) => t.title === "Golden task: review prep");
    expect(found).toBeTruthy();
  });

  test("GT-5: Preference dismiss and restore round-trip", async ({ page, request }) => {
    test.setTimeout(120_000);
    const courseId = await createCourseWithContent(page, "Golden Prefs");

    // Set a preference via API (retry on 503 — SQLite lock)
    let prefResp!: Awaited<ReturnType<typeof request.post>>;
    for (let attempt = 0; attempt < 5; attempt++) {
      prefResp = await request.post(`${apiBaseUrl}/preferences/`, {
        data: {
          dimension: "explanation_style",
          value: "detailed",
          scope: "course",
          course_id: courseId,
          source: "golden_test",
        },
      });
      if (prefResp.ok() || (prefResp.status() !== 503 && prefResp.status() !== 429)) break;
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
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
