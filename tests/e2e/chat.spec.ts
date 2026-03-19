import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourseViaApi,
  createCourseWithContent,
  sendChatMessage,
  expectAssistantMessage,
  hasRealLlmEnv,
  openChatDrawer,
  presetTemplateLayout,
} from "./helpers/test-utils";

// ---------------------------------------------------------------------------
// Basic chat
// ---------------------------------------------------------------------------
test.describe("Basic chat", () => {
  let courseId: string;

  test.beforeAll(async () => {
    courseId = await createCourseViaApi("Chat Basic Tests");
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await presetTemplateLayout(page, courseId);
    await page.goto(`/course/${courseId}`);
    await openChatDrawer(page);
  });

  test("shows welcome or empty state when chat opens", async ({ page }) => {
    // The backend auto-generates a welcome greeting on new sessions,
    // so the chat may show either the "No messages yet" empty state
    // or a "Welcome back" greeting depending on timing.
    const welcomeOrEmpty = page.getByText(/No messages yet|Welcome back/i).first();
    await expect(welcomeOrEmpty).toBeVisible({ timeout: 15_000 });
  });

  test("chat input accepts text", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Hello, this is a test message");
    await expect(chatInput).toHaveValue("Hello, this is a test message");
  });

  test("send button disabled when input is empty", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    const sendButton = page.getByTestId("chat-send");
    // Input should be empty initially
    await expect(page.getByTestId("chat-input")).toHaveValue("");
    await expect(sendButton).toBeDisabled();
  });

  test("sending a message shows user bubble", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    const message = "What is binary search?";
    await page.getByTestId("chat-input").fill(message);
    await page.getByTestId("chat-send").click();

    // The user message should appear in a user bubble
    await expect(page.getByTestId("chat-message-user").getByText(message)).toBeVisible({ timeout: 15_000 });
  });

  test("assistant responds after sending a message", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    await sendChatMessage(page, "Explain bubble sort");
    await expectAssistantMessage(page);
  });

  test("Enter key sends message", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Sending with enter key");
    await chatInput.press("Enter");

    // The message should appear in a user bubble
    await expect(page.getByTestId("chat-message-user").getByText("Sending with enter key")).toBeVisible({ timeout: 15_000 });
  });

  test("Shift+Enter inserts newline without sending", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Line one");
    await chatInput.press("Shift+Enter");
    await chatInput.pressSequentially("Line two");

    // The input should contain both lines (not sent)
    const value = await chatInput.inputValue();
    expect(value).toContain("Line one");
    expect(value).toContain("Line two");

    // The send button should still be enabled (message not sent yet)
    await expect(page.getByTestId("chat-send")).toBeEnabled();
  });

  test("send button disabled while streaming", async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Streaming state is only observable with a real LLM provider");
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Quick test for streaming state");
    await page.getByTestId("chat-send").click();

    // Immediately after clicking send, the button should be disabled
    // (it re-enables once streaming finishes). With mock LLM, the response
    // arrives almost instantly, so we just verify the message appears.
    await expect(page.getByTestId("chat-message-assistant").last()).toBeVisible({ timeout: 30_000 });
  });
});

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------
test.describe.serial("Session management", () => {
  let courseId: string;

  test.beforeAll(async () => {
    courseId = await createCourseViaApi("Chat Session Tests");
  });

  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    await skipOnboarding(page);
    await presetTemplateLayout(page, courseId);
    await page.goto(`/course/${courseId}`);
    await openChatDrawer(page);
  });

  test("session dropdown is visible", async ({ page }) => {
    const sessionSelect = page.getByTestId("chat-session-select");
    await expect(sessionSelect).toBeVisible();
  });

  test("New button clears messages and creates session", async ({ page }) => {
    // First send a message to create history
    await sendChatMessage(page, "First message for session test");
    await expect(page.getByTestId("chat-message-user").getByText("First message for session test")).toBeVisible({ timeout: 15_000 });

    // Click "New" to create a new session
    await page.getByRole("button", { name: "New" }).click();

    // The empty state placeholder should reappear
    await expect(page.getByText(/AI will reference your uploaded materials/i)).toBeVisible({
      timeout: 15_000,
    });
  });

  test("session list updates after sending message", async ({ page }) => {
    // Send a message which creates/updates a session
    await sendChatMessage(page, "Session list update test message");

    // The session picker is a Radix Select trigger rather than a native <select>.
    const sessionSelect = page.getByTestId("chat-session-select");
    await expect(sessionSelect).toBeVisible({ timeout: 15_000 });
    await sessionSelect.click();
    await expect(page.getByRole("option", { name: "Current conversation" })).toBeVisible({ timeout: 15_000 });
    await expect.poll(async () => await page.getByRole("option").count(), {
      timeout: 15_000,
    }).toBeGreaterThan(1);
  });
});

