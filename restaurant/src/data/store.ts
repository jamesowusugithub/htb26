import {
  EMPTY_METRICS, type Config, type Decision, type GpuView, type Job, type Metrics,
  type SimEvent, type SimState, type SchedulerName,
} from './types'

export function emptyState(): SimState {
  return {
    t: 0, lastSeq: 0, gpuOrder: [], gpus: {}, jobs: {}, metrics: { ...EMPTY_METRICS },
    scheduler: null, lastDecision: null, thresholds: { warning: 75, critical: 85 },
    coins: 0, missed: 0, rejections: [],
  }
}

export function stateFromConfig(cfg: Config, prev?: SimState): SimState {
  const s = emptyState()
  s.thresholds = cfg.thresholds
  s.scheduler = cfg.scheduler
  for (const n of cfg.nodes)
    for (const g of n.gpus) {
      s.gpuOrder.push(g.id)
      s.gpus[g.id] = {
        id: g.id, name: g.name, tier: g.tier, vram_gb: g.vram_gb, compute: g.compute,
        temp: prev?.gpus[g.id]?.temp ?? 40, util: 0, vram_used_gb: 0, health: 'normal', disabled: false,
      }
    }
  return s
}

const DONE_KEEP_TICKS = 12

/** Pure-ish reducer: mutates and returns the given state (caller owns it). */
export function applyEvent(s: SimState, ev: SimEvent): SimState {
  if (ev.seq <= s.lastSeq) return s // dedupe
  s.lastSeq = ev.seq
  s.t = Math.max(s.t, ev.t)
  switch (ev.type) {
    case 'JOB_ARRIVED':
      s.jobs[ev.job.id] = { job: ev.job, status: 'arrived', gpuIds: [], arrivedSeq: ev.seq }
      break
    case 'DECISION': {
      const j = s.jobs[ev.job_id]
      const d: Decision = {
        job_id: ev.job_id, action: ev.action, target_gpu_ids: ev.target_gpu_ids, scheduler: ev.scheduler,
        factors: ev.factors, mask_summary: ev.mask_summary, t: ev.t, seq: ev.seq,
      }
      s.lastDecision = d
      s.scheduler = ev.scheduler
      if (j && j.status !== 'running') {
        j.gpuIds = ev.target_gpu_ids
        j.status = ev.action === 'hold' ? 'held' : ev.action === 'cloud' ? 'cloud' : 'assigned'
      }
      break
    }
    case 'SCHEDULER_CHANGED':
      s.scheduler = ev.scheduler
      break
    case 'ALLOCATION_REJECTED':
      s.rejections.push({ t: ev.t, job_id: ev.job_id, gpu_id: ev.gpu_id, reason: ev.reason })
      if (s.rejections.length > 20) s.rejections.shift()
      break
    case 'JOB_STARTED': {
      const j = s.jobs[ev.job_id]
      if (j) { j.status = 'running'; j.gpuIds = ev.gpu_ids; j.etaT = ev.eta_t }
      break
    }
    case 'JOB_COMPLETED': {
      const j = s.jobs[ev.job_id]
      if (j) { j.status = 'done'; j.onTime = ev.on_time; j.doneT = ev.t }
      s.coins += 1
      if (!ev.on_time) s.missed += 1
      break
    }
    case 'JOB_FAILED': {
      const j = s.jobs[ev.job_id]
      if (j) {
        if (ev.requeued) { j.status = 'held'; j.gpuIds = []; j.etaT = undefined }
        else { j.status = 'failed'; j.doneT = ev.t }
      }
      break
    }
    case 'GPU_TELEMETRY': {
      const g = s.gpus[ev.gpu_id]
      if (g) { g.temp = ev.temp; g.util = ev.util; g.vram_used_gb = ev.vram_used_gb; g.health = ev.health }
      break
    }
    case 'THERMAL_WARNING':
      break // telemetry carries the health; metrics carry incident count
    case 'GPU_DISABLED': {
      const g = s.gpus[ev.gpu_id]
      if (g) { g.disabled = true; g.health = 'down' }
      break
    }
    case 'GPU_RESTORED': {
      const g = s.gpus[ev.gpu_id]
      if (g) { g.disabled = false; if (g.health === 'down') g.health = 'normal' }
      break
    }
    case 'METRICS': {
      const { seq: _a, t: _b, type: _c, ...m } = ev
      void _a; void _b; void _c
      s.metrics = m as Metrics
      break
    }
  }
  // bound memory: forget long-finished jobs
  for (const id in s.jobs) {
    const j = s.jobs[id]
    if ((j.status === 'done' || j.status === 'failed') && j.doneT !== undefined && s.t - j.doneT > DONE_KEEP_TICKS) delete s.jobs[id]
  }
  return s
}

