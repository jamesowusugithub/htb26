// Browser test: NEW ORDERS are scheduled by the trained policy via the backend, and the simulated TAKEAWAY shows up in the animation.
//   BASE=http://127.0.0.1:5174 API=http://127.0.0.1:8020 PUPPETEER=/path/to/node_modules/puppeteer-core node tests/e2e-orders-takeaway.mjs
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
const puppeteer = createRequire(import.meta.url)(process.env.PUPPETEER || 'puppeteer-core');
const BASE = process.env.BASE || 'http://127.0.0.1:5174';
const API = process.env.API || 'http://127.0.0.1:8020';
const OUT = process.env.OUT || 'shots';
mkdirSync(OUT, { recursive: true });
const results = [];
const check = (n, ok, d = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  - ' + d : ''}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (p) => p.evaluate(() => document.body.innerText);
const click = (p, label) => p.evaluate((l) => {
  const x = [...document.querySelectorAll('button')].find((e) => e.textContent.trim().includes(l) && !e.disabled);
  if (!x) throw new Error('no enabled button: ' + l);
  x.click();
}, label);

const b = await puppeteer.launch({
  executablePath: process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: 'new', protocolTimeout: 120000,
  args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  defaultViewport: { width: 1500, height: 1000 },
});
const reqs = [];
try {
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message));
  p.on('response', (r) => { if (r.url().includes('/restaurant/trace')) reqs.push(`${r.request().method()} ${r.status()}`); });
  await p.goto(`${BASE}/?trace=rl_ppo&api=${encodeURIComponent(API)}`, { waitUntil: 'domcontentloaded' });
  await p.waitForSelector('canvas', { timeout: 60000 });
  await sleep(2500);
  let t = await text(p);
  check('recording comes from OUR backend and says the takeaway is simulated', /RL policy/.test(t) && /SIMULATED cloud fallback/.test(t));
  check('the takeaway chef exists in the kitchen (cloud-0 declared and labelled simulated)', /Cloud takeaway \(SIMULATED\)/.test(t));
  check('"New order" controls are offered when a backend is attached', /New order \(not in the trace\)/i.test(t));
  await click(p, '16x');
  await click(p, 'Rush: 6 big orders');
  await p.waitForFunction(() => /6 placed/i.test(document.body.innerText), { timeout: 90000, polling: 300 });
  check('placing orders posts to the backend and the animation reloads', reqs.filter((x) => x.startsWith('POST 200')).length >= 1, reqs.join(', '));

  const seen = { order: false, cloud: false, rl: false, cost: 0, newOrderLabel: false };
  const t0 = Date.now();
  let shot = false;
  while (Date.now() - t0 < 70000 && !(seen.order && seen.cloud)) {
    const s = await p.evaluate(() => {
      const head = document.querySelector('.decision-head')?.innerText || '';
      const body = document.body.innerText;
      const m = body.match(/Takeaway cost \(simulated\)\s*([0-9.]+)/i);
      return { head, labelled: body.includes('not in the Alibaba trace'), cost: m ? parseFloat(m[1]) : 0, rl: /RL policy \(trained\)/.test(body) };
    });
    if (/ORDER-/.test(s.head)) { seen.order = true; seen.rl = seen.rl || s.rl; }
    if (/cloud takeaway/i.test(s.head)) {
      seen.cloud = true;
      if (!shot) { await p.screenshot({ path: `${OUT}/takeaway.png` }); shot = true; }
    }
    seen.cost = Math.max(seen.cost, s.cost);
    seen.newOrderLabel = seen.newOrderLabel || s.labelled;
    await sleep(250);
  }
  check('the trained RL policy made a decision on a NEW order (ORDER-nnn, not in the trace)', seen.order && seen.rl);
  check('the UI labels it as a new order', seen.newOrderLabel);
  check('a customer was sent to the cloud takeaway ("Send to cloud takeaway" shown)', seen.cloud);
  await sleep(2500);
  t = await text(p);
  const cost = parseFloat((t.match(/Takeaway cost \(simulated\)\s*\n?\s*([0-9.]+)/i) || [])[1] || '0');
  check('takeaway cost is shown and is greater than zero', Math.max(cost, seen.cost) > 0, `$${Math.max(cost, seen.cost)}`);
  await click(p, 'Place order');
  await p.waitForFunction(() => /7 placed/i.test(document.body.innerText), { timeout: 90000, polling: 300 });
  check('a single custom order can be added after the first batch', true);
  await p.screenshot({ path: `${OUT}/orders.png` });
  check('no page errors', errs.length === 0, errs.slice(0, 2).join(' | '));
  const q = await b.newPage();
  await q.goto(`${BASE}/?trace=rl_ppo`, { waitUntil: 'domcontentloaded' });
  await q.waitForSelector('canvas', { timeout: 60000 });
  await sleep(1500);
  check('without a backend the recording is read-only (no order form)', !/New order \(not in the trace\)/i.test(await text(q)));
} catch (e) {
  check('test ran without exception', false, String(e.stack || e).slice(0, 300));
} finally {
  await b.close();
}
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
process.exit(results.every(Boolean) ? 0 : 1);
