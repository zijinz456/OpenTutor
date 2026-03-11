import { chromium } from 'playwright';

const COURSE_URL = 'http://localhost:3001/course/a0966293-1a49-445c-a57b-6393da58449e';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(COURSE_URL, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2000);
  await page.evaluate(() => document.querySelectorAll('nextjs-portal').forEach(el => el.remove()));

  // Find and click the Maximize2 button in the Notes block header
  const clicked = await page.evaluate(() => {
    const blocks = document.querySelectorAll('[role="region"]');
    for (const block of blocks) {
      if (block.getAttribute('aria-label') !== 'Notes') continue;
      const header = block.querySelector('.flex.items-center.gap-2');
      if (!header) continue;
      const btns = header.querySelectorAll('button');
      for (const btn of btns) {
        const label = btn.getAttribute('aria-label') || '';
        if (label.toLowerCase().includes('full') || label.toLowerCase().includes('expand') || label.toLowerCase().includes('open')) {
          btn.click();
          return 'clicked: ' + label;
        }
      }
      return 'buttons found: ' + [...btns].map(b => b.getAttribute('aria-label') || b.textContent?.trim() || '(no label)').join(', ');
    }
    return 'Notes block not found';
  });
  console.log('Click result:', clicked);

  await page.waitForTimeout(1000);

  // Check what panels are visible
  const panels = await page.evaluate(() => {
    const els = document.querySelectorAll('[role="complementary"], [role="dialog"], [class*="drawer"], [class*="Drawer"]');
    return [...els].map(d => {
      const style = window.getComputedStyle(d);
      return {
        role: d.getAttribute('role'),
        label: d.getAttribute('aria-label'),
        display: style.display,
        visibility: style.visibility,
        transform: style.transform,
        width: d.offsetWidth,
        height: d.offsetHeight,
      };
    });
  });
  console.log('Panels:', JSON.stringify(panels, null, 2));

  await page.screenshot({ path: 'screenshots/04-notes-drawer-clean.png', fullPage: true });
  console.log('Screenshot saved: 04-notes-drawer-clean.png');

  await browser.close();
})();
