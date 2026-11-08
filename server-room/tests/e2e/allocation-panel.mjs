// "How jobs are placed" must tell the truth: every decision it lists (job, GPUs, priority, board, wait) equals the backend's own start/arrive events.
//   node tests/e2e/allocation-panel.mjs [--api=http://127.0.0.1:8020]
import { serveDist, launch, openRoom, sleep } from './harness.mjs';
const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `--${k}=${d}`).split('=').slice(1).join('=');
const base = arg('api', 'http://127.0.0.1:8020');
const results = []; const check = (n, ok, d = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  - ' + d : ''}`); };
const { server, port } = await serveDist(); const browser = await launch();
try {
  const { page } = await openRoom(browser, `http://127.0.0.1:${port}/index.html?api=${encodeURIComponent(base)}&preset=heldout_demo&policy=rl_ppo`);
  await page.waitForFunction(() => (window.gpuLab.engine.snapshot().allocations || []).length >= 6, { timeout: 180000, polling: 500 });
  const s = await page.evaluate(() => { const e = window.gpuLab.engine, sn = e.snapshot(); return { runId: e.runId, allocs: sn.allocations.slice(), text: document.querySelector('.alloc-section')?.innerText || '', policy: sn.policy }; });
  check('the panel is on screen and says which policy decides', /How jobs are placed/i.test(s.text) && /trained RL policy/i.test(s.text));
  const ev = (await (await fetch(`${base}/runs/${s.runId}/events?types=start,arrive`)).text()).split('\n').filter(Boolean).map(l => JSON.parse(l));
  const starts = new Map(), arrive = new Map();
  for (const e of ev) { if (e.type === 'start') (starts.get(e.job) || starts.set(e.job, []).get(e.job)).push(e); else arrive.set(e.job, e.t); }
  const bad = s.allocs.filter(a => !(starts.get(a.job) || []).some(e => e.t === a.t && e.board === a.board && e.gpus === a.gpus && e.priority === a.priority));
  check('every listed decision equals a backend start event (job, time, board, GPUs, priority)', s.allocs.length >= 6 && bad.length === 0, `${s.allocs.length} decisions, ${bad.length} mismatches`);
  const badWait = s.allocs.filter(a => a.waitS != null && Math.abs(a.waitS - (a.t - arrive.get(a.job))) > 1);
  check('the waiting time shown equals start minus arrival from the backend', badWait.length === 0, `${badWait.length} mismatches`);
  check('boards named in the text exist (1-24)', s.allocs.every(a => a.board == null || (a.board >= 0 && a.board < 24)));
  check('header counts boards, not jobs', /Boards busy/i.test(await page.evaluate(() => document.querySelector('.activity')?.innerText || '')));
} catch (e) { check('test ran without exception', false, String(e.stack || e).slice(0, 300)); } finally { await browser.close(); server.close(); }
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`); process.exit(results.every(Boolean) ? 0 : 1);
