// Live proof run against ALREADY RUNNING servers. Records real network traffic and captures a job id from the UI for lineage tracing.
//   node tests/e2e/proof.mjs --api=http://127.0.0.1:8010 --web=http://127.0.0.1:8081
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { launch, openRoom, sleep, root } from './harness.mjs';
const arg = (k, d) => (process.argv.find(a => a.startsWith(`--${k}=`)) || `--${k}=${d}`).split('=').slice(1).join('=');
const API = arg('api', 'http://127.0.0.1:8010'), WEB = arg('web', 'http://127.0.0.1:8081');
const out = path.resolve(root, '../analysis/proof'); mkdirSync(out, { recursive: true });
const browser = await launch();
const net = { api: API, requests: [], websockets: [], frames: { total: 0, bytes: 0, byType: {}, itemsByType: {} }, sampleFrames: [] };
try {
  const url = `${WEB}/index.html?api=${encodeURIComponent(API)}&preset=heldout_demo&policy=rl_ppo`;
  const page = await browser.newPage();
  const cdp = await page.createCDPSession();
  await cdp.send('Network.enable');
  const pending = new Map();
  cdp.on('Network.requestWillBeSent', e => { if (e.request.url.startsWith(API)) pending.set(e.requestId, { method: e.request.method, url: e.request.url.replace(API, ''), t: e.timestamp }); });
  cdp.on('Network.responseReceived', e => { const r = pending.get(e.requestId); if (r) { r.status = e.response.status; net.requests.push(r); } });
  cdp.on('Network.webSocketCreated', e => net.websockets.push({ url: e.url.replace(/^ws:\/\/[^/]+/, '') }));
  cdp.on('Network.webSocketFrameReceived', e => {
    const p = e.response.payloadData; net.frames.total++; net.frames.bytes += p.length;
    try { const m = JSON.parse(p); net.frames.byType[m.type] = (net.frames.byType[m.type] || 0) + 1;
      if (m.type === 'batch') for (const it of m.items) net.frames.itemsByType[it.type] = (net.frames.itemsByType[it.type] || 0) + 1;
      if (net.sampleFrames.length < 3 && m.type === 'batch' && m.items.some(i => i.type === 'start' && !i.warm)) net.sampleFrames.push({ type: m.type, t_from: m.t_from, t_to: m.t_to, items: m.items.filter(i => ['start', 'finish', 'preempt'].includes(i.type)).slice(0, 3) });
    } catch {}
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.setViewport({ width: 1500, height: 900 });
  await page.waitForFunction(() => document.querySelector('.gpu-ui')?.dataset.assetLoaded === 'true' && document.querySelector('.gpu-ui').dataset.status === 'ready' && window.gpuLab.engine.snapshot().stats.running > 0, { timeout: 120000, polling: 250 });
  await sleep(9000);                                                      // let real data stream at 1x (10 sim-minutes per second)
  await page.screenshot({ path: path.join(out, 'proof-01-live-rl-scene.png') });
  const st1 = await page.evaluate(() => { const e = window.gpuLab.engine, s = e.snapshot(); return { policy: s.policy, mode: s.connection.mode, status: s.connection.status, runId: e.runId, simTime: s.time, link: s.link, running: s.stats.running, queued: s.stats.queued, completed: s.stats.completed, policyLabel: document.querySelector('select[aria-label="Scheduling policy"]')?.selectedOptions[0]?.textContent }; });

  // pick a job that STARTED during the replay (not the warm start) on some board, and show it in the inspector
  const pick = await page.evaluate(() => { const e = window.gpuLab.engine; for (const [b, a] of e.assignedByBoard()) if (a.startT > 0) return { board: b, job: a.job, startT: a.startT, service: a.service, pool: a.pool, priority: a.priority, gpus: a.gpus }; return null; });
  if (pick) { await page.select('#device-select', String(pick.board)); await sleep(1200); }
  const shown = await page.evaluate(() => ({ jobIdInInspector: document.querySelector('.device-metrics .job-id')?.textContent, gpu: document.querySelector('.device-name h3')?.textContent, subtitle: document.querySelector('.device-subtitle')?.textContent }));
  await page.screenshot({ path: path.join(out, 'proof-02-job-in-inspector.png') });

  // policy scoreboard run by the backend (includes the trained RL policy)
  await page.evaluate(() => [...document.querySelectorAll('button')].find(b => /Compare policies/.test(b.textContent)).click());
  await page.waitForFunction(() => window.gpuLab.engine.snapshot().scoreboardStatus === 'ready', { timeout: 240000, polling: 500 });
  await page.evaluate(() => document.querySelector('.score-section').scrollIntoView({ block: 'start' }));
  await sleep(600);
  await page.screenshot({ path: path.join(out, 'proof-03-policy-scoreboard.png') });
  const sb = await page.evaluate(() => window.gpuLab.engine.snapshot().scoreboard);
  const st2 = await page.evaluate(() => { const s = window.gpuLab.engine.snapshot(); return { link: s.link, simTime: s.time }; });
  writeFileSync(path.join(out, 'network.json'), JSON.stringify({ ...net, requests: net.requests.slice(0, 40), requestCount: net.requests.length }, null, 1));
  writeFileSync(path.join(out, 'live-run.json'), JSON.stringify({ url, st1, pick, shown, scoreboard: sb, after: st2 }, null, 1));
  console.log(JSON.stringify({ st1, pick, shown, requests: net.requests.length, ws: net.websockets, frames: net.frames, scoreRows: sb.rows.map(r => [r.policy, +r.hp_wait_mean_h.toFixed(2), +r.spot_wait_mean_h.toFixed(2)]) }, null, 1));
} finally { await browser.close(); }
