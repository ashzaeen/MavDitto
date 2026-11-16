import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewportSize: { width: 1440, height: 1200 } });
await p.goto('http://127.0.0.1:8000/pages/1', { waitUntil: 'networkidle' });
await p.waitForTimeout(700);
await p.screenshot({ path: '../data/shot-review.png', fullPage: true });
await b.close(); console.log('ok');
