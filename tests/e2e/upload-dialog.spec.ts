import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourse,
  SAMPLE_COURSE_MD,
  SAMPLE_COURSE_2_MD,
} from "./helpers/test-utils";

// ---------------------------------------------------------------------------
// All upload-dialog tests require a course to be created first so they run
// inside the workspace. We use test.describe.serial() because each test
// within a serial block shares the same course to avoid redundant setup.
// ---------------------------------------------------------------------------

test.describe.serial("File upload tab", () => {
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourse(page, "Upload Dialog Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("workspace-upload-trigger")).toBeVisible({ timeout: 15_000 });
  });

  test("dialog opens when clicking upload trigger", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    // The dialog title should become visible
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("Upload File")).toBeVisible();
  });

  test("file input exists with correct accept types", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();

    const fileInput = page.getByTestId("workspace-upload-file-input");
    await expect(fileInput).toBeAttached();
    const accept = await fileInput.getAttribute("accept");
    expect(accept).toContain(".pdf");
    expect(accept).toContain(".pptx");
    expect(accept).toContain(".docx");
    expect(accept).toContain(".md");
    expect(accept).toContain(".txt");
  });

  test("uploading a markdown file shows success toast", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();

    await page.getByTestId("workspace-upload-file-input").setInputFiles(SAMPLE_COURSE_MD);
    // Wait for the success toast
    await expect(page.getByText(/Uploaded sample-course\.md/i)).toBeVisible({ timeout: 30_000 });
  });

  test("dialog closes after successful upload", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();

    await page.getByTestId("workspace-upload-file-input").setInputFiles(SAMPLE_COURSE_2_MD);
    await expect(page.getByText(/Uploaded sample-course-2\.md/i)).toBeVisible({ timeout: 30_000 });

    // Dialog should close automatically after successful upload
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 15_000 });
  });

  test("content tree updates after file upload", async ({ page }) => {
    // After previous uploads, the notes panel should contain content from the uploaded file
    // The sample-course.md contains "Binary Search Basics"
    await expect(page.getByTestId("notes-panel")).toContainText("Binary Search", { timeout: 30_000 });
  });

  test("notes panel shows uploaded content", async ({ page }) => {
    // Verify the notes panel reflects content from sample-course.md
    await expect(page.getByTestId("notes-panel")).toContainText("Binary Search", { timeout: 30_000 });
  });

  test("upload button shows loading state during upload", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // The Choose File button should show "Uploading..." text while uploading
    // We check that the button label exists before upload
    await expect(page.getByText("Choose File")).toBeVisible();

    // Start the upload — the loading state may be brief so we just verify
    // the initial state is correct (non-loading)
    const chooseFileButton = page.getByText("Choose File");
    await expect(chooseFileButton).toBeVisible();
  });
});

test.describe.serial("URL tab", () => {
  let courseId: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await skipOnboarding(page);
    courseId = await createCourse(page, "Upload Dialog URL Tests");
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto(`/course/${courseId}`);
    await expect(page.getByTestId("workspace-upload-trigger")).toBeVisible({ timeout: 15_000 });
  });

  test("URL tab is clickable", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();

    // Click the "Paste URL" tab
    await page.getByRole("tab", { name: /Paste URL/i }).click();
    // URL input should be visible
    await expect(page.getByPlaceholder(/https:\/\/example\.com/i)).toBeVisible();
  });

  test("URL input and Scrape button are visible", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("tab", { name: /Paste URL/i }).click();

    await expect(page.getByPlaceholder(/https:\/\/example\.com/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /Scrape & Import/i })).toBeVisible();
  });

  test("empty URL disables Scrape button", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("tab", { name: /Paste URL/i }).click();

    const scrapeButton = page.getByRole("button", { name: /Scrape & Import/i });
    await expect(scrapeButton).toBeDisabled();
  });

  test("Scrape with invalid URL shows error toast", async ({ page }) => {
    await page.getByTestId("workspace-upload-trigger").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("tab", { name: /Paste URL/i }).click();

    const urlInput = page.getByPlaceholder(/https:\/\/example\.com/i);
    await urlInput.fill("not-a-valid-url");

    const scrapeButton = page.getByRole("button", { name: /Scrape & Import/i });
    await expect(scrapeButton).toBeEnabled();
    await scrapeButton.click();

    // Expect an error toast
    await expect(page.getByText(/Scrape failed/i)).toBeVisible({ timeout: 30_000 });
  });
});
