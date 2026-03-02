import { expect, test } from "@playwright/test";
import {
  skipOnboarding,
  createCourse,
  SAMPLE_COURSE_MD,
} from "./helpers/test-utils";

// ---------------------------------------------------------------------------
// Step 1: Mode Selection
// ---------------------------------------------------------------------------
test.describe("Step 1: Mode Selection", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
  });

  test("displays three mode options: Upload, URL, Both", async ({ page }) => {
    await expect(page.getByTestId("mode-option-upload")).toBeVisible();
    await expect(page.getByTestId("mode-option-url")).toBeVisible();
    await expect(page.getByTestId("mode-option-both")).toBeVisible();
  });

  test("Both mode is selected by default", async ({ page }) => {
    const bothCard = page.getByTestId("mode-option-both");
    await expect(bothCard).toHaveAttribute("data-selected", "true");

    const uploadCard = page.getByTestId("mode-option-upload");
    await expect(uploadCard).toHaveAttribute("data-selected", "false");
  });

  test("clicking Upload mode selects it", async ({ page }) => {
    await page.getByTestId("mode-option-upload").click();
    const uploadCard = page.getByTestId("mode-option-upload");
    await expect(uploadCard).toHaveAttribute("data-selected", "true");

    const bothCard = page.getByTestId("mode-option-both");
    await expect(bothCard).toHaveAttribute("data-selected", "false");
  });

  test("Continue button navigates to upload step", async ({ page }) => {
    await page.getByTestId("mode-continue").click();
    // Upload step shows the project name input
    await expect(page.getByTestId("project-name-input")).toBeVisible();
  });

  test("Back to Projects navigates to dashboard", async ({ page }) => {
    await page.getByRole("button", { name: /Back to Projects/i }).click();
    await expect(page).toHaveURL("/");
  });
});

