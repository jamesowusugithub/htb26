import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ReplayEngine, SPEED_BASE, gpuId } from '../replay-engine.js';
import { BackendClient, PollingStream } from '../backend-client.js';
import * as ops from '../scenario-ops.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE = path.resolve(here, '../../samples/run_node_failure_cooling_fault.ndjson');
const lines = readFileSync(SAMPLE, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
const meta = lines[0], items = lines.slice(1);
const SC = meta.scenario;

function engine() {
  const e = new ReplayEngine({ client: {}, scenario: SC });
  e.meta = meta; e.runId = 'sample'; e.status = 'ready';
  return e;
}
const batches = (secs = 60) => {
  const out = []; let t0 = 0, cur = [];
  for (const it of items) { while (it.t >= t0 + secs) { out.push({ type: 'batch', t_from: t0, t_to: t0 + secs, items: cur }); cur = []; t0 += secs; } cur.push(it); }
  out.push({ type: 'batch', t_from: t0, t_to: t0 + secs, items: cur });
  return out;
};

test('every displayed board value equals the backend snapshot exactly (nothing invented)', () => {
  const e = engine();
  let checked = 0;
  for (const b of batches()) {
    e.ingest(b);
    const snap = items.filter(i => i.type === 'snapshot' && i.t < b.t_to && i.t >= b.t_from).at(-1);
    if (!snap) continue;
    const s = e.snapshot();
    snap.boards.forEach((bd, i) => {
      assert.equal(s.gpus[i].temperature, bd.temp_c);
      assert.equal(s.gpus[i].utilisation, bd.util_pct);
      assert.equal(s.gpus[i].status, bd.status);
      assert.equal(s.gpus[i].alert, bd.alert);
      assert.equal(s.gpus[i].powerW, bd.power_w);
      assert.deepEqual(s.gpus[i].forecast, bd.forecast);
      assert.equal(s.gpus[i].nodesDown, bd.nodes_down);
    });
    checked++;
  }
  assert.ok(checked > 100);
});

test('pool totals, completed and queue counts come from backend counters', () => {
  const e = engine();
  for (const b of batches().slice(0, 200)) e.ingest(b);
  const snap = items.filter(i => i.type === 'snapshot' && i.t < e.time).at(-1);
  const s = e.snapshot();
  const sum = k => Object.values(snap.pools).reduce((a, p) => a + p[k], 0);
  assert.equal(s.stats.completed, sum('completed'));
  assert.equal(s.stats.queued, sum('queue_hp') + sum('queue_spot'));
  assert.equal(s.stats.submitted, sum('arrived'));
});

test('running set equals what the start/finish/preempt events imply; progress is elapsed/service', () => {
  const e = engine(); const ref = new Map();
  for (const b of batches().slice(0, 150)) {
    e.ingest(b);
    for (const it of b.items) {
      if (it.type === 'start') ref.set(it.job, it); else if (it.type === 'finish' || it.type === 'preempt') ref.delete(it.job);
    }
  }
  assert.deepEqual([...e.running.keys()].sort(), [...ref.keys()].sort());
  const s = e.snapshot();
  const withJob = s.gpus.filter(g => g.jobId);
  assert.ok(withJob.length > 0);
  for (const g of withJob) {
    const r = e.running.get(g.jobId);
    assert.equal(g.progress, Math.min(1, Math.max(0, (e.time - r.startT) / r.service)));
  }
});

test('queue list is the backend queue head of the selected board pool, in backend order', () => {
  const e = engine();
  for (const b of batches().slice(0, 400)) e.ingest(b);
  const snap = items.filter(i => i.type === 'snapshot' && i.t < e.time).at(-1);
  for (const board of [0, 7, 13, 20]) {
    e.setFocusBoard(board);
    const pool = meta.display.boards[board].pool;
    assert.deepEqual(e.snapshot().queue.map(q => q.id), snap.pools[pool].queue_head.map(h => h.job));
  }
});

test('node failure scenario shows failed boards and thermal alerts exactly when the backend says so', () => {
  const e = engine(); let sawFailed = false, sawAlert = false;
  for (const b of batches()) {
    e.ingest(b);
    const s = e.snapshot();
    if (s.gpus[7].status === 'failed') { sawFailed = true; assert.equal(s.stats.failed >= 1, true); assert.equal(s.gpus[7].utilisation, 0); }
    if (s.stats.alerts > 0) { sawAlert = true; assert.ok(s.gpus.filter(g => g.alert).every(g => g.temperature >= meta.thermal.assumptions.alert_threshold_c)); }
  }
  assert.ok(sawFailed && sawAlert);
});

test('routing particles come from non-warm start events only; evictions run backwards; pool overflow is counted', () => {
  const e = engine();
  const warmStarts = items.filter(i => i.type === 'start' && i.warm);
  e.ingest({ type: 'batch', t_from: 0, t_to: 1, items: warmStarts });
  assert.equal(e.snapshot().inFlight.length, 0);                     // warm start is not animated
  assert.ok(e.running.size >= warmStarts.length - 1);
  const live = items.filter(i => i.type === 'start' && !i.warm && i.board != null).slice(0, 5);
  e.ingest({ type: 'batch', t_from: 1, t_to: 2, items: live });
  const f = e.snapshot().inFlight;
  assert.equal(f.length, 5);
  assert.deepEqual(f.map(x => x.assignedGpuIds[0]), live.map(x => gpuId(x.board)));
  e.tick(0, 2);
  assert.equal(e.snapshot().inFlight.length, 0);
  const many = items.filter(i => i.type === 'start' && !i.warm && i.board != null).slice(0, 60);
  e.ingest({ type: 'batch', t_from: 2, t_to: 3, items: many });
  assert.equal(e.snapshot().inFlight.length, 48);
  assert.equal(e.counters.routesDropped, 12);
  const ev = items.find(i => i.type === 'preempt' && i.cause === 'node_failure' && i.board != null);
  e.tick(0, 2); e.ingest({ type: 'batch', t_from: 3, t_to: 4, items: [ev] });
  assert.equal(e.snapshot().inFlight[0].reverse, true);
});

test('engine and client contain no random numbers and no thermal/scheduling arithmetic', () => {
  for (const f of ['../replay-engine.js', '../backend-client.js', '../scenario-ops.js']) {
    const src = readFileSync(path.resolve(here, f), 'utf8');
    assert.doesNotMatch(src, /Math\.random/, f);
    assert.doesNotMatch(src, /Math\.exp|lerp|setInterval\([^)]*temp/i, f);
  }
});

test('scenario ops only edit scenario parameters, strictly after the playhead, and are idempotent for failures', () => {
  const sc = { start_day: 90, days: 1, failures: [], injected_jobs: [] };
  const a = ops.failBoard(sc, 2.0, 5);
  assert.equal(a.failures[0].board, 5); assert.ok(a.failures[0].at_h > 2.0); assert.equal(a.failures[0].repair_after_h, null);
  assert.equal(sc.failures.length, 0);                                // input not mutated
  assert.equal(ops.failBoard(a, 3.0, 5).failures.length, 1);          // already down: no duplicate
  const r = ops.repairBoard(a, 4.0, 5);
  assert.ok(r.failures[0].repair_after_h > 4.0 - a.failures[0].at_h - 1e-9);
  assert.equal(ops.boardIsFailed(a, 3.0, 5), true); assert.equal(ops.boardIsFailed(r, 5.0, 5), false);
  const b = ops.addBurst(sc, 1.0); assert.ok(b.burst.start_h > 1.0 && b.burst.mult > 1);
  const j = ops.addInjectedJob(sc, 1.0, { pool: 'a10', gpus: 4, priority: 'spot', duration_s: 2700 });
  assert.deepEqual({...j.injected_jobs[0],at_h:0},{at_h:0,pool:'a10',gpus:4,priority:'spot',duration_s:2700}); assert.ok(j.injected_jobs[0].at_h > 1.0);
  const c = ops.startCoolingFault(sc, 1.0), c2 = ops.stopCoolingFault(c, 3.0);
  assert.equal(ops.coolingFaultActive(c, 2.0), true); assert.equal(ops.coolingFaultActive(c2, 4.0), false);
});

test('load() asks the backend for the real scenario, then seeks and streams from the playhead (fake client)', async () => {
  const calls = [];
  const client = {
    whatIf: async b => { calls.push(['whatIf', b]); return { results: { priority_fifo: { run_id: 'r1', metrics: {} } }, comparison: [], workload: {} }; },
    runMeta: async () => meta, state: async (id, t) => { calls.push(['state', id, t]); return { t, snapshot: null, running: [], queued_total: 0, queued_sample: [] }; },
    openStream: (id, o) => { calls.push(['stream', id, o.start, o.speed, o.paused]); return { send: c => calls.push(['send', c]), close() {}, mode: () => 'websocket' }; },
  };
  const e = new ReplayEngine({ client, scenario: SC, speed: 2 });
  e.time = 7200;
  assert.equal(await e.load(), true);
  assert.deepEqual(calls.map(c => c[0]), ['whatIf', 'state', 'stream']);
  assert.equal(calls[1][2], 7200); assert.equal(calls[2][2], 7200); assert.equal(calls[2][3], 2 * SPEED_BASE);
  assert.equal(calls[0][1].policies[0], 'priority_fifo');
  await e.failBoard(3);
  const sc = calls.filter(c => c[0] === 'whatIf').at(-1)[1].scenario;
  assert.ok(sc.failures.some(f => f.board === 3 && f.at_h > 2.0));
  assert.deepEqual(calls.find(c => c[0] === 'send'), ['send', { cmd: 'pause' }]);   // clock frozen while recomputing
});

test('a failed what-if keeps the previous run on screen and reports the backend error', async () => {
  let n = 0;
  const client = {
    whatIf: async () => { if (++n > 1) throw new Error('422 invalid scenario'); return { results: { priority_fifo: { run_id: 'r1', metrics: {} } }, comparison: [], workload: {} }; },
    runMeta: async () => meta, state: async (id, t) => ({ t, snapshot: null, running: [] }),
    openStream: () => ({ send() {}, close() {}, mode: () => 'websocket' }),
  };
  const e = new ReplayEngine({ client, scenario: SC });
  await e.load();
  assert.equal(await e.failBoard(99), false);
  assert.equal(e.status, 'ready'); assert.match(e.error, /422/); assert.equal(e.runId, 'r1');
});

test('polling fallback: same message shape, and WebSocket failure falls back to polling', async () => {
  const fakeFetch = async url => {
    const u = new URL(url);
    if (u.pathname.endsWith('/events')) return { ok: true, text: async () => items.filter(i => i.t >= +u.searchParams.get('t_from') && i.t <= +u.searchParams.get('t_to')).map(i => JSON.stringify(i)).join('\n') };
    return { ok: true, json: async () => meta };
  };
  const client = new BackendClient('http://x', { WebSocketImpl: class { constructor() { throw new Error('no ws'); } }, fetchImpl: fakeFetch });
  const msgs = []; const modes = [];
  const s = client.openStream('r', { start: 0, speed: 3600, onMessage: m => msgs.push(m), onStatus: m => modes.push(m.mode) });
  await new Promise(r => setTimeout(r, 900));
  s.close();
  assert.equal(s.mode(), 'polling'); assert.ok(modes.includes('polling'));
  assert.equal(msgs[0].type, 'meta');
  const batch = msgs.find(m => m.type === 'batch'); assert.ok(batch && Array.isArray(batch.items) && batch.t_to > batch.t_from);
});
