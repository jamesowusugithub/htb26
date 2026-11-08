// Replay engine: presents the scheduling backend's results through the same engine surface the 3D room already uses
// (tick(), snapshot(), onEvent), so the Blender scene, materials and animations are untouched.
//
// Contract: this engine NEVER invents scheduling decisions or GPU measurements.
//   - job starts/finishes/preemptions, node failures, queue order, board utilisation/temperature/power/forecast and
//     thermal alerts are copied from backend events and snapshots;
//   - the only values it derives are arithmetic on backend fields (job progress = elapsed / service_s, counts, arrival rate)
//     and purely visual timing (route-particle flight time).
// Temperature/power are a backend *proxy* (H100 profile); the engine carries the backend's label through unchanged.
import * as ops from './scenario-ops.js';
import { buildRackPools } from './rack-fabric.js';

export const SPEED_BASE = 600;        // trace seconds per real second at "1x" (10 simulated minutes per second)
const ROUTE_SECONDS = 1.2;            // visual flight time of a routing particle only
const MAX_ROUTES = 48;                // particle pool size in the scene; excess is counted, not hidden
const EVENT_LOG = 80;
const RANK = { fail: 6, thermal_alert: 5, repair: 4, preempt: 3, start: 2, finish: 1, arrive: 0 };
export const gpuId = i => `GPU-${String(i + 1).padStart(2, '0')}`;

export class ReplayEngine {
  constructor({ client, scenario, policy = 'priority_fifo', onEvent, onChange, speed = 1, paused = false } = {}) {
    this.client = client;
    this.baseScenario = JSON.parse(JSON.stringify(scenario));
    this.scenario = JSON.parse(JSON.stringify(scenario));
    this.policy = policy;
    this.speed = speed;
    this.paused = paused;
    this.onEvent = onEvent;
    this.onChange = onChange;
    this.focusBoard = 0;
    this.focusPool = null;
    this.status = 'idle';               // idle | computing | ready | ended | error
    this.error = null;
    this.connection = { mode: 'offline', status: 'idle' };
    this.meta = null; this.runId = null; this.comparison = null; this.workload = null; this.metrics = null;
    this.time = 0;
    this.version = 0;
    this.loadToken = 0; this.streamId = 0; this.stream = null;
    this.counters = { batches: 0, eventsApplied: 0, routesDropped: 0, loads: 0, lastBatchAt: null };
    this.scoreboard = null; this.scoreboardStatus = 'idle';
    this.listeners = new Set(onEvent ? [onEvent] : []);
    this.resetState();
  }

  // ------------------------------------------------------------------ state
  resetState() {
    this.lastSnap = null;
    this.prevArrived = null;
    this.arrivalsPerMin = null;
    this.running = new Map();           // job -> {board,pool,gpus,priority,startT,service,attempt}
    this.routes = [];                   // visual only: {job,board,priority,age,reverse}
    this.events = [];
    this.allocations = [];              // the latest scheduler decisions, newest first, for the 'Why jobs go where they do' panel
    this.arrivedAt = new Map();         // job -> arrival time, to show how long a job waited before it was placed
    this.latest = null;
    this.alertBoards = new Set();
    this.assigned = null; this.assignedVersion = -1;
    this.version++;
  }

  applyState(st) {
    this.lastSnap = st.snapshot || null;
    for (const r of st.running || []) this.running.set(r.job, { board: r.board, pool: r.pool, gpus: r.gpus, priority: r.priority, startT: r.start_t, service: r.service_s, attempt: r.attempt });
    this.time = st.t;
    this.version++;
  }

  // ------------------------------------------------------------------ loading / streaming
  async load(scenario = this.scenario, policy = this.policy, seekT = this.time) {
    const token = ++this.loadToken;
    const wasPaused = this.paused;
    this.status = 'computing';
    this.stream?.send({ cmd: 'pause' });                 // freeze the old clock while the backend recomputes
    this.emitChange();
    try {
      const res = await this.client.whatIf({ scenario, policies: [policy], snapshot_s: 60 });
      if (token !== this.loadToken) return false;
      const runId = res.results[policy].run_id;
      const [meta, st] = await Promise.all([this.client.runMeta(runId), this.client.state(runId, seekT)]);
      if (token !== this.loadToken) return false;
      this.closeStream();
      this.scenario = JSON.parse(JSON.stringify(scenario)); this.policy = policy; this.allocations = []; this.arrivedAt.clear(); this.runId = runId; this.meta = meta;
      this.comparison = res.comparison; this.workload = res.workload; this.metrics = res.results[policy].metrics;
      this.counters.loads++;
      this.resetState();
      this.applyState(st);
      this.paused = wasPaused;
      this.openStream(seekT);
      this.status = 'ready'; this.error = null;
      this.emitChange();
      return true;
    } catch (e) {
      if (token !== this.loadToken) return false;
      this.status = this.runId ? 'ready' : 'error';    // keep showing the previous run if there is one
      this.error = String(e.message || e);
      if (this.stream && !wasPaused) this.stream.send({ cmd: 'resume' });
      this.emitChange();
      return false;
    }
  }

