// End-to-end: type two URLs into the GUI and watch a real run finish.
//
// The point of the form is that nobody has to touch a terminal, so the check
// drives it the way a person would — fill the fields, click the button, wait
// for the dashboard to show the run's own results.
//
//   python -m src.server --results data/run --port 8012
//   node run-e2e.mjs

import { chromium } from 'playwright';

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8012';
const OLD = process.env.OLD_URL ?? 'https://ashzaeen.super.site/';
const NEW = process.env.NEW_URL ?? 'https://www.ashzaeen.com/';

const browser = await chromium.launch();
const page = await browser.newPage({ viewportSize: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text());
});

await page.goto(base, { waitUntil: 'networkidle' });

// Open the form if it is collapsed.
if (!(await page.locator('input[placeholder="https://old.example.edu"]').isVisible())) {
  await page.getByRole('button', { name: /Compare two sites/ }).click();
}

await page.fill('input[placeholder="https://old.example.edu"]', OLD);
await page.fill('input[placeholder="https://example.edu"]', NEW);

// Keep it small: this is checking the wiring, not the crawler.
await page.getByRole('button', { name: /^Options$/ }).click();
await page.fill('input[type="number"] >> nth=0', '25');
await page.fill('input[type="number"] >> nth=1', '3');
// robots.txt is off by default now, so there is nothing to tick.

console.log(`starting a run: ${OLD} -> ${NEW}`);
await page.getByRole('button', { name: /Run comparison/ }).click();

const started = Date.now();
let lastStatus = '';
let finished = false;

while (Date.now() - started < 8 * 60 * 1000) {
  const status = await page.locator('.run-status').first().textContent().catch(() => null);
  if (status && status !== lastStatus) {
    lastStatus = status;
    console.log(`  ${status.replace(/\s+/g, ' ').trim()}`);
  }
  if (await page.locator('.run-done').count()) {
    finished = true;
    break;
  }
  if (await page.locator('.run-error').count()) {
    const text = await page.locator('.run-error').first().textContent();
    console.log(`  ERROR: ${text}`);
    break;
  }
  await page.waitForTimeout(1500);
}

if (finished) {
  console.log('\n' + (await page.locator('.run-done').first().innerText()).trim());
  // The table must show the run's own results, not the previous folder's.
  const footnote = await page.locator('.footnote').first().innerText();
  console.log(footnote.trim());
}

console.log(`\nconsole errors: ${errors.length}`);
for (const e of errors.slice(0, 3)) console.log(`  ${e}`);

await page.screenshot({ path: '../data/shot-run.png', fullPage: true });
await browser.close();
process.exit(finished && errors.length === 0 ? 0 : 1);
