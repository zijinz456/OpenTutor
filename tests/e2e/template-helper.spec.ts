import { expect, test } from "@playwright/test";
import { selectTemplateIfShown } from "./helpers/test-utils";

const picker = '<section><h2>Choose a template</h2><button>STEM Student</button></section>';
const workspace = '<ul aria-label="Workspace blocks"><li>Notes</li></ul>';

test("selects a template and waits for workspace blocks", async ({ page }) => {
  await page.setContent(picker);
  await page.evaluate((html) => {
    document.querySelector("button")!.addEventListener("click", () => {
      document.body.innerHTML = html;
    });
  }, workspace);
  await selectTemplateIfShown(page);
  await expect(page.getByRole("list", { name: "Workspace blocks" })).toBeVisible();
});

test("accepts a saved layout that replaces the picker during the click", async ({ page }) => {
  test.setTimeout(7_000);
  await page.setContent(picker);
  await page.evaluate((html) => {
    document.querySelector("button")!.disabled = true;
    // Hydration replaces a visible picker while Playwright waits for actionability.
    setTimeout(() => { document.body.innerHTML = html; }, 200);
  }, workspace);
  await selectTemplateIfShown(page);
  await expect(page.getByRole("list", { name: "Workspace blocks" })).toBeVisible();
});

test("does not hide a real click failure while the picker remains", async ({ page }) => {
  test.setTimeout(7_000);
  await page.setContent(picker);
  await page.getByRole("button", { name: "STEM Student" }).evaluate((button: HTMLButtonElement) => {
    button.disabled = true;
  });
  await expect(selectTemplateIfShown(page)).rejects.toThrow();
  await expect(page.getByRole("heading", { name: "Choose a template" })).toBeVisible();
});