  openStream(t) {
    const id = ++this.streamId;
    this.stream = this.client.openStream(this.runId, {
      start: t, speed: this.speed * SPEED_BASE, paused: this.paused,
      onMessage: m => { if (id === this.streamId) this.ingest(m); },
      onStatus: s => { if (id === this.streamId) { this.connection = s; this.emitChange(); } },
    });
  }
  closeStream() { this.streamId++; this.stream?.close(); this.stream = null; }
  dispose() { this.loadToken++; this.closeStream(); this.listeners.clear(); }

  ingest(m) {
    if (m.type === 'meta') { this.meta = m; this.version++; }
    else if (m.type === 'batch') {
      this.counters.batches++;
      this.counters.lastBatchAt = Date.now();      // wall clock, display only ("last data n s ago")
      let top = null;
      for (const it of m.items) {
        const text = this.applyItem(it);
        if (text && (!top || RANK[it.type] >= RANK[top.type])) top = { type: it.type, text, item: it };
      }
      this.time = m.t_to;
      this.version++;
      if (top) { this.latest = top; for (const l of this.listeners) l({ type: top.type, text: top.text, time: top.item.t, ...top.item }); }
    } else if (m.type === 'end') { this.status = 'ended'; this.emitChange(); }
    else if (m.type === 'error') { this.error = m.detail || 'stream error'; this.emitChange(); }
  }

  poolLabel(id) { return this.meta?.pools?.find(p => p.id === id)?.label || id; }

  applyItem(it) {
    this.counters.eventsApplied++;
    switch (it.type) {
      case 'snapshot': {
        this.lastSnap = it;
        const arrived = Object.values(it.pools).reduce((a, p) => a + p.arrived, 0);
        if (this.prevArrived && it.t > this.prevArrived.t) this.arrivalsPerMin = ((arrived - this.prevArrived.n) / (it.t - this.prevArrived.t)) * 60;
        this.prevArrived = { t: it.t, n: arrived };
        return null;
      }
      case 'arrive':
        if (!it.warm) { this.arrivedAt.set(it.job, it.t); if (this.arrivedAt.size > 5000) this.arrivedAt.delete(this.arrivedAt.keys().next().value); }
        return it.warm ? null : `Job ${it.job} entered the ${this.poolLabel(it.pool)} queue (${it.gpus} GPU, ${it.priority === 'hp' ? 'high priority' : 'spot'})`;
      case 'start': {
        this.running.set(it.job, { board: it.board, pool: it.pool, gpus: it.gpus, priority: it.priority, startT: it.t, service: it.service_s, attempt: it.attempt });
        if (it.warm) return null;
        this.allocations.unshift({ t: it.t, job: it.job, gpus: it.gpus, priority: it.priority, board: it.board ?? null, pool: it.pool, cloud: !!it.cloud, attempt: it.attempt, waitS: this.arrivedAt.has(it.job) ? Math.max(0, it.t - this.arrivedAt.get(it.job)) : null });
        if (this.allocations.length > 8) this.allocations.length = 8;
        this.addRoute({ job: it.job, board: it.board, pool: it.pool, priority: it.priority, reverse: false });
        return `Scheduler routed ${it.job} to ${it.board != null ? `board ${it.board + 1}` : this.poolLabel(it.pool)}${it.attempt > 1 ? ` (restart ${it.attempt})` : ''}`;
      }
      case 'finish':
        this.running.delete(it.job);
        return `Job ${it.job} completed after waiting ${(it.wait_s / 60).toFixed(0)} min`;
      case 'preempt': {
        const r = this.running.get(it.job);
        this.running.delete(it.job);
        if (it.board != null) this.addRoute({ job: it.job, board: it.board, priority: 'evict', reverse: true });
        return it.cause === 'node_failure' ? `Node failure: ${it.job} evicted and requeued${r ? '' : ''}` : `Spot job ${it.job} preempted for a high-priority job`;
      }
      case 'fail': return `Node failure on board ${it.board != null ? it.board + 1 : '?'} (${this.poolLabel(it.pool)})`;
      case 'repair': return `Node repaired on board ${it.board != null ? it.board + 1 : '?'}`;
      case 'thermal_alert':
        it.state === 'on' ? this.alertBoards.add(it.board) : this.alertBoards.delete(it.board);
        return it.state === 'on' ? `Board ${it.board + 1} overheating: ${it.temp_c} °C ≥ ${it.threshold_c} °C (proxy)` : `Board ${it.board + 1} back below the alert threshold`;
      default: return null;
    }
  }

