// End-to-end: real FastAPI backend -> WebSocket/polling -> replay engine -> Blender/Three.js scene, driven through the real UI.
// Run from server-room/:  node tests/e2e/live-flow.mjs [--transport=polling]
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { serveDist, launch, openRoom, ui, sleep, root } from './harness.mjs';

const repo = path.resolve(root, '..');
const PY = process.env.PYTHON || '/Users/carlkaziboni/anaconda3/envs/htb/bin/python';
const transport = (process.argv.find(a => a.startsWith('--transport=')) || '--transport=websocket').split('=')[1];
const shots = path.resolve(repo, 'analysis/visualization/integration'); mkdirSync(shots, { recursive: true });
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`); };
const freePort = () => new Promise(r => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });

const apiPort = await freePort();
const api = spawn(PY, ['-m', 'uvicorn', 'scheduler.api:app', '--port', String(apiPort), '--log-level', 'warning'], { cwd: repo, stdio: ['ignore', 'pipe', 'pipe'] });
let apiLog = ''; api.stderr.on('data', d => { apiLog += d; }); api.stdout.on('data', d => { apiLog += d; });
const base = `http://127.0.0.1:${apiPort}`;
for (let i = 0; i < 180; i++) { try { if ((await fetch(base + '/health')).ok) break; } catch {} await sleep(1000); if (i === 179) throw new Error('backend did not start\n' + apiLog); }
const { server, port } = await serveDist();
const browser = await launch();
const E = page => page.evaluate(() => { const s = window.gpuLab.engine.snapshot(); return { time: s.time, status: s.status, policy: s.policy, stats: s.stats, conn: s.connection, error: s.error, effects: s.effects,
  gpus: s.gpus.map(g => ({ i: g.index, status: g.status, temp: g.temperature, util: g.utilisation, alert: g.alert, nodesDown: g.nodesDown, pool: g.pool })), failures: window.gpuLab.engine.scenario.failures, scenario: window.gpuLab.engine.scenario }; });
const waitFor = (page, fn, arg, timeout = 90000) => page.waitForFunction(fn, { timeout, polling: 200 }, arg);
const ringHex = (page, i) => page.evaluate(idx => { let hex = null; window.gpuLab.lab.traverse(o => { if (o.userData?.gpuIndex === idx && o.material?.emissive) hex = o.material.color.getHex(); }); return hex; }, i);
const clickByText = (page, text) => page.evaluate(t => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim().includes(t) && !x.disabled); if (!b) throw new Error('button not found: ' + t); b.click(); }, text);

