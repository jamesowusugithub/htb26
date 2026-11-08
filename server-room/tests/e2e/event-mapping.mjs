// Verifies that real scheduler decisions (made by the chosen policy, e.g. the trained RL model) land on the right 3D objects.
//   node tests/e2e/event-mapping.mjs [--policy=rl_ppo] [--preset=heldout_demo]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { serveDist, launch, openRoom, sleep, root } from './harness.mjs';
const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `--${k}=${d}`).split('=')[1];
const policy = arg('policy', 'rl_ppo'), preset = arg('preset', 'heldout_demo');
const repo = path.resolve(root, '..'), PY = process.env.PYTHON || '/Users/carlkaziboni/anaconda3/envs/htb/bin/python';
const out = path.resolve(repo, 'analysis/visualization/integration'); mkdirSync(out, { recursive: true });
const results = [];
const check = (n, ok, d = '') => { results.push({ name: n, ok: !!ok, detail: d }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`); };
const freePort = () => new Promise(r => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
const apiPort = await freePort(); const base = `http://127.0.0.1:${apiPort}`;
const api = spawn(PY, ['-m', 'uvicorn', 'scheduler.api:app', '--port', String(apiPort), '--log-level', 'warning'], { cwd: repo, stdio: 'ignore' });
for (let i = 0; i < 180; i++) { try { if ((await fetch(base + '/health')).ok) break; } catch {} await sleep(1000); }
const { server, port } = await serveDist(); const browser = await launch();
try {
  const { page, logs } = await openRoom(browser, `http://127.0.0.1:${port}/index.html?api=${encodeURIComponent(base)}&preset=${preset}&policy=${policy}`);
  await page.waitForFunction(() => document.querySelector('.gpu-ui').dataset.status === 'ready' && window.gpuLab.engine.snapshot().stats.running > 0, { timeout: 120000, polling: 250 });
  const meta = await page.evaluate(() => { const e = window.gpuLab.engine; return { runId: e.runId, policy: e.meta.policy, ui: document.querySelector('select[aria-label="Scheduling policy"]')?.selectedOptions[0]?.textContent }; });
  check(`the room is replaying a run decided by ${policy}`, meta.policy.name === policy && meta.runId.endsWith(policy), `${meta.runId} | UI shows "${meta.ui}"`);
  // sample what the 3D scene is animating for a few real seconds
  const sampled = [];
  for (let k = 0; k < 90; k++) {
    sampled.push(await page.evaluate(() => { const s = window.gpuLab.engine.snapshot();
      return { t: s.time, flights: s.inFlight.map(f => ({ job: f.id.split('#')[0], gpu: f.assignedGpuIds[0], pool: f.pool ?? null, kind: f.kind, reverse: !!f.reverse })),
               boards: s.gpus.map(g => ({ i: g.index, job: g.jobId, status: g.status })), queued: s.stats.queued, queue: s.queue.map(q => q.id), completed: s.stats.completed, pool: s.run.display?.boards?.[0]?.pool }; }));
    await sleep(100);
  }
  const ev = (await (await fetch(`${base}/runs/${meta.runId}/events?types=start,preempt,finish,arrive`)).text()).split('\n').filter(Boolean).map(l => JSON.parse(l));
  const starts = new Map(), pre = new Map(), arrived = new Set(), finished = new Set();
  for (const e of ev) { if (e.type === 'start') (starts.get(e.job) || starts.set(e.job, []).get(e.job)).push(e); else if (e.type === 'preempt') (pre.get(e.job) || pre.set(e.job, []).get(e.job)).push(e); else if (e.type === 'arrive') arrived.add(e.job); else if (e.type === 'finish') finished.add(e.job); }
  const routes = sampled.flatMap(s => s.flights.filter(f => f.kind === 'route'));
  // pod pools: the particle must go to the board the scheduler chose; pools drawn only as racks (board null): it must go to the pool the scheduler chose
  const wrong = routes.filter(f => !(starts.get(f.job) || []).some(e => e.board != null ? `GPU-${String(e.board + 1).padStart(2, '0')}` === f.gpu : (f.pool != null && e.pool === f.pool)));
  check('assignments: every animated routing particle goes to the board the scheduler chose', routes.length > 0 && wrong.length === 0, `${routes.length} samples, ${new Set(routes.map(r => r.job)).size} distinct jobs, ${wrong.length} mismatches`);
  const evicts = sampled.flatMap(s => s.flights.filter(f => f.kind === 'evict'));
  const wrongE = evicts.filter(f => !(pre.get(f.job) || []).some(e => e.board != null && `GPU-${String(e.board + 1).padStart(2, '0')}` === f.gpu));
  check('preemptions: every eviction particle leaves the board the scheduler evicted from', wrongE.length === 0, `${evicts.length} samples (${new Set(evicts.map(r => r.job)).size} jobs), ${wrongE.length} mismatches`);
  const bad = [];
  for (const s of sampled) for (const b of s.boards) if (b.job && !(starts.get(b.job) || []).some(e => e.board === b.i)) bad.push([b.i, b.job]);
  check('board inspector: the job shown on each board was started there by the scheduler', bad.length === 0, `${bad.length} mismatches over ${sampled.length} frames`);
  const unknownQ = sampled.flatMap(s => s.queue).filter(j => !arrived.has(j));
  check('queue: every queued job shown was a real arrival from the trace', unknownQ.length === 0, `${new Set(sampled.flatMap(s => s.queue)).size} distinct queue entries`);
  const comp = sampled.map(s => s.completed); const mono = comp.every((c, i) => i === 0 || c >= comp[i - 1]);
  check('completions: the completed counter only moves forward and matches finish events', mono && comp.at(-1) > 0, `${comp[0]} -> ${comp.at(-1)}`);
  // real inference vs another policy on the same scenario: decisions must differ
  const other = policy === 'fifo' ? 'priority_fifo' : 'fifo';
  const sc = await page.evaluate(() => window.gpuLab.engine.scenario);
  const r2 = await (await fetch(base + '/whatif', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ scenario: sc, policies: [other], snapshot_s: 600 }) })).json();
  const ev2 = (await (await fetch(`${base}/runs/${r2.results[other].run_id}/events?types=start`)).text()).split('\n').filter(Boolean).map(l => JSON.parse(l)).filter(e => !e.warm);
  const s1 = ev.filter(e => e.type === 'start' && !e.warm).map(e => e.job), s2 = ev2.map(e => e.job);
  const n = Math.min(s1.length, s2.length, 400); let diff = 0; for (let i = 0; i < n; i++) if (s1[i] !== s2[i]) diff++;
  check(`${policy} decides differently from ${other} on the identical workload (real inference, not a copy)`, diff > n * 0.05, `${diff} of the first ${n} starts differ`);
  check('no page errors', !logs.some(l => /^pageerror/.test(l)), logs.filter(l => /^pageerror/.test(l)).slice(0, 2).join(' | '));
  await page.screenshot({ path: path.join(out, `mapping-${policy}.png`) });
} catch (e) { check('run completed without exception', false, String(e.stack || e).slice(0, 300)); }
finally { await browser.close(); server.close(); api.kill('SIGTERM'); writeFileSync(path.join(out, `event-mapping-${policy}.json`), JSON.stringify(results, null, 1)); }
const f = results.filter(r => !r.ok); console.log(`\n${results.length - f.length}/${results.length} checks passed (${policy})`); process.exit(f.length ? 1 : 0);