  addRoute(r) {
    if (this.routes.length >= MAX_ROUTES) { this.counters.routesDropped++; return; }   // visual sampling only; counts stay exact
    this.routes.push({ ...r, age: 0 });
  }

  /** Called every frame. `realDt` is real seconds (visual flight time); simulation time only advances from the backend. */
  tick(_simDt, realDt = 0) {
    if (!this.routes.length || realDt <= 0) return this.snapshot();
    for (const r of this.routes) r.age += realDt;
    this.routes = this.routes.filter(r => r.age < ROUTE_SECONDS);
    return this.snapshot();
  }

  // ------------------------------------------------------------------ snapshot (shape consumed by gpu-room.js / overlay)
  assignedByBoard() {
    if (this.assigned && this.assignedVersion === this.version) return this.assigned;
    const a = new Map();
    for (const [job, r] of this.running) {
      if (r.board == null) continue;
      const cur = a.get(r.board);
      if (!cur || r.startT > cur.startT) a.set(r.board, { job, ...r });
    }
    this.assigned = a; this.assignedVersion = this.version;
    return a;
  }

  snapshot() {
    const snap = this.lastSnap;
    const disp = this.meta?.display;
    const n = disp?.boards?.length || 24;
    const assigned = this.assignedByBoard();
    const gpus = [];
    for (let i = 0; i < n; i++) {
      const b = snap?.boards?.[i], bm = disp?.boards?.[i];
      const a = assigned.get(i);
      const progress = a && a.service > 0 ? Math.min(1, Math.max(0, (this.time - a.startT) / a.service)) : 0;
      gpus.push({
        id: gpuId(i), index: i, status: b?.status ?? 'idle', temperature: b ? b.temp_c : null, utilisation: b ? b.util_pct : 0,
        jobId: b && b.status === 'running' && a ? a.job : null, progress, completed: 0, failed: b?.nodes_down ?? 0, cooldownRemaining: 0,
        model: bm ? this.poolLabel(bm.pool) : 'Connecting…', pool: bm?.pool ?? null, pod: bm?.pod ?? Math.floor(i / 6), slice: bm?.slice ?? i % 6,
        label: bm ? `${gpuId(i)} / ${this.poolLabel(bm.pool)}` : `${gpuId(i)} / Pod ${Math.floor(i / 6) + 1}`,
        alert: !!b?.alert, powerW: b ? b.power_w : null, nodes: b?.nodes ?? bm?.nodes ?? 0, nodesDown: b?.nodes_down ?? 0,
        capacityGpus: bm?.capacity_gpus ?? 0, runningJobs: b?.running_jobs ?? 0, forecast: b?.forecast ?? null,
      });
    }
    const focusPool = this.focusPool || disp?.boards?.[this.focusBoard]?.pool;
    const heads = (snap && focusPool && snap.pools[focusPool]?.queue_head) || [];
    const pools = snap?.pools ?? {};
    const sum = k => Object.values(pools).reduce((a, p) => a + (p[k] || 0), 0);
    const count = s => gpus.filter(g => g.status === s).length;
    const inFlight = this.routes.map((r, k) => ({
      id: `${r.job}#${k}`, priority: r.priority === 'hp' ? 'high' : r.priority, assignedGpuIds: [gpuId(r.board)],
      pool: r.pool, transitRemaining: Math.max(0, ROUTE_SECONDS - r.age), reverse: r.reverse, kind: r.priority === 'evict' ? 'evict' : 'route' }));
    const rackPools = buildRackPools(this.meta?.pools, pools, snap?.boards, disp);
    const sc = this.scenario, nowH = this.time / 3600;
    return {
      time: this.time, policy: this.policy, evidence: 'backend_simulation', mode: 'backend',
      gpus, jobs: [], inFlight,
      queue: heads.map((h, i) => ({ id: h.job, priority: h.priority === 'hp' ? 'high' : 'spot', gpus: h.gpus, position: i + 1, pool: focusPool })),
      stats: { running: count('running'), completed: sum('completed'), submitted: sum('arrived'), queued: sum('queue_hp') + sum('queue_spot'),
               queuedHp: sum('queue_hp'), queuedSpot: sum('queue_spot'), failed: count('failed'), idle: count('idle'), cooling: count('cooling'), reserved: 0,
               alerts: gpus.filter(g => g.alert).length, arrivalsPerMin: this.arrivalsPerMin, routesDropped: this.counters.routesDropped,
               failureEvictions: this.meta?.failure_evictions ?? 0 },
      pools, rackPools, events: this.events, allocations: this.allocations,
      run: { runId: this.runId, scenarioId: this.meta?.scenario_id, scenario: sc, thermal: this.meta?.thermal ?? null, forecast: this.meta?.forecast ?? null, demand: this.meta?.demand_forecast ?? null,
             display: disp ?? null, pools: this.meta?.pools ?? null, window: this.meta?.window ?? null, policyInfo: this.meta?.policy ?? null, metrics: this.metrics, comparison: this.comparison },
      effects: { burstActive: ops.burstActive(sc, nowH), coolingFaultActive: ops.coolingFaultActive(sc, nowH),
                 coolingDeltaC: snap?.cooling_fault_delta_c ?? 0, burst: sc.burst ?? null },
      link: { base: this.client?.base ?? null, runId: this.runId, batches: this.counters.batches, events: this.counters.eventsApplied, loads: this.counters.loads, lastBatchAt: this.counters.lastBatchAt },
      scoreboard: this.scoreboard, scoreboardStatus: this.scoreboardStatus,
      connection: this.connection, status: this.status, error: this.error,
    };
  }