// ---- snapshot parsing ----
// Real shape (backend sim.snapshot() + Run.snapshot()):
//   gpus[]    {gpu_id, tier, temp, util, vram_used_gb, vram_total_gb, health, job_ids[]}
//   queue[]   flat Job (id, priority, vram_gb, ...) + wait_s
//   running[] {job_id, gpu_ids[], eta_t}   <- NO job body; priority/deadline are not in the snapshot
//   metrics, last_seq, scheduler (effective label), t
type R = Record<string, unknown>
const num = (v: unknown, d = 0) => (typeof v === 'number' && isFinite(v) ? v : d)
const isObj = (v: unknown): v is R => typeof v === 'object' && v !== null
const HEALTH = new Set(['normal', 'warning', 'critical', 'down'])

export function snapshotToState(raw: unknown, cfg: Config | null, prev: SimState): SimState {
  const snap = (isObj(raw) ? raw : {}) as R
  const s = cfg ? stateFromConfig(cfg, prev) : { ...emptyState(), gpuOrder: [...prev.gpuOrder], thresholds: prev.thresholds }
  if (!cfg) for (const id of prev.gpuOrder) s.gpus[id] = { ...prev.gpus[id] }
  s.t = num(snap.t)
  s.lastSeq = num(snap.last_seq)
  if (typeof snap.scheduler === 'string') s.scheduler = snap.scheduler as SchedulerName
  else s.scheduler = prev.scheduler
  if (isObj(snap.metrics)) s.metrics = { ...EMPTY_METRICS, ...(snap.metrics as Partial<Metrics>) }
  s.coins = s.metrics.completed
  s.lastDecision = prev.lastDecision
  const gpuVram: Record<string, number> = {}
  const gpuJobs: Record<string, string[]> = {}
  for (const g of Array.isArray(snap.gpus) ? snap.gpus : []) {
    if (!isObj(g)) continue
    const id = typeof g.gpu_id === 'string' ? g.gpu_id : typeof g.id === 'string' ? g.id : null
    if (!id) continue
    if (!s.gpus[id]) {
      s.gpuOrder.push(id)
      s.gpus[id] = {
        id, tier: (g.tier as GpuView['tier']) ?? (id.startsWith('premium') ? 'premium' : id.startsWith('cloud') ? 'cloud' : 'standard'),
        vram_gb: num(g.vram_total_gb ?? g.vram_gb, 40), compute: num(g.compute, 1), temp: 40, util: 0, vram_used_gb: 0, health: 'normal', disabled: false,
      }
    }
    const v = s.gpus[id]
    v.temp = num(g.temp, v.temp)
    v.util = num(g.util, v.util)
    v.vram_used_gb = num(g.vram_used_gb, v.vram_used_gb)
    if (typeof g.health === 'string' && HEALTH.has(g.health)) v.health = g.health as GpuView['health']
    v.disabled = v.health === 'down'
    gpuVram[id] = v.vram_used_gb
    gpuJobs[id] = Array.isArray(g.job_ids) ? (g.job_ids as string[]) : []
  }
  const asJob = (x: unknown): Job | null => (isObj(x) && typeof x.id === 'string' ? (x as unknown as Job) : null)
  for (const q of Array.isArray(snap.queue) ? snap.queue : []) {
    const job = asJob(q)
    if (job) s.jobs[job.id] = { job, status: 'held', gpuIds: [], arrivedSeq: 0 }
  }
  for (const r of Array.isArray(snap.running) ? snap.running : []) {
    if (!isObj(r) || typeof r.job_id !== 'string') continue
    const id = r.job_id
    const gpuIds = (Array.isArray(r.gpu_ids) ? r.gpu_ids : []) as string[]
    const etaT = typeof r.eta_t === 'number' ? r.eta_t : undefined
    // Snapshot has no job body for running jobs: reuse what we already know, else a neutral placeholder
    // (vram share estimated from the GPU's used vram / number of jobs on it).
    let job = prev.lastSeq <= s.lastSeq ? prev.jobs[id]?.job : undefined // after a server reset ids restart: never reuse
    if (!job) {
      const g0 = gpuIds[0]
      const share = g0 && gpuJobs[g0]?.length ? (gpuVram[g0] ?? 0) / gpuJobs[g0].length : 8
      job = { id, priority: 'medium', vram_gb: Math.max(1, Math.round(share)), compute_units: 1,
        duration_s: Math.max(1, (etaT ?? s.t) - s.t), deadline_t: etaT ?? s.t, splittable: gpuIds.length > 1, tiers: [] }
    }
    s.jobs[id] = { job, status: 'running', gpuIds, etaT, arrivedSeq: 0 }
  }
  return s
}
