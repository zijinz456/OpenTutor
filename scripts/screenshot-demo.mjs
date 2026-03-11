import { chromium } from "playwright";
import { join } from "path";

const OUTPUT_DIR = join(import.meta.dirname, "..", "docs", "assets");
const BASE_URL = "http://localhost:3001";
// Python Basics course — has actual content, blocks, and template selected
const COURSE_ID = "f6ce4dfb-47c7-409e-b547-bf440bc968b3";

async function screenshot(page, url, name, opts = {}) {
  console.log(`📸 ${name}...`);
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(opts.wait || 2500);
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

  // 1. Dashboard — the home page with course list
  await screenshot(page, BASE_URL, "dashboard");

  // 2. Setup / Onboarding — upload step
  await screenshot(page, `${BASE_URL}/setup`, "setup");

  // 3. Course workspace — block layout (Python Basics has a template)
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}`, "workspace", {
    wait: 4000,
  });

  // 4. Workspace full page scroll
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}`, "workspace-full", {
    wait: 4000,
    fullPage: true,
  });

  // 5. Notes page
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}/notes`, "notes", {
    wait: 3000,
  });

  // 6. Practice / quiz page
  await screenshot(
    page,
    `${BASE_URL}/course/${COURSE_ID}/practice`,
    "practice",
    { wait: 3000 }
  );

  // 7. Knowledge graph
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}/graph`, "graph", {
    wait: 3500,
  });

  // 8. Study plan page
  await screenshot(page, `${BASE_URL}/course/${COURSE_ID}/plan`, "plan", {
    wait: 2500,
  });

  // 9. Course profile / analytics
  await screenshot(
    page,
    `${BASE_URL}/course/${COURSE_ID}/profile`,
    "profile",
    { wait: 2500 }
  );

  // 10. Chat drawer — open from workspace
  console.log("📸 chat...");
  await page.goto(`${BASE_URL}/course/${COURSE_ID}`, {
    waitUntil: "load",
    timeout: 15000,
  });
  await page.waitForTimeout(3500);
  // Look for the chat FAB button (bottom right corner)
  const chatSelectors = [
    'button[aria-label*="chat" i]',
    'button[aria-label*="Chat" i]',
    '[data-testid="chat-trigger"]',
    // FAB style button at bottom-right
    'button.fixed',
    'button:has(svg)',
  ];
  for (const sel of chatSelectors) {
    const els = page.locator(sel);
    const count = await els.count();
    if (count > 0) {
      // Try the last one (likely the FAB at bottom-right)
      const el = els.last();
      const box = await el.boundingBox();
      if (box && box.x > 1200 && box.y > 700) {
        console.log(`   Found chat FAB with selector: ${sel}`);
        await el.click();
        await page.waitForTimeout(2000);
        break;
      }
    }
  }
  await page.screenshot({
    path: join(OUTPUT_DIR, "demo-chat.png"),
    fullPage: false,
  });
  console.log("   ✅ demo-chat.png");

  // 11. Global analytics page
  await screenshot(page, `${BASE_URL}/analytics`, "analytics", {
    wait: 2500,
  });

  // 12. Settings page
  await screenshot(page, `${BASE_URL}/settings`, "settings", {
    wait: 2000,
  });

  await browser.close();
  console.log(`\n✅ All screenshots saved to ${OUTPUT_DIR}/demo-*.png`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