  // ------------------------------------------------------------------ playback controls
  setPaused(p) { this.paused = p; this.stream?.send({ cmd: p ? 'pause' : 'resume' }); this.emitChange(); }
  setSpeed(mult) { this.speed = mult; this.stream?.send({ cmd: 'speed', value: mult * SPEED_BASE }); this.emitChange(); }
  setFocusBoard(i) { this.focusBoard = i; this.version++; }
  setFocusPool(id) { this.focusPool = id || null; this.version++; }
  async seek(t) {
    if (!this.runId) return;
    const st = await this.client.state(this.runId, t);
    const wasPaused = this.paused;
    this.resetState(); this.applyState(st);
    this.stream?.send({ cmd: 'seek', t });
    this.paused = wasPaused;
    this.emitChange();
  }

  // ------------------------------------------------------------------ what-if controls -> real backend scenarios
  nowH() { return this.time / 3600; }
  setPolicy(name) { return this.load(this.scenario, name, this.time); }
  applyScenario(sc) { return this.load(sc, this.policy, this.time); }
  addJob(pool, opts = {}) { return this.applyScenario(ops.addInjectedJob(this.scenario, this.nowH(), { pool, ...opts })); }
  burst(opts) { return this.applyScenario(ops.addBurst(this.scenario, this.nowH(), opts)); }
  failBoard(i) { return this.applyScenario(ops.failBoard(this.scenario, this.nowH(), i)); }
  repairBoard(i) { return this.applyScenario(ops.repairBoard(this.scenario, this.nowH(), i)); }
  boardIsFailed(i) { return ops.boardIsFailed(this.scenario, this.nowH(), i); }
  coolingFault(on, delta = 35) { return this.applyScenario(on ? ops.startCoolingFault(this.scenario, this.nowH(), delta) : ops.stopCoolingFault(this.scenario, this.nowH())); }
  selectScenario(sc) { this.baseScenario = JSON.parse(JSON.stringify(sc)); return this.load(sc, this.policy, 0); }
  reset() { return this.load(this.baseScenario, this.policy, 0); }

  /** Run the current scenario under several policies in the backend and keep the backend's own comparison table. */
  async compare(policies = ['fifo', 'priority_fifo', 'backfill_median', 'sjf_hint', 'rl_ppo', 'sjf_oracle']) {
    this.scoreboardStatus = 'computing'; this.emitChange();
    try {
      const res = await this.client.whatIf({ scenario: this.scenario, policies, snapshot_s: 600 });
      this.scoreboard = { scenarioId: res.scenario_id, rows: res.comparison, workload: res.workload, computeSeconds: res.compute_seconds };
      this.scoreboardStatus = 'ready';
    } catch (e) { this.scoreboardStatus = 'error'; this.error = String(e.message || e); }
    this.emitChange();
  }

  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emitChange() { this.onChange?.(this); }
}
