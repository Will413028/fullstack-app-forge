import { chromium } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

const base = process.env.FORGE_TEST_ORIGIN;
if (!base || new URL(base).hostname !== '127.0.0.1') throw new Error('owned local server required');
const browser = await chromium.launch({
  executablePath: '/Users/will/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
});
const evidence = [];
try {
  for (const viewport of [{ width: 1440, height: 960 }, { width: 390, height: 844 }]) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(base, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: '回到你的工作室' }).waitFor();
    await page.getByRole('button', { name: '還沒有帳號？建立一個' }).click();
    await page.getByRole('heading', { name: '建立你的工作室' }).waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    if (overflow || errors.length) throw new Error(JSON.stringify({ viewport, overflow, errors }));
    await page.screenshot({ path: new URL(`p1a-web-${viewport.width}.png`, import.meta.url).pathname, fullPage: true });
    evidence.push({ viewport, registration_switch: true, horizontal_overflow: false, page_errors: errors });
    await page.close();
  }
  await writeFile(new URL('p1a-web-smoke.json', import.meta.url), JSON.stringify({
    scope: 'real browser login/register shell; API integration is covered separately, not mocked here',
    checks: evidence,
  }, null, 2));
  console.log(JSON.stringify(evidence));
} finally {
  await browser.close();
}
