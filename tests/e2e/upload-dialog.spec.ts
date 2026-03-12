import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  SAMPLE_COURSE_MD,
  SAMPLE_COURSE_2_MD,
} from "./helpers/test-utils";

/**
 * File upload tests.
 *
 * File uploads happen in two places:
 * 1. The /new page (ContentUploadStep) — for new courses
 * 2. The /setup?step=content page — during onboarding
 *
 * These tests use the /new page upload form.
 */

test.describe.serial("File upload", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    await expect(page.getByTestId("project-name-input")).toBeVisible({ timeout: 15_000 });
  });

  test("upload dropzone is visible", async ({ page }) => {
    await expect(page.getByTestId("upload-dropzone")).toBeVisible();
  });

  test("file input exists with correct accept types", async ({ page }) => {
    const fileInput = page.getByTestId("project-file-input");
    await expect(fileInput).toBeAttached();
    const accept = await fileInput.getAttribute("accept");
    expect(accept).toContain(".pdf");
    expect(accept).toContain(".md");
    expect(accept).toContain(".txt");
  });

  test("file can be selected for upload", async ({ page }) => {
    await page.getByTestId("project-file-input").setInputFiles(SAMPLE_COURSE_MD);
    // The file name should appear somewhere after selection
    await expect(page.getByText(/sample-course/i)).toBeVisible({ timeout: 15_000 });
  });
});

test.describe.serial("URL input", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    await expect(page.getByTestId("project-name-input")).toBeVisible({ timeout: 15_000 });
  });

  test("URL input is visible (both mode)", async ({ page }) => {
    await expect(page.getByTestId("project-url-input")).toBeVisible();
  });

  test("URL input accepts text", async ({ page }) => {
    const urlInput = page.getByTestId("project-url-input");
    await urlInput.fill("https://example.com/test");
    await expect(urlInput).toHaveValue("https://example.com/test");
  });

  test("autoscrape toggle is visible", async ({ page }) => {
    await expect(page.getByTestId("autoscrape-toggle")).toBeVisible();
  });
});
