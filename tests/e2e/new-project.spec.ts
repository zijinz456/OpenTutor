import { expect, test } from "@playwright/test";
import { skipOnboarding } from "./helpers/test-utils";

/**
 * New Project page tests.
 *
 * The /new page is a simplified "add another course" flow for returning users.
 * It skips mode selection and feature config — goes straight to upload → parse → workspace.
 * Mode is hardcoded to "both" (file upload + URL).
 */

// ---------------------------------------------------------------------------
// Upload Form (the page lands directly on this step)
// ---------------------------------------------------------------------------
test.describe("Upload Form", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    // The upload step is shown immediately (no mode selection)
    await expect(page.getByTestId("project-name-input")).toBeVisible({ timeout: 15_000 });
  });

  test("shows project name input", async ({ page }) => {
    const input = page.getByTestId("project-name-input");
    await expect(input).toBeVisible();
  });

  test("shows file upload area", async ({ page }) => {
    // The hidden file input should exist in the DOM
    const fileInput = page.getByTestId("project-file-input");
    await expect(fileInput).toBeAttached();
  });

  test("project name input accepts text", async ({ page }) => {
    const input = page.getByTestId("project-name-input");
    await input.fill("My Test Project");
    await expect(input).toHaveValue("My Test Project");
  });

  test("shows URL input (both mode includes URL)", async ({ page }) => {
    await expect(page.getByTestId("project-url-input")).toBeVisible();
  });

  test("shows file upload dropzone", async ({ page }) => {
    await expect(page.getByTestId("upload-dropzone")).toBeVisible();
  });

  test("Back button navigates to dashboard", async ({ page }) => {
    await page.getByTestId("new-back-mode").click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });
  });

  test("Start Parsing button starts course creation", async ({ page }) => {
    await page.getByTestId("project-name-input").fill("Parse Test Project");
    await page.getByTestId("start-parsing").click();
    // Should transition to parsing step — heading confirms the step changed
    await expect(
      page.getByRole("heading", { name: /processing/i }),
    ).toBeVisible({ timeout: 30_000 });
  });
});

// ---------------------------------------------------------------------------
// Parsing Progress
// ---------------------------------------------------------------------------
test.describe("Parsing Progress", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    await page.getByTestId("project-name-input").fill("Parsing Progress Test");
    await page.getByTestId("start-parsing").click();
  });

  test("shows progress indicators", async ({ page }) => {
    const progressOrContinue = page.getByTestId("continue-to-features")
      .or(page.getByTestId("enter-now"))
      .or(page.getByText(/\d+%/));
    await expect(progressOrContinue.first()).toBeVisible({ timeout: 60_000 });
  });

  test("Continue button appears after parsing and navigates to workspace", async ({ page }) => {
    // Either continue-to-features or enter-now button should appear
    const continueBtn = page.getByTestId("continue-to-features").or(page.getByTestId("enter-now"));
    await expect(continueBtn.first()).toBeVisible({ timeout: 60_000 });
    await continueBtn.first().click();
    await expect(page).toHaveURL(/\/course\//, { timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Full flow
// ---------------------------------------------------------------------------
test.describe("Full flow", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("complete upload flow end-to-end", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/new");
    await page.getByTestId("project-name-input").fill("Upload E2E Test");
    await page.getByTestId("start-parsing").click();

    // Wait for parsing to finish — either continue-to-features or enter-now button
    const continueBtn = page.getByTestId("continue-to-features").or(page.getByTestId("enter-now"));
    await expect(continueBtn.first()).toBeVisible({ timeout: 60_000 });
    await continueBtn.first().click();

    // Should arrive at workspace
    await expect(page).toHaveURL(/\/course\//, { timeout: 15_000 });
  });

  test("both mode shows file and URL inputs", async ({ page }) => {
    await page.goto("/new");
    // Both file upload area and URL input should be present (mode is hardcoded "both")
    await expect(page.getByTestId("upload-dropzone")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("project-url-input")).toBeVisible();
    await expect(page.getByTestId("autoscrape-toggle")).toBeVisible();
  });

  test("wizard preserves project name through steps", async ({ page }) => {
    const projectName = "Persistence Test Project";
    await page.goto("/new");

    await page.getByTestId("project-name-input").fill(projectName);
    await page.getByTestId("start-parsing").click();

    // The project name should appear in the parsing step
    await expect(page.getByText(projectName, { exact: true }).first()).toBeVisible({ timeout: 15_000 });
  });
});
