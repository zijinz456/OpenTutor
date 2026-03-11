import { chromium } from "playwright";
import { join } from "path";

const OUTPUT_DIR = join(import.meta.dirname, "..", "docs", "assets");
const BASE_URL = "http://localhost:3001";
const COURSE_ID = "f6ce4dfb-47c7-409e-b547-bf440bc968b3";

// CSS to hide Next.js dev overlays, error toasts, and dev indicators
const HIDE_DEV_CSS = `
  /* Next.js dev indicator (N logo bottom-left) */
  [data-nextjs-dialog-overlay],
  [data-nextjs-dialog],
  nextjs-portal,
  #__next-build-indicator,
  [class*="nextjs"],
  /* The circular N button at bottom-left */
  body > div:last-child:not(#__next):not([id]),
  /* Next.js error overlay "1 Issue" badge */
  [data-nextjs-toast],
  [data-nextjs-error-overlay],
  /* Generic dev tool indicators */
  [class*="dev-tool"],
  [class*="DevTool"],
  /* Sonner toast notifications (Request failed, etc.) */
  [data-sonner-toaster],
  [data-sonner-toast],
  section[aria-label*="Notifications"],
  ol[data-sonner-toaster],
  /* Next.js 15/16 dev indicator uses shadow DOM in a custom element */
  [data-next-mark],
  [data-nextjs-data],
  [data-next-hide-fouc] ~ div:not(#__next) {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
  }
`;

async function hideDevOverlays(page) {
  await page.addStyleTag({ content: HIDE_DEV_CSS });
  // Remove specific dev-only elements via JS
  await page.evaluate(() => {
    // Remove the nextjs-portal shadow DOM element (Next.js dev indicator)
    document.querySelectorAll("nextjs-portal").forEach((el) => el.remove());
    // Remove Sonner toast containers (API error toasts like "Request failed")
    document
      .querySelectorAll("[data-sonner-toaster], [data-sonner-toast], ol[data-sonner-toaster]")
      .forEach((el) => el.remove());
    // Remove any notification sections
    document.querySelectorAll("section[aria-label]").forEach((el) => {
      if (/notification/i.test(el.getAttribute("aria-label") || "")) {
        el.remove();
      }
    });
  });
  await page.waitForTimeout(200);
}

async function screenshot(page, url, name, opts = {}) {
  console.log(`📸 ${name}...`);
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(opts.wait || 2500);
  await hideDevOverlays(page);
  if (opts.action) await opts.action();
  if (opts.actionWait) await page.waitForTimeout(opts.actionWait);
  await page.screenshot({
    path: join(OUTPUT_DIR, `demo-${name}.png`),
    fullPage: opts.fullPage || false,
  });
  console.log(`   ✅ demo-${name}.png`);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });
  const page = await context.newPage();

  // 1. Dashboard
  await screenshot(page, BASE_URL, "dashboard");

  // 2. Setup / Onboarding
  await screenshot(page, `${BASE_URL}/setup`, "setup");

  // 3. Course workspace
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}`, "workspace", {
    wait: 4000,
  });

  // 4. Workspace full page
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}`, "workspace-full", {
    wait: 4000,
    fullPage: true,
  });

  // 5. Practice / quiz page
  await screenshot(
    page,
    `${BASE_URL}/course/${COURSE_ID}/practice`,
    "practice",
    { wait: 3000 }
  );

  // 6. Study plan
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}/plan`, "plan", {
    wait: 2500,
  });

  // 7. Chat drawer — open from workspace
  console.log("📸 chat...");
  await page.goto(`${BASE_URL}/course/${COURSE_ID}`, {
    waitUntil: "load",
    timeout: 15000,
  });
  await page.waitForTimeout(4000);
  await hideDevOverlays(page);
  // Click the chat FAB ("Open chat" button)
  const chatFab = page.locator('button[aria-label="Open chat"]');
  if ((await chatFab.count()) > 0) {
    await chatFab.first().click();
    await page.waitForTimeout(2500);
    await hideDevOverlays(page);
  }
  await page.screenshot({
    path: join(OUTPUT_DIR, "demo-chat.png"),
    fullPage: false,
  });
  console.log("   ✅ demo-chat.png");

  await browser.close();
  console.log(`\n✅ All screenshots saved to ${OUTPUT_DIR}/demo-*.png`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