try {
  const url = `http://127.0.0.1:${port}/index.html?api=${encodeURIComponent(base)}&preset=live_demo&policy=priority_fifo&transport=${transport}`;
  const { page, logs } = await openRoom(browser, url);
  await waitFor(page, () => document.querySelector('.gpu-ui').dataset.status === 'ready' && window.gpuLab.engine.snapshot().stats.running > 0);
  await page.evaluate(() => window.gpuLab.engine.setSpeed(4));   // 4x = 40 simulated minutes per real second
  await page.evaluate(() => { const b = document.querySelector('.ui-shell'); });
  let d = await ui(page);
  check('backend mode is active and the Blender GLB loaded', d.mode === 'backend' && d.assetLoaded === 'true' && Number(d.gpuAssetMeshes) >= 1, `mode=${d.mode} meshes=${d.gpuAssetMeshes}`);
  check(`connected via ${transport}`, d.connection === `${transport}:connected`, d.connection);
  const t0 = Number(d.simTime); await sleep(2500); d = await ui(page);
  check('simulation clock advances from backend batches', Number(d.simTime) > t0 + 600, `${t0} -> ${d.simTime}`);
  const s1 = await E(page);
  check('3D scene shows running boards, queue and completed jobs from the backend', s1.stats.running > 0 && s1.stats.queued >= 0 && s1.stats.completed > 0, JSON.stringify({ running: s1.stats.running, queued: s1.stats.queued, completed: s1.stats.completed }));
  await page.screenshot({ path: path.join(shots, 'live-01-running.png') });

  // --- queue positions: chips above the gateway are the backend's queue head for the selected board's pool, in order
  const qpool = await page.evaluate(() => { const s = window.gpuLab.engine.snapshot(); const best = Object.entries(s.pools).sort((a, b) => (b[1].queue_hp + b[1].queue_spot) - (a[1].queue_hp + a[1].queue_spot))[0][0]; return { pool: best, board: window.gpuLab.engine.meta.display.boards.find(b => b.pool === best)?.index ?? null }; });
  if (qpool.board != null) {
    await page.select('#device-select', String(qpool.board)); await sleep(700);
    const chips = await page.evaluate(() => { let n = 0; window.gpuLab.lab.traverse(o => { if (o.name === 'Queue position chip' && o.visible) n++; }); const q = window.gpuLab.engine.snapshot().queue; return { visible: n, head: q.length, first: q[0]?.id }; });
    check('queue chips at the gateway match the backend queue head of the selected pool', chips.visible === Math.min(12, chips.head) && chips.head > 0, `pool=${qpool.pool} chips=${chips.visible} head=${chips.head}`);
    await page.screenshot({ path: path.join(shots, 'live-01b-queue.png') });
    await page.select('#device-select', '0'); await sleep(300);
  }

  // --- the displayed values equal the backend's (REST truth), exactly
  const live = await page.evaluate(() => { const e = window.gpuLab.engine; return { runId: e.runId, snapT: e.lastSnap.t, boards: e.lastSnap.boards.map(b => [b.temp_c, b.util_pct, b.status]) }; });
  const truth = await (await fetch(`${base}/runs/${live.runId}/state?t=${live.snapT}`)).json();
  const same = truth.snapshot.t === live.snapT && truth.snapshot.boards.every((b, i) => b.temp_c === live.boards[i][0] && b.util_pct === live.boards[i][1] && b.status === live.boards[i][2]);
  check('engine snapshot equals backend /state at the same time (no frontend-invented values)', same);
  const feed = (await (await fetch(`${base}/runs/${live.runId}/events?types=snapshot`)).text()).split('\n').filter(Boolean).map(l => JSON.parse(l));
  const allowed = Array.from({ length: 24 }, (_, i) => new Set(feed.map(f => f.boards[i].temp_c)));
  const sampled = [];
  for (let k = 0; k < 25; k++) { sampled.push(await page.evaluate(() => window.gpuLab.engine.snapshot().gpus.map(g => g.temperature))); await sleep(120); }
  const bad = sampled.flatMap(row => row.map((t, i) => (t == null || allowed[i].has(t)) ? null : [i, t])).filter(Boolean);
  check('every temperature shown over 3 s is a value the backend sent for that board', bad.length === 0, bad.slice(0, 3).join(' | '));

  // --- what-if: fail the selected board (real backend failure, real node eviction)
  await page.select('#device-select', '7');
  await sleep(300);
  const before = await E(page);
  const evictBefore = before.stats.failureEvictions;
  await page.click('.fail-action');
  await waitFor(page, () => window.gpuLab.engine.snapshot().status === 'ready' && window.gpuLab.engine.scenario.failures.length === 1);
  check('Fail GPU posts a real scenario failure to the backend', (await E(page)).failures[0]?.board === 7, JSON.stringify((await E(page)).failures));
  await waitFor(page, () => window.gpuLab.engine.snapshot().gpus[7].status === 'failed', undefined, 60000);
  const failed = await E(page);
  check('failed board is reported by the backend with all its nodes down', failed.gpus[7].status === 'failed' && failed.gpus[7].nodesDown > 0 && failed.stats.failed >= 1, `nodesDown=${failed.gpus[7].nodesDown}`);
  let failedRing = null;
  for (let k = 0; k < 30 && failedRing !== 0xe94f64; k++) { failedRing = await ringHex(page, 7); if (failedRing !== 0xe94f64) await sleep(100); }   // allow the next render frame
  check('3D board ring turns the failure colour', failedRing === 0xe94f64, '0x' + (failedRing ?? 0).toString(16));
  await waitFor(page, () => window.gpuLab.engine.meta.failure_evictions > 0, undefined, 30000);
  check('running jobs on the failed node were evicted by the scheduler', (await E(page)).stats.failureEvictions > evictBefore, `evictions=${(await E(page)).stats.failureEvictions}`);
  await page.screenshot({ path: path.join(shots, 'live-02-board-failed.png') });
  await clickByText(page, 'Repair');
  await waitFor(page, () => window.gpuLab.engine.snapshot().status === 'ready' && window.gpuLab.engine.snapshot().gpus[7].status !== 'failed' && window.gpuLab.engine.scenario.failures[0].repair_after_h != null, undefined, 90000);
  check('Repair sends a repair and the board recovers', (await E(page)).gpus[7].status !== 'failed');

  // --- workload spike
  await page.evaluate(() => window.gpuLab.engine.setSpeed(1));   // a 30-simulated-minute spike lasts 3 real seconds at 1x (0.75 s at 4x)
  const q0 = (await E(page)).stats.queued;
  await clickByText(page, 'Job burst');
  await waitFor(page, () => window.gpuLab.engine.snapshot().status === 'ready' && !!window.gpuLab.engine.scenario.burst);
  await waitFor(page, () => /Arrival spike/.test(document.querySelector('.status-banner')?.textContent || ''), undefined, 15000);
  const banner = await page.evaluate(() => document.querySelector('.status-banner')?.textContent || '');
  check('arrival spike scenario is active and announced from backend scenario data', /Arrival spike/.test(banner), banner.slice(0, 80));
  await sleep(2500);
  const q1 = (await E(page)).stats.queued;
  check('queue reflects the backend spike', q1 !== q0 || (await E(page)).stats.arrivalsPerMin > 0, `queued ${q0} -> ${q1}`);
  await page.screenshot({ path: path.join(shots, 'live-03-spike.png') });
  await page.evaluate(() => window.gpuLab.engine.setSpeed(4));

  // --- overheating: cooling fault
  await clickByText(page, 'Cooling fault');
  await waitFor(page, () => window.gpuLab.engine.snapshot().status === 'ready' && !!window.gpuLab.engine.scenario.cooling_fault);
  await waitFor(page, () => window.gpuLab.engine.snapshot().stats.alerts > 0, undefined, 90000);
  const hot = await E(page);
  const hottest = hot.gpus.filter(g => g.alert).sort((a, b) => b.temp - a.temp)[0];
  const thr = await page.evaluate(() => window.gpuLab.engine.meta.thermal.assumptions.alert_threshold_c);
  check('overheating alerts come from the backend and exceed its stated threshold', hot.gpus.filter(g => g.alert).every(g => g.temp >= thr), `${hot.stats.alerts} boards >= ${thr} C, hottest ${hottest.temp} C`);
  // the pulsing alert colour is lerp(0xff2d2d, 0xffb199): red channel saturated, green >= 45. Normal hot-running boards top out at red ~240.
  const rings = [];
  for (let k = 0; k < 12; k++) { rings.push(await page.evaluate(idx => { const g = window.gpuLab.engine.snapshot().gpus[idx]; let hex = null; window.gpuLab.lab.traverse(o => { if (o.userData?.gpuIndex === idx && o.material?.emissive) hex = o.material.color.getHex(); }); return { alert: g.alert, hex }; }, hottest.i)); await sleep(90); }
  const alertFrames = rings.filter(r => r.alert);
  check('hottest board ring pulses the red alert colour in the 3D scene', alertFrames.length >= 6 && alertFrames.some(r => ((r.hex >> 16) & 255) >= 250 && ((r.hex >> 8) & 255) <= 200), alertFrames.slice(0, 3).map(r => '0x' + r.hex.toString(16)).join(','));
  await page.screenshot({ path: path.join(shots, 'live-04-overheating.png') });
  const evidence = await page.evaluate(() => document.querySelector('.evidence-strip')?.textContent || '');
  check('footer states the thermal values are a proxy', /proxy/i.test(evidence) && /Simulated replay/.test(evidence), evidence.slice(0, 120));

  // --- policy switch keeps the playhead
  const tBefore = (await E(page)).time;
  await page.select('select[aria-label="Scheduling policy"]', 'sjf_hint');
  await waitFor(page, () => window.gpuLab.engine.snapshot().status === 'ready' && window.gpuLab.engine.snapshot().policy === 'sjf_hint', undefined, 90000);
  const tAfter = (await E(page)).time;
  check('switching policy re-runs the scenario in the backend without rewinding', tAfter >= tBefore - 1 && tAfter < tBefore + 7200, `${Math.round(tBefore)} -> ${Math.round(tAfter)}`);
  const pools = await page.evaluate(() => document.querySelectorAll('.pool-table tbody tr').length);
  check('pool panel lists all six simulated pools', pools === 6, `${pools}`);

  // --- scenario preset, pause/resume
  await page.select('select[aria-label="What-if scenario"]', 'node_failure');
  await waitFor(page, () => window.gpuLab.engine.snapshot().status === 'ready' && window.gpuLab.engine.scenario.name === 'node_failure' && window.gpuLab.engine.snapshot().time < 600, undefined, 90000);
  check('selecting a preset loads that backend scenario from t=0', (await E(page)).scenario.failures.length === 1);
  await clickByText(page, 'Pause'); await sleep(500);
  const tp = (await E(page)).time; await sleep(1500);
  check('pause freezes the backend clock', Math.abs((await E(page)).time - tp) < 1, `${tp}`);
  await clickByText(page, 'Resume');
  const finalErrors = logs.filter(l => /^(pageerror|error)/.test(l) && !/favicon|Failed to load resource/i.test(l));
  check('no page or console errors', finalErrors.length === 0, finalErrors.slice(0, 2).join(' | '));
} catch (e) {
  check('e2e run completed without exception', false, String(e.stack || e).slice(0, 400));
} finally {
  await browser.close(); server.close(); api.kill('SIGTERM');
  writeFileSync(path.join(shots, `live-flow-${transport}.json`), JSON.stringify(results, null, 1));
}
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed (${transport})`);
process.exit(failed.length ? 1 : 0);
