/**
 * Playwright script to capture demo screenshots for README.
 * Usage: PLAYWRIGHT_USE_EXISTING_SERVER=1 npx playwright test take-screenshots
 */
import { test } from "@playwright/test";
import path from "path";

const OUT = path.resolve(__dirname, "../../docs/assets");

test.use({
  viewport: { width: 1440, height: 900 },
  colorScheme: "dark",
});

test("capture course workspace screenshot", async ({ page }) => {
  // Get courses from API
  const apiBase = "http://127.0.0.1:8000/api";
  const res = await page.request.get(`${apiBase}/courses/`);
  const courses = await res.json();

  if (courses.length === 0) {
    test.skip(true, "No courses available");
    return;
  }

  await page.goto(`/course/${courses[0].id}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);

  // Dismiss offline banner if visible
  const offlineBanner = page.locator('text=You are offline');
  if (await offlineBanner.isVisible({ timeout: 1000 }).catch(() => false)) {
    await offlineBanner.evaluate(el => {
      const banner = el.closest('[class*="bg-"]');
      if (banner) (banner as HTMLElement).style.display = 'none';
    });
  }

  // If template selector is shown, click STEM Student
  const stemCard = page.locator('text=STEM Student').first();
  if (await stemCard.isVisible({ timeout: 1000 }).catch(() => false)) {
    await stemCard.click();
    await page.waitForTimeout(3000);
  }

  // Wait for workspace blocks to render
  await page.waitForTimeout(2000);

  // Hide offline banner again after navigation
  await page.evaluate(() => {
    const banners = document.querySelectorAll('[class*="offline"], [class*="bg-red"], [class*="bg-destructive"]');
    banners.forEach(b => (b as HTMLElement).style.display = 'none');
  });

  await page.screenshot({
    path: path.join(OUT, "screenshot-workspace.png"),
    fullPage: false,
  });
});

test("capture dashboard screenshot", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.waitForTimeout(2000);

  // Hide offline banner
  await page.evaluate(() => {
    const banners = document.querySelectorAll('[class*="offline"], [class*="bg-red"], [class*="bg-destructive"]');
    banners.forEach(b => (b as HTMLElement).style.display = 'none');
  });

  await page.screenshot({
    path: path.join(OUT, "screenshot-dashboard.png"),
    fullPage: false,
  });
});

test("capture setup page screenshot", async ({ page }) => {
  await page.goto("/setup", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);

  // Hide offline banner
  await page.evaluate(() => {
    const banners = document.querySelectorAll('[class*="offline"], [class*="bg-red"], [class*="bg-destructive"]');
    banners.forEach(b => (b as HTMLElement).style.display = 'none');
  });

  await page.screenshot({
    path: path.join(OUT, "screenshot-setup.png"),
    fullPage: false,
  });
});
