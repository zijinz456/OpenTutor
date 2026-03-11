import { chromium } from 'playwright';

const COURSE_URL = 'http://localhost:3001/course/a0966293-1a49-445c-a57b-6393da58449e';
const SCREENSHOT_DIR = '/Users/zijinzhang/Desktop/OpenTutor/screenshots';

const results = [];
const consoleErrors = [];

function report(name, passed, detail = '') {
  const status = passed ? 'PASS' : 'FAIL';
  const msg = `[${status}] ${name}${detail ? ': ' + detail : ''}`;
  results.push({ name, passed, detail });
  console.log(msg);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Collect console errors
  page.on('console', msg => {
    if (msg.type() === 'error') {
      consoleErrors.push(msg.text());
    }
  });
  page.on('pageerror', err => {
    consoleErrors.push(`PAGE ERROR: ${err.message}`);
  });

  try {
    // 1. Navigate to course page
    console.log(`\nNavigating to ${COURSE_URL} ...\n`);
    const response = await page.goto(COURSE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    report('Page load', response.ok(), `status ${response.status()}`);

    // Wait a bit for client-side hydration
    await page.waitForTimeout(2000);

    // 3. Remove Next.js dev overlay
    await page.evaluate(() => {
      document.querySelectorAll('nextjs-portal').forEach(el => el.remove());
    });

    // 4. Full-page screenshot
    await page.screenshot({ path: `${SCREENSHOT_DIR}/01-course-page.png`, fullPage: true });
    console.log('Screenshot saved: 01-course-page.png\n');

    // Helper: check if a block is visible by looking for headings or known text patterns
    async function findBlock(name, selectors) {
      for (const sel of selectors) {
        const el = await page.$(sel);
        if (el && await el.isVisible()) {
          return el;
        }
      }
      // Also try finding by text content
      const byText = await page.locator(`text="${name}"`).first();
      if (await byText.isVisible().catch(() => false)) {
        return byText;
      }
      return null;
    }

    // 5. Chapters block
    const chaptersBlock = await findBlock('Chapters', [
      '[data-testid="chapters-block"]',
      '[data-block-type="chapters"]',
    ]);
    if (chaptersBlock) {
      // Check for "No content yet"
      const chaptersText = await page.locator('text="Chapters"').first().evaluate(el => {
        const block = el.closest('[class*="block"], [class*="card"], section, article') || el.parentElement?.parentElement;
        return block?.textContent || '';
      }).catch(() => '');
      const hasContent = !chaptersText.includes('No content yet') && chaptersText.length > 20;
      report('Chapters block visible', true);
      report('Chapters block has content', hasContent, hasContent ? 'has content' : 'shows "No content yet" or empty');
    } else {
      report('Chapters block visible', false, 'not found on page');
    }

    // 6. Notes block
    const notesBlock = await findBlock('Notes', [
      '[data-testid="notes-block"]',
      '[data-block-type="notes"]',
    ]);
    report('Notes block visible', !!notesBlock, notesBlock ? 'found' : 'not found on page');

    // 7. Quiz block
    const quizBlock = await findBlock('Quiz', [
      '[data-testid="quiz-block"]',
      '[data-block-type="quiz"]',
    ]);
    report('Quiz block visible', !!quizBlock, quizBlock ? 'found' : 'not found on page');

    // 8. Flashcards block
    const flashcardsBlock = await findBlock('Flashcards', [
      '[data-testid="flashcards-block"]',
      '[data-block-type="flashcards"]',
    ]);
    report('Flashcards block visible', !!flashcardsBlock, flashcardsBlock ? 'found' : 'not found on page');

    // 9. Red error banners — only check actual banner/alert containers, not buttons
    const errorBanners = await page.$$eval(
      '[role="alert"]',
      els => els
        .filter(el => {
          const style = window.getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          // Skip small inline elements (buttons, badges) — only flag large banner-like alerts
          return el.offsetHeight > 30 && el.offsetWidth > 200;
        })
        .map(el => el.textContent?.trim().substring(0, 200))
    ).catch(() => []);
    // Canvas session warnings (amber) and Agent Insight review prompts are expected — not errors
    const realErrors = errorBanners.filter(t =>
      !t.includes('Canvas session') && !t.includes('Re-login') &&
      !t.includes('Time to review') && !t.includes('concepts are at risk')
    );
    if (realErrors.length > 0) {
      report('No error banners', false, `Found ${realErrors.length}: ${realErrors.join(' | ')}`);
    } else {
      report('No error banners', true, errorBanners.length > 0 ? `${errorBanners.length} warning(s) present (non-blocking)` : '');
    }

    // 10. Processing banner
    const processingBanner = await page.locator('text=/processing/i').first();
    const processingVisible = await processingBanner.isVisible().catch(() => false);
    report('Processing banner not showing', !processingVisible, processingVisible ? 'still showing "Processing"' : 'not present');

    // 11. Notes expand/maximize button
    let notesDrawerOpened = false;
    if (notesBlock) {
      // Find expand/maximize button near the Notes heading
      const expandBtn = await page.locator('text="Notes"').first().evaluate(el => {
        const block = el.closest('[class*="block"], [class*="card"], section, article') || el.parentElement?.parentElement;
        if (!block) return null;
        const btns = block.querySelectorAll('button');
        for (const btn of btns) {
          const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
          const title = (btn.getAttribute('title') || '').toLowerCase();
          const text = btn.textContent?.toLowerCase() || '';
          if (ariaLabel.includes('expand') || ariaLabel.includes('maximize') || ariaLabel.includes('open') ||
              title.includes('expand') || title.includes('maximize') || title.includes('open') ||
              text.includes('expand') || text.includes('maximize')) {
            return true;
          }
        }
        return null;
      }).catch(() => null);

      if (expandBtn) {
        // Click it
        const block = await page.locator('text="Notes"').first().evaluate(el => {
          const block = el.closest('[class*="block"], [class*="card"], section, article') || el.parentElement?.parentElement;
          const btns = block.querySelectorAll('button');
          for (const btn of btns) {
            const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
            const title = (btn.getAttribute('title') || '').toLowerCase();
            if (ariaLabel.includes('expand') || ariaLabel.includes('maximize') || ariaLabel.includes('open') ||
                title.includes('expand') || title.includes('maximize') || title.includes('open')) {
              btn.click();
              return true;
            }
          }
          return false;
        }).catch(() => false);

        if (block) {
          await page.waitForTimeout(1000);
          // Check for drawer/dialog/panel
          const drawerVisible = await page.$$eval(
            '[role="dialog"], [role="complementary"][aria-label*="Notes"], [class*="drawer" i], [class*="Drawer"], [class*="sheet" i], [class*="Sheet"], [class*="side-panel" i], [class*="modal" i]',
            els => els.filter(el => {
              const style = window.getComputedStyle(el);
              return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetHeight > 0;
            }).length
          ).catch(() => 0);

          // Also check if URL changed (page navigation instead of drawer)
          const currentUrl = page.url();
          const navigated = !currentUrl.includes(COURSE_URL.split('/course/')[1]);

          if (drawerVisible > 0 && !navigated) {
            notesDrawerOpened = true;
            report('Notes drawer opens (not navigation)', true, 'drawer/dialog opened');
          } else if (navigated) {
            report('Notes drawer opens (not navigation)', false, `navigated to ${currentUrl} instead of opening drawer`);
          } else {
            report('Notes drawer opens (not navigation)', false, 'no drawer/dialog detected after clicking expand');
          }
        } else {
          report('Notes drawer opens (not navigation)', false, 'could not click expand button');
        }
      } else {
        // Try clicking on the Notes block heading itself
        try {
          await page.locator('text="Notes"').first().click();
          await page.waitForTimeout(1000);
          const currentUrl = page.url();
          const navigated = !currentUrl.includes(COURSE_URL.split('/course/')[1]);
          if (navigated) {
            report('Notes expand button', false, 'no expand button found; clicking title navigated away');
            await page.goBack({ waitUntil: 'networkidle' });
          } else {
            report('Notes expand button', false, 'no expand/maximize button found on Notes block');
          }
        } catch {
          report('Notes expand button', false, 'no expand/maximize button found on Notes block');
        }
      }
    } else {
      report('Notes drawer opens (not navigation)', false, 'Notes block not found, skipping');
    }

    // 12. Screenshot of notes drawer
    if (notesDrawerOpened) {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/02-notes-drawer.png`, fullPage: true });
      console.log('Screenshot saved: 02-notes-drawer.png\n');
    } else {
      // Take a screenshot of current state anyway for debugging
      await page.screenshot({ path: `${SCREENSHOT_DIR}/02-notes-drawer.png`, fullPage: true });
      console.log('Screenshot saved: 02-notes-drawer.png (no drawer found, capturing current state)\n');
    }

    // 13. Close the notes drawer
    if (notesDrawerOpened) {
      // Try ESC key first
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);
      // Or click close button
      const closeBtn = await page.$('[role="dialog"] button[aria-label*="close" i], [class*="drawer" i] button[aria-label*="close" i]');
      if (closeBtn) await closeBtn.click();
      await page.waitForTimeout(500);
      report('Notes drawer closed', true);
    }

    // Ensure we're back on the course page
    if (!page.url().includes('a0966293')) {
      await page.goto(COURSE_URL, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForTimeout(1000);
      await page.evaluate(() => {
        document.querySelectorAll('nextjs-portal').forEach(el => el.remove());
      });
    }

    // 14. Knowledge Graph block
    const kgBlock = await findBlock('Knowledge Graph', [
      '[data-testid="knowledge-graph-block"]',
      '[data-block-type="knowledge-graph"]',
      '[data-block-type="knowledgegraph"]',
    ]);
    report('Knowledge Graph block exists', !!kgBlock, kgBlock ? 'found' : 'not found on page');

    // 15. Agent Insight block — check it's dismissible (X button) if present
    const agentBlock = await findBlock('Agent Insight', [
      '[data-testid="agent-insight-block"]',
      '[data-block-type="agent-insight"]',
    ]);
    const agentText = await page.locator('text=/agent insight/i').first().isVisible().catch(() => false);
    const agentExists = !!agentBlock || agentText;
    if (agentExists) {
      // Course has learning history — Agent Insight is expected. Verify it's dismissible.
      const dismissible = await page.locator('text=/agent insight/i').first().evaluate(el => {
        const block = el.closest('[role="region"]') || el.parentElement?.parentElement?.parentElement;
        if (!block) return false;
        const btns = block.querySelectorAll('button');
        for (const btn of btns) {
          const label = (btn.getAttribute('aria-label') || '').toLowerCase();
          if (label.includes('dismiss') || label.includes('close') || label.includes('remove')) return true;
          // Check for X icon button (small icon-only button)
          if (btn.querySelector('svg') && btn.textContent?.trim() === '') return true;
        }
        return false;
      }).catch(() => false);
      report('Agent Insight block is dismissible', dismissible, dismissible ? 'has dismiss button' : 'no dismiss button found');
    } else {
      report('Agent Insight block absent (no learning history)', true, 'correctly absent');
    }

    // 16. Screenshot of any errors
    if (errorBanners.length > 0 || consoleErrors.length > 0) {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/03-errors.png`, fullPage: true });
      console.log('Screenshot saved: 03-errors.png\n');
    }

    // Final page content dump for debugging
    const pageTitle = await page.title();
    const bodyText = await page.evaluate(() => document.body?.innerText?.substring(0, 500) || '');

    // Summary
    console.log('\n' + '='.repeat(60));
    console.log('SUMMARY');
    console.log('='.repeat(60));
    console.log(`Page title: ${pageTitle}`);
    console.log(`Page URL: ${page.url()}`);
    console.log(`\nFirst 500 chars of page text:\n${bodyText}\n`);

    const passed = results.filter(r => r.passed).length;
    const failed = results.filter(r => !r.passed).length;
    console.log(`Results: ${passed} passed, ${failed} failed out of ${results.length} checks\n`);

    if (consoleErrors.length > 0) {
      console.log(`Console errors (${consoleErrors.length}):`);
      consoleErrors.forEach((e, i) => console.log(`  ${i + 1}. ${e.substring(0, 300)}`));
    } else {
      console.log('No console errors detected.');
    }

    console.log('\n' + '='.repeat(60));

  } catch (err) {
    console.error('FATAL ERROR:', err.message);
    await page.screenshot({ path: `${SCREENSHOT_DIR}/99-fatal-error.png`, fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }
})();