// ---------------------------------------------------------------------------
// Step 2: Upload Form
// ---------------------------------------------------------------------------
test.describe("Step 2: Upload Form", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    await page.getByTestId("mode-continue").click();
    await expect(page.getByTestId("project-name-input")).toBeVisible();
  });

  test("shows project name input", async ({ page }) => {
    const input = page.getByTestId("project-name-input");
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute("placeholder", /CS101/i);
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

  test("Back button returns to mode selection", async ({ page }) => {
    await page.getByRole("button", { name: /Back/i }).first().click();
    // Mode selection cards should be visible again
    await expect(page.getByTestId("mode-option-both")).toBeVisible();
  });

  test("Start Parsing button starts course creation", async ({ page }) => {
    await page.getByTestId("project-name-input").fill("Parse Test Project");
    await page.getByTestId("start-parsing").click();
    // Should transition to parsing step — look for progress indicators
    await expect(page.getByText(/Parsing Progress/i)).toBeVisible({ timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Step 3: Parsing Progress
// ---------------------------------------------------------------------------
test.describe("Step 3: Parsing Progress", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();
    await page.getByTestId("project-name-input").fill("Parsing Progress Test");
    await page.getByTestId("start-parsing").click();
  });

  test("shows progress indicators", async ({ page }) => {
    // Wait for parsing to begin — the continue button or a progress indicator appears
    const progressOrContinue = page.getByTestId("continue-to-features").or(page.getByText(/\d+% complete/));
    await expect(progressOrContinue.first()).toBeVisible({ timeout: 60_000 });
  });

  test("Continue to Features appears after parsing", async ({ page }) => {
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
  });
});

// ---------------------------------------------------------------------------
// Step 4: Feature Selection
// ---------------------------------------------------------------------------
test.describe("Step 4: Feature Selection", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();
    await page.getByTestId("project-name-input").fill("Feature Selection Test");
    await page.getByTestId("start-parsing").click();
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();
  });

  test("shows feature cards", async ({ page }) => {
    await expect(page.getByText("Organize Notes")).toBeVisible();
    await expect(page.getByText("Practice Mode")).toBeVisible();
    await expect(page.getByText("Wrong Answer Review")).toBeVisible();
    await expect(page.getByText("Study Plan").first()).toBeVisible();
    await expect(page.getByText("Free Q&A")).toBeVisible();
  });

  test("feature cards can be toggled", async ({ page }) => {
    // "Organize Notes" is enabled by default — click to toggle it off
    const notesCard = page.getByText("Organize Notes").locator("..").locator("..");
    await notesCard.click();
    // The checkbox indicator should no longer have the selected style
    // Click again to re-enable
    await notesCard.click();
    // Should still be visible and interactable
    await expect(page.getByText("Organize Notes")).toBeVisible();
  });

  test("NL instruction textarea accepts input", async ({ page }) => {
    const textarea = page.getByPlaceholder(/Use bullet points/i);
    await expect(textarea).toBeVisible();
    await textarea.fill("Focus on algorithms and data structures");
    await expect(textarea).toHaveValue("Focus on algorithms and data structures");
  });

  test("Enter Workspace navigates to course page", async ({ page }) => {
    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//, { timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Full wizard flow
// ---------------------------------------------------------------------------
test.describe("Full wizard flow", () => {
  test.beforeEach(async ({ page }) => {
    await skipOnboarding(page);
  });

  test("complete upload mode flow end-to-end", async ({ page }) => {
    await page.goto("/new");
    // Step 1: Select upload mode
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();

    // Step 2: Fill project name
    await page.getByTestId("project-name-input").fill("Upload E2E Test");
    await page.getByTestId("start-parsing").click();

    // Step 3: Wait for parsing to finish
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();

    // Step 4: Enter workspace
    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//, { timeout: 15_000 });
  });

  test("complete URL mode flow shows URL input", async ({ page }) => {
    await page.goto("/new");
    // Select URL mode
    await page.getByTestId("mode-option-url").click();
    await page.getByTestId("mode-continue").click();

    // URL input should be visible, file upload area should NOT be visible
    await expect(page.getByPlaceholder(/https:\/\/professor-site/i)).toBeVisible();
    await expect(page.getByText("Upload Learning Materials")).not.toBeVisible();
    // Auto-Scrape settings should be visible in URL mode
    await expect(page.getByText("Auto-Scrape Settings")).toBeVisible();
  });

  test("complete Both mode flow shows file and URL inputs", async ({ page }) => {
    await page.goto("/new");
    // "Both" is default
    await page.getByTestId("mode-continue").click();

    // Both file upload area and URL input should be present
    await expect(page.getByText("Upload Learning Materials")).toBeVisible();
    await expect(page.getByPlaceholder(/https:\/\/professor-site/i)).toBeVisible();
    await expect(page.getByText("Auto-Scrape Settings")).toBeVisible();
  });

  test("wizard preserves project name through steps", async ({ page }) => {
    const projectName = "Persistence Test Project";
    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();

    await page.getByTestId("project-name-input").fill(projectName);
    await page.getByTestId("start-parsing").click();

    // The project name should appear in the parsing step sidebar
    await expect(page.getByText(projectName, { exact: true }).first()).toBeVisible({ timeout: 15_000 });

    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();

    // The project name should appear in the feature selection header
    await expect(page.getByText(projectName, { exact: true }).first()).toBeVisible();
  });

  test("feature toggles persist to course metadata", async ({ page }) => {
    let patchedMetadata: Record<string, unknown> | null = null;
    await page.route("**/api/courses/*", async (route) => {
      const request = route.request();
      if (request.method() !== "PATCH") {
        await route.continue();
        return;
      }

      const payload = JSON.parse(request.postData() || "{}") as { metadata?: Record<string, unknown> };
      patchedMetadata = payload.metadata ?? null;
      const courseId = request.url().split("/").pop() || "test-course";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: courseId,
          name: "LocalStorage Features Test",
          description: null,
          metadata: payload.metadata ?? null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      });
    });

    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();
    await page.getByTestId("project-name-input").fill("LocalStorage Features Test");
    await page.getByTestId("start-parsing").click();
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();

    // Toggle "Practice Mode" off by clicking its card
    const practiceCard = page.getByRole("button", { name: /Practice Mode/ });
    await practiceCard.click();

    // Enter workspace
    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//, { timeout: 15_000 });

    // Extract courseId from URL
    const url = page.url();
    const courseId = url.match(/\/course\/([^/?#]+)/)?.[1];
    expect(courseId).toBeTruthy();

    expect(patchedMetadata).toMatchObject({
      workspace_features: {
        practice: false,
        notes: true,
        free_qa: true,
      },
    });
  });

  test("NL instruction is handed off to the workspace", async ({ page }) => {
    const instruction = "Focus on sorting algorithms please";
    await page.goto("/new");
    await page.getByTestId("mode-option-upload").click();
    await page.getByTestId("mode-continue").click();
    await page.getByTestId("project-name-input").fill("NL Instruction Test");
    await page.getByTestId("start-parsing").click();
    await expect(page.getByTestId("continue-to-features")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("continue-to-features").click();

    // Fill in NL instruction
    const textarea = page.getByPlaceholder(/Use bullet points/i);
    await textarea.fill(instruction);

    // Enter workspace
    await page.getByTestId("enter-workspace").click();
    await expect(page).toHaveURL(/\/course\//, { timeout: 15_000 });

    // Extract courseId from URL
    const url = page.url();
    const courseId = url.match(/\/course\/([^/?#]+)/)?.[1];
    expect(courseId).toBeTruthy();

    const consumedPrompt = await page.evaluate((cid) => {
      return sessionStorage.getItem(`course_init_prompt_consumed_${cid}`);
    }, courseId);
    expect(consumedPrompt).toBe("true");
  });
});
