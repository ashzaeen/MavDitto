// Headless render check for every route.
//
// `npm run build` passing only means the bundle compiled; it says nothing about
// whether the app runs. This loads each route against the served build, fails on
// any console or page error, and prints the first lines of what actually
// rendered so a blank-but-error-free screen cannot pass.
//
//   npm run preview -- --port 5178
//   node smoke.mjs

import { chromium } from 'playwright';

const base = process.env.BASE_URL ?? 'http://127.0.0.1:5178';
// Each route names something that must actually be on the page. A render that
// throws no errors but shows an empty table is still broken, and a length
// threshold alone lets that through -- it did, once.
const routes = [
  ['/', 'Home', /Migration validation, accessibility/i, () => true],
  ['/all-tools', 'All Tools', /Every capability MavDitto offers/i, () => true],
  ['/migration', 'Migration Validator', /Did your migration keep everything/i, () => true],
  ['/migration/results', 'Migrated pages', /Showing (\d+) of/, (m) => Number(m[1]) > 0],
  ['/migration/missing', 'Not migrated', /(\d+)% of old pages accounted for/, () => true],
  ['/migration/redirects', 'Redirect map', /Showing (\d+) of (\d+) redirect rules/, (m) => Number(m[2]) > 0],
  ['/migration/pages/1', 'Page detail', /The pages, side by side/i, () => true],
  ['/alt-text', 'Alt text', /Alt text generator/i, () => true],
  ['/broken-links', 'Broken links', /Broken link inspector/i, () => true],
  ['/broken-links/link/0', 'Link detail', /Nothing here yet/i, () => true],
  ['/content-writer', 'Content writer', /Content writer/i, () => true],
  ['/web-builder', 'Web builder', /Web [Bb]uilder/i, () => true],
  ['/setup', 'Setup wizard', /Set up MavDitto/i, () => true],
  ['/settings', 'Settings', /Reconfigure the brand voice/i, () => true],
];

const browser = await chromium.launch();
let failed = 0;

for (const [route, name, pattern, check] of routes) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });

  await page.goto(base + route, { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);

  const text = await page.innerText('body');
  const match = text.match(pattern);
  const contentOk = Boolean(match) && check(match);
  const ok = errors.length === 0 && text.length > 120 && contentOk;
  if (!ok) failed++;

  console.log(
    `${ok ? 'OK  ' : 'FAIL'} ${name.padEnd(14)} ${text.length} chars` +
      (match ? `  [${match[0]}]` : '  [expected content missing]')
  );
  if (errors.length) {
    for (const e of errors.slice(0, 3)) console.log(`      ${e}`);
  } else {
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
    console.log('      ' + lines.slice(2, 8).join(' | ').slice(0, 170));
  }
  await page.close();
}

await browser.close();
process.exit(failed);