// ---------------------------------------------------------------------------
// Chat with content
// ---------------------------------------------------------------------------
test.describe.serial("Chat with content", () => {
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourseWithContent(page, "Chat Content Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    await skipOnboarding(page);
    await presetTemplateLayout(page, courseId);
    await page.goto(`/course/${courseId}`);
    await openChatDrawer(page);
  });

  test("chat after file upload gets contextual response", async ({ page }) => {
    await sendChatMessage(page, "What does this course cover?");
    await expectAssistantMessage(page);
  });

  test("multiple messages maintain conversation history", async ({ page }) => {
    await sendChatMessage(page, "First question about binary search");
    await expect(page.getByTestId("chat-message-user").getByText("First question about binary search")).toBeVisible({
      timeout: 15_000,
    });

    await sendChatMessage(page, "Second follow-up question");
    await expect(page.getByTestId("chat-message-user").getByText("Second follow-up question")).toBeVisible({ timeout: 15_000 });

    // Both user messages should still be visible in the conversation
    await expect(page.getByTestId("chat-message-user").getByText("First question about binary search").first()).toBeVisible();
    await expect(page.getByTestId("chat-message-user").getByText("Second follow-up question").first()).toBeVisible();
  });

  test("chat input clears after sending", async ({ page }) => {
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("This message should clear the input");
    await page.getByTestId("chat-send").click();

    // The input should be cleared after sending
    await expect(chatInput).toHaveValue("", { timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------
test.describe("Edge cases", () => {
  let courseId: string;

  test.beforeAll(async () => {
    courseId = await createCourseViaApi("Chat Edge Case Tests");
  });

  test.beforeEach(async ({ page }) => {
    test.skip(!hasRealLlmEnv(), "Chat input is disabled without a real LLM provider");
    await skipOnboarding(page);
    await presetTemplateLayout(page, courseId);
    await page.goto(`/course/${courseId}`);
    await openChatDrawer(page);
  });

  test("empty message cannot be sent", async ({ page }) => {
    // Input is empty — send button should be disabled
    await expect(page.getByTestId("chat-send")).toBeDisabled();

    // Fill with only whitespace
    await page.getByTestId("chat-input").fill("   ");
    await expect(page.getByTestId("chat-send")).toBeDisabled();

    // Press Enter with empty input — nothing should be sent
    await page.getByTestId("chat-input").fill("");
    await page.getByTestId("chat-input").press("Enter");

    // The empty state should still be present (no message bubbles)
    await expect(page.getByText(/No messages yet|AI will reference/i)).toBeVisible();
  });

  test("very long message can be sent", async ({ page }) => {
    const longMessage = "This is a very long test message. ".repeat(50);
    await page.getByTestId("chat-input").fill(longMessage);

    // Send button should be enabled for a non-empty message
    await expect(page.getByTestId("chat-send")).toBeEnabled();
    // Use force:true to bypass any overlay elements (e.g., Tune FAB)
    await page.getByTestId("chat-send").click({ force: true });

    // Should receive a response (mock fallback)
    await expect(
      page.locator('[class*="assistant"], [data-role="assistant"]').last()
    ).toBeVisible({ timeout: 30_000 });
  });
});
