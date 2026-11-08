// The demand-forecast panel shows what the backend sent: forecast values equal meta.demand_forecast, "got" values equal arrivals, honest footnote present.
//   node tests/e2e/forecast-panel.mjs [--api=http://127.0.0.1:8010] [--preset=heldout_demo]
import path from 'node:path';
import { mkdirSync } from 'node:fs';
import { serveDist, launch, openRoom, sleep, root } from './harness.mjs';
const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `--${k}=${d}`).split('=').slice(1).join('=');
const base = arg('api', 'http://127.0.0.1:8010'), preset = arg('preset', 'heldout_demo'), policy = arg('policy', 'rl_ppo');
const out = path.resolve(root, '..', 'analysis/visualization/integration'); mkdirSync(out, { recursive: true });
const results = []; const check = (n, ok, d = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  - ' + d : ''}`); };
const { server, port } = await serveDist(); const browser = await launch();
try {
  const { page } = await openRoom(browser, `http://127.0.0.1:${port}/index.html?api=${encodeURIComponent(base)}&preset=${preset}&policy=${policy}`);
  await page.waitForFunction(() => document.querySelector('.gpu-ui').dataset.status === 'ready', { timeout: 90000 });
  const d = await page.evaluate(() => window.gpuLab.engine.meta.demand_forecast);
  check('the feed carries a demand forecast for this window', d && d.available, d && d.method ? 'method: ' + d.method.slice(0, 50) : JSON.stringify(d));
  check('held-out window (not flattered by training days)', d && d.in_training_period === false);
  await page.evaluate(() => window.gpuLab.engine.seek?.(3 * 3600));
  await page.waitForFunction(() => document.querySelector('.forecast-table'), { timeout: 60000 }).catch(() => {});
  await sleep(1500);
  const panel = await page.evaluate(() => ({ text: document.querySelector('.demand-section')?.innerText || '', rows: [...document.querySelectorAll('.forecast-table tbody tr')].map(r => [...r.children].map(c => c.innerText)),
    t: window.gpuLab.engine.snapshot().time }));
  check('panel is visible with a heading', /demand forecast/i.test(panel.text));
  check('one row per pool (6)', panel.rows.length === 6, String(panel.rows.length));
  const now = [...d.series].filter(e => e.t <= panel.t).pop();
  const a100 = panel.rows.find(r => /a100/i.test(r[0]));
  check('expected value shown equals the backend number', now && a100 && Number(a100[1]) === Math.round(now.pools.a100.next_gpus * 10) / 10, `${a100 && a100[1]} vs ${now && now.pools.a100.next_gpus}`);
  const done = [...d.series].filter(e => e.t + d.horizon_s <= panel.t).pop();
  const got = done && a100 && a100[3].split('→')[1];
  check('"said → got" shows realised arrivals from the backend', !done || (got && Math.abs(Number(got) - done.pools.a100.realised_gpus) < 0.06), a100 && a100[3]);
  check('honest footnote: little skill on A10 and spikes not anticipated', /little skill on the A10/i.test(panel.text) && /spikes/i.test(panel.text));
  await page.evaluate(() => document.querySelector('.demand-section').scrollIntoView({ block: 'center' })); await sleep(400);
  await page.screenshot({ path: path.join(out, 'forecast-panel.png') });
} catch (e) { check('ran without exception', false, String(e.stack || e).slice(0, 300)); } finally { await browser.close(); server.close(); }
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`); process.exit(results.every(Boolean) ? 0 : 1);
