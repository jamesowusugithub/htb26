// Render the restaurant animation playing a REAL-trace recording and save screenshots.
//   node tests/e2e/restaurant-shoot.mjs [trace=sjf_hint] [seconds=40]
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { serveDist, launch, sleep, root } from './harness.mjs';
const trace = process.argv[2] || 'sjf_hint', secs = Number(process.argv[3] || 40);
const out = path.resolve(root, '../analysis/proof/restaurant'); mkdirSync(out, { recursive: true });
const { server, port } = await serveDist(0, path.resolve(root, '../restaurant/dist'));
const browser = await launch();
try {
  const page = await browser.newPage(); const logs = [];
  page.on('console', m => logs.push(`${m.type()}: ${m.text()}`)); page.on('pageerror', e => logs.push(`pageerror: ${e.message}`));
  await page.setViewport({ width: 1500, height: 950 });
  await page.goto(`http://127.0.0.1:${port}/?trace=${trace}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('[data-testid="source-badge"]') && document.querySelector('canvas'), { timeout: 60000 });
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '8x')?.click());
  for (const [i, t] of [[1, 6], [2, 14], [3, secs]]) { await sleep((t - (i === 1 ? 0 : [0, 6, 14][i - 1])) * 1000); await page.screenshot({ path: path.join(out, `${trace}-${i}.png`) }); }
  const info = await page.evaluate(() => ({ badge: document.querySelector('[data-testid="source-badge"]')?.textContent, sched: document.querySelector('[data-testid="scheduler-label"]')?.textContent,
    banner: document.querySelector('[data-testid="trace-banner"]')?.textContent?.slice(0, 160), tiles: [...document.querySelectorAll('.tile')].map(t => t.textContent) }));
  console.log(JSON.stringify(info, null, 1)); console.log('errors:', logs.filter(l => /error/i.test(l)).slice(0, 4));
} finally { await browser.close(); server.close(); }
