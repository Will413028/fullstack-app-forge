import { chromium, expect as baseExpect } from '@playwright/test';
import { existsSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';

const origin = process.env.FORGE_TEST_ORIGIN;
if (!origin || new URL(origin).hostname !== '127.0.0.1') throw new Error('owned local origin required');
const cached = '/Users/will/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const expect = baseExpect.configure({ timeout: 60000 });
const browser = await chromium.launch(existsSync(cached) ? { executablePath: cached } : {});
const identity = 'browser-' + randomUUID().slice(0, 12);
const password = 'isolated-browser-fixture';
let page;
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  page = await context.newPage();
  page.setDefaultTimeout(60000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(origin, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '還沒有帳號？建立一個' }).click();
  await page.getByLabel('帳號', { exact: true }).fill(identity);
  await page.getByLabel('密碼', { exact: true }).fill(password);
  await page.getByRole('button', { name: '建立帳號 →' }).click();
  await expect(page.getByRole('heading', { name: '把下一個想法做出來。' })).toBeVisible();
  await page.getByLabel('應用名稱', { exact: true }).fill('Browser walking skeleton');
  await page.getByLabel('簡短描述').fill('Real browser, control API and isolated PostgreSQL');
  await page.getByRole('button', { name: '開始建立 →' }).click();
  await expect(page.getByRole('heading', { name: 'Browser walking skeleton', exact: true })).toBeVisible();
  const appId = new URL(page.url()).pathname.split('/').at(-1);
  await page.getByLabel('應用需求', { exact: true }).fill('建立待辦清單，先驗證任務生命週期。');
  await page.getByRole('button', { name: '生成版本 ↑' }).click();
  await expect(page.getByText('run.queued', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '取消這次任務' }).click();
  await expect(page.getByText('已取消', { exact: true })).toBeVisible();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByText('已取消', { exact: true })).toBeVisible();
  const history = await (await page.request.get(`${origin}/v1/apps/${appId}/runs`)).json();
  if (history.length !== 1 || history[0].status !== 'cancelled') throw new Error('refresh changed durable run');

  const oversized = await page.request.post(`${origin}/v1/auth/register`, {
    headers: { origin, 'content-type': 'application/json' }, data: 'x'.repeat(65537),
  });
  if (oversized.status() !== 413) throw new Error('proxy request limit missing');
  const other = await browser.newContext();
  const second = await other.request.post(`${origin}/v1/auth/register`, {
    headers: { origin }, data: { username: 'other-' + randomUUID().slice(0, 12), password },
  });
  if (second.status() !== 201) throw new Error('second owner registration failed');
  if ((await other.request.get(`${origin}/v1/apps/${appId}`)).status() !== 404) throw new Error('owner boundary missing');
  await other.close();

  await page.locator('summary').filter({ hasText: '應用設定' }).click();
  await page.getByLabel('名稱', { exact: true }).fill('Renamed from browser');
  await page.getByRole('button', { name: '儲存設定' }).click();
  await expect(page.getByRole('heading', { name: 'Renamed from browser', exact: true })).toBeVisible();
  await page.screenshot({ path: new URL('p1a-browser-flow.png', import.meta.url).pathname, fullPage: true });
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '刪除應用', exact: true }).click();
  await expect(page.getByRole('heading', { name: '把下一個想法做出來。' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Renamed from browser', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '登出', exact: true }).click();
  await expect(page.getByRole('heading', { name: '回到你的工作室' })).toBeVisible();
  await page.getByLabel('帳號', { exact: true }).fill(identity);
  await page.getByLabel('密碼', { exact: true }).fill(password);
  await page.getByRole('button', { name: '登入工作室 →' }).click();
  await expect(page.getByRole('heading', { name: '把下一個想法做出來。' })).toBeVisible();
  if (errors.length) throw new Error('browser page errors: ' + errors.join('; '));
  const result = { app_id: appId, run_id: history[0].id, register: true, app_create: true,
    queued_event: true, cancel: true, replay_did_not_create_run: true, app_update: true,
    tombstone_delete: true, logout_login: true, owner_isolation: true, proxy_body_limit: true,
    scope: 'platform browser/API/DB only; no generated app or model completion' };
  await writeFile(new URL('p1a-browser-flow.json', import.meta.url), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  if (page) await page.screenshot({ path: new URL('p1a-browser-flow-failed.png', import.meta.url).pathname, fullPage: true }).catch(() => {});
  throw error;
} finally {
  await browser.close();
}
