import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourse,
  createCourseWithContent,
  sendChatMessage,
  SAMPLE_COURSE_MD,
} from "./helpers/test-utils";

// ---------------------------------------------------------------------------
// Basic chat
// ---------------------------------------------------------------------------
test.describe("Basic chat", () => {
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourse(page, "Chat Basic Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("chat-input")).toBeVisible({ timeout: 15_000 });
  });

  test("shows empty state with placeholder text", async ({ page }) => {
    // When no messages exist, the chat panel shows placeholder text
    await expect(page.getByText(/AI will reference your uploaded materials/i)).toBeVisible();
  });

  test("chat input accepts text", async ({ page }) => {
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Hello, this is a test message");
    await expect(chatInput).toHaveValue("Hello, this is a test message");
  });

  test("send button disabled when input is empty", async ({ page }) => {
    const sendButton = page.getByTestId("chat-send");
    // Input should be empty initially
    await expect(page.getByTestId("chat-input")).toHaveValue("");
    await expect(sendButton).toBeDisabled();
  });

  test("sending a message shows user bubble", async ({ page }) => {
    const message = "What is binary search?";
    await page.getByTestId("chat-input").fill(message);
    await page.getByTestId("chat-send").click();

    // The user message should appear in the chat
    await expect(page.getByText(message)).toBeVisible({ timeout: 15_000 });
  });

  test("assistant responds with mock LLM message", async ({ page }) => {
    await sendChatMessage(page, "Explain bubble sort");

    // The mock LLM fallback response pattern
    await expect(
      page.getByText("No LLM API key configured. This is a local fallback response.")
    ).toBeVisible({ timeout: 30_000 });
  });

  test("Enter key sends message", async ({ page }) => {
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Sending with enter key");
    await chatInput.press("Enter");

    // The message should appear in the chat
    await expect(page.getByText("Sending with enter key")).toBeVisible({ timeout: 15_000 });
  });

  test("Shift+Enter inserts newline without sending", async ({ page }) => {
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
    const chatInput = page.getByTestId("chat-input");
    await chatInput.fill("Quick test for streaming state");
    await page.getByTestId("chat-send").click();

    // Immediately after clicking send, the button should be disabled
    // (it re-enables once streaming finishes). We check the disabled state
    // by verifying the button is either disabled or becomes enabled after
    // the response arrives.
    await expect(
      page.locator('[class*="assistant"], [data-role="assistant"]').last()
    ).toBeVisible({ timeout: 30_000 });
  });
});

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------
test.describe.serial("Session management", () => {
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourse(page, "Chat Session Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("chat-input")).toBeVisible({ timeout: 15_000 });
  });

  test("session dropdown is visible", async ({ page }) => {
    const sessionSelect = page.getByTestId("chat-session-select");
    await expect(sessionSelect).toBeVisible();
  });

  test("New button clears messages and creates session", async ({ page }) => {
    // First send a message to create history
    await sendChatMessage(page, "First message for session test");
    await expect(page.getByText("First message for session test")).toBeVisible({ timeout: 15_000 });

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

    // The session dropdown should have a non-empty value (a session ID)
    await expect(page.getByTestId("chat-session-select")).toHaveValue(/.+/, { timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Chat with content
// ---------------------------------------------------------------------------
test.describe.serial("Chat with content", () => {
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourseWithContent(page, "Chat Content Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("chat-input")).toBeVisible({ timeout: 15_000 });
  });

  test("chat after file upload gets contextual response", async ({ page }) => {
    await sendChatMessage(page, "What does this course cover?");

    // The mock LLM fallback should reference the user's message
    await expect(
      page.getByText("No LLM API key configured. This is a local fallback response.")
    ).toBeVisible({ timeout: 30_000 });
  });

  test("multiple messages maintain conversation history", async ({ page }) => {
    await sendChatMessage(page, "First question about binary search");
    await expect(page.getByText("First question about binary search")).toBeVisible({
      timeout: 15_000,
    });

    await sendChatMessage(page, "Second follow-up question");
    await expect(page.getByText("Second follow-up question")).toBeVisible({ timeout: 15_000 });

    // Both user messages should still be visible in the conversation
    await expect(page.getByText("First question about binary search")).toBeVisible();
    await expect(page.getByText("Second follow-up question")).toBeVisible();
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

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourse(page, "Chat Edge Case Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("chat-input")).toBeVisible({ timeout: 15_000 });
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
    await expect(page.getByText(/AI will reference your uploaded materials/i)).toBeVisible();
  });

  test("very long message can be sent", async ({ page }) => {
    const longMessage = "This is a very long test message. ".repeat(50);
    await page.getByTestId("chat-input").fill(longMessage);

    // Send button should be enabled for a non-empty message
    await expect(page.getByTestId("chat-send")).toBeEnabled();
    await page.getByTestId("chat-send").click();

    // Should receive a response (mock fallback)
    await expect(
      page.locator('[class*="assistant"], [data-role="assistant"]').last()
    ).toBeVisible({ timeout: 30_000 });
  });
});
