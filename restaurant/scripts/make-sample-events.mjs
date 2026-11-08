// Hand-scripted 60-tick recording following contracts/CONTRACT.md.
// The *story* (who arrives, where they go, what heats up) is scripted by hand below;
// telemetry/metrics are derived from that story so the numbers stay internally consistent.
// SIMULATED data. Not from the real backend. Run: npm run sample
import { writeFileSync } from 'node:fs'

const GPUS = [
  { id: 'premium-0', tier: 'premium', vram_gb: 80, compute: 1.0, temp0: 58 },
  { id: 'premium-1', tier: 'premium', vram_gb: 80, compute: 1.0, temp0: 46 },
  { id: 'standard-0', tier: 'standard', vram_gb: 40, compute: 0.6, temp0: 44 },
  { id: 'standard-1', tier: 'standard', vram_gb: 40, compute: 0.6, temp0: 43 },
  { id: 'standard-2', tier: 'standard', vram_gb: 40, compute: 0.6, temp0: 42 },
  { id: 'cloud-0', tier: 'cloud', vram_gb: 640, compute: 4.0, temp0: 35 },
]
const config = {
  nodes: [
    { id: 'node-0', gpus: GPUS.slice(0, 2).map(({ temp0, ...g }) => g) },
    { id: 'node-1', gpus: GPUS.slice(2, 5).map(({ temp0, ...g }) => g) },
    { id: 'cloud', gpus: GPUS.slice(5).map(({ temp0, ...g }) => g) },
  ],
  thresholds: { warning: 75, critical: 85 },
  overflow_threshold: 10,
  scheduler: 'fallback_heuristic', // honest: this recording is scripted, not an RL policy
}
const TICKS = 60
const RATE = { premium: 3.2, standard: 1.4, cloud: 5.5 } // $/job-second-ish, illustrative

const J = {} // id -> job
const mk = (id, priority, vram_gb, duration_s, t, slack, tiers, splittable = false) => {
  J[id] = { id, priority, vram_gb, compute_units: Math.round(vram_gb * 1.5), duration_s, deadline_t: t + duration_s + slack, splittable, tiers, _t: t }
}
const ALL = ['premium', 'standard', 'cloud']
mk('j01', 'medium', 24, 14, 1, 20, ['standard', 'premium', 'cloud'])
mk('j02', 'high', 60, 17, 2, 14, ['premium'])
mk('j03', 'low', 8, 9, 3, 60, ALL)
mk('j04', 'vip', 70, 12, 4, 6, ['premium'])
mk('j05', 'medium', 30, 12, 5, 18, ['standard', 'premium', 'cloud'])
mk('j06', 'low', 12, 10, 6, 60, ALL)
mk('j07', 'high', 36, 10, 8, 10, ['standard', 'premium', 'cloud'])
mk('j08', 'medium', 16, 8, 9, 15, ['standard', 'premium', 'cloud'])
mk('j09', 'medium', 40, 9, 11, 14, ALL)
mk('j10', 'vip', 40, 8, 13, 5, ['premium', 'cloud'])
mk('j11', 'high', 24, 10, 15, 12, ALL)
mk('j12', 'low', 6, 8, 17, 60, ALL)
mk('j13', 'medium', 20, 9, 22, 14, ALL)
mk('j14', 'high', 32, 10, 23, 12, ALL)
mk('j15', 'low', 10, 8, 23, 60, ALL)
mk('j16', 'vip', 56, 9, 24, 6, ['premium', 'cloud'])
mk('j17', 'medium', 28, 10, 30, 14, ALL)
mk('j18', 'high', 36, 9, 34, 10, ALL)
mk('j19', 'low', 8, 7, 38, 60, ALL)
mk('j20', 'medium', 30, 10, 41, 16, ALL)
mk('j21', 'vip', 64, 8, 44, 6, ['premium', 'cloud'])
mk('j22', 'medium', 18, 7, 48, 14, ALL)

// ---- the story (tick, kind, ...) ----
const S = []
const arr = (id) => S.push({ t: J[id]._t, k: 'arrive', id })
const dec = (t, id, action, targets, mask = [5, 6]) => S.push({ t, k: 'decide', id, action, targets, mask })
const rej = (t, id, gpu, reason) => S.push({ t, k: 'reject', id, gpu, reason })
const start = (t, id, gpus) => S.push({ t, k: 'start', id, gpus })
const done = (t, id) => S.push({ t, k: 'done', id })
const fail = (t, id, reason, requeued) => S.push({ t, k: 'fail', id, reason, requeued })
const disable = (t, g) => S.push({ t, k: 'disable', g })
const restore = (t, g) => S.push({ t, k: 'restore', g })

for (const id of Object.keys(J)) arr(id)
// j01 -> standard-0
dec(1, 'j01', 'assign', ['standard-0']); start(1, 'j01', ['standard-0']); done(15, 'j01')
// j02 high 60GB -> premium-0 (this one heats the chef)
dec(2, 'j02', 'assign', ['premium-0'], [2, 6]); start(2, 'j02', ['premium-0']); done(19, 'j02')
// j03 low -> held in the delivery area, released later
dec(3, 'j03', 'hold', [], [5, 6]); dec(12, 'j03', 'assign', ['standard-2'], [3, 6]); start(12, 'j03', ['standard-2']); done(21, 'j03')
// j04 vip -> premium-1
dec(4, 'j04', 'assign', ['premium-1'], [2, 6]); start(4, 'j04', ['premium-1']); done(16, 'j04')
dec(5, 'j05', 'assign', ['standard-1'], [4, 6]); start(5, 'j05', ['standard-1']); done(17, 'j05')
dec(6, 'j06', 'hold', [], [3, 6]); dec(14, 'j06', 'assign', ['standard-0'], [4, 6]); start(14, 'j06', ['standard-0']); done(24, 'j06')
dec(8, 'j07', 'assign', ['standard-2'], [3, 6]); start(8, 'j07', ['standard-2']); done(18, 'j07')
dec(9, 'j08', 'assign', ['standard-0'], [3, 6]); start(9, 'j08', ['standard-0']); done(17, 'j08')
// j09 medium 40GB: standard is full -> cloud takeaway
dec(11, 'j09', 'cloud', ['cloud-0'], [1, 6]); start(11, 'j09', ['cloud-0']); done(20, 'j09')
// j10 vip 40GB: tries premium-1, memory clash (j04 holds 70GB), then goes to cloud
dec(13, 'j10', 'assign', ['premium-1'], [3, 6]); rej(13, 'j10', 'premium-1', 'memory')
dec(13, 'j10', 'cloud', ['cloud-0'], [1, 6]); start(13, 'j10', ['cloud-0']); done(21, 'j10')
// j11 high: premium-0 is hot -> safety layer rejects on thermal, scheduler reroutes
dec(15, 'j11', 'assign', ['premium-0'], [3, 6]); rej(15, 'j11', 'premium-0', 'thermal')
dec(15, 'j11', 'assign', ['premium-1'], [2, 6]); start(15, 'j11', ['premium-1']); done(25, 'j11')
dec(17, 'j12', 'hold', [], [2, 6]); dec(22, 'j12', 'assign', ['standard-1'], [3, 6]); start(22, 'j12', ['standard-1']); done(30, 'j12')
// spike at 22-24
dec(22, 'j13', 'assign', ['standard-2'], [3, 6]); start(22, 'j13', ['standard-2']); done(31, 'j13')
dec(23, 'j14', 'assign', ['standard-0'], [3, 6]); start(23, 'j14', ['standard-0']); done(33, 'j14')
dec(23, 'j15', 'hold', [], [2, 6]); dec(31, 'j15', 'assign', ['standard-1'], [3, 6]); start(31, 'j15', ['standard-1']); done(39, 'j15')
// j16 vip: premium-0 still critical (rejected), premium-1 busy -> cloud
dec(24, 'j16', 'assign', ['premium-0'], [3, 6]); rej(24, 'j16', 'premium-0', 'thermal')
dec(24, 'j16', 'cloud', ['cloud-0'], [1, 6]); start(24, 'j16', ['cloud-0']); done(33, 'j16')
dec(30, 'j17', 'assign', ['premium-1'], [4, 6]); start(30, 'j17', ['premium-1']); done(40, 'j17')
dec(34, 'j18', 'assign', ['standard-2'], [4, 6]); start(34, 'j18', ['standard-2']); done(43, 'j18')
dec(38, 'j19', 'hold', [], [3, 6]); dec(45, 'j19', 'assign', ['standard-0'], [3, 6]); start(45, 'j19', ['standard-0']); done(52, 'j19')
// j20 starts on standard-1 and the GPU gets disabled under it at t=42
dec(41, 'j20', 'assign', ['standard-1'], [4, 6]); start(41, 'j20', ['standard-1'])
disable(42, 'standard-1'); fail(42, 'j20', 'gpu_down', true)
dec(43, 'j20', 'assign', ['standard-0'], [3, 6]); start(43, 'j20', ['standard-0']); done(55, 'j20') // deadline missed -> sad cloud
dec(44, 'j21', 'assign', ['premium-1'], [2, 6]); start(44, 'j21', ['premium-1']); done(52, 'j21')
restore(54, 'standard-1')
dec(48, 'j22', 'assign', ['standard-2'], [3, 6]); start(48, 'j22', ['standard-2']); done(55, 'j22')

// ---- walk the ticks ----
const events = []
let seq = 0
const push = (t, e) => events.push({ seq: ++seq, t, ...e })
const running = {} // gpu -> Set(jobs)
const jobState = {}
const temp = Object.fromEntries(GPUS.map((g) => [g.id, g.temp0]))
const disabled = new Set()
const lvl = {}
let received = 0, completed = 0, onTimeN = 0, costTotal = 0, incidents = 0
const waits = []
const arrivedAt = {}
const startedWait = {}
const order = { arrive: 0, reject: 1, decide: 1, start: 2, fail: 2, done: 3, disable: 0, restore: 0 }
const healthOf = (id) => disabled.has(id) ? 'down' : temp[id] >= 85 ? 'critical' : temp[id] >= 75 ? 'warning' : 'normal'

for (let t = 0; t <= TICKS; t++) {
  const todo = S.filter((e) => e.t === t).sort((a, b) => order[a.k] - order[b.k])
  for (const e of todo) {
    if (e.k === 'arrive') {
      const { _t, ...job } = J[e.id]
      push(t, { type: 'JOB_ARRIVED', job }); received++; arrivedAt[e.id] = t; jobState[e.id] = 'waiting'
    } else if (e.k === 'decide') {
      const waiting = Object.values(jobState).filter((s) => s === 'waiting').length
      const target = e.targets[0]
      const job = J[e.id]
      const tier = target ? GPUS.find((g) => g.id === target).tier : 'standard'
      push(t, {
        type: 'DECISION', job_id: e.id, action: e.action, target_gpu_ids: e.targets, scheduler: 'fallback_heuristic',
        factors: {
          queue_len: waiting,
          deadline_slack: job.deadline_t - t - job.duration_s,
          pred_temp: target ? Math.round(temp[target] + (running[target]?.size ? 2 : -1) * Math.min(job.duration_s, 6)) : 0,
          cost: Math.round(job.duration_s * RATE[tier] * 10) / 10,
        },
        mask_summary: { valid: e.mask[0], total: e.mask[1] },
      })
    } else if (e.k === 'reject') {
      push(t, { type: 'ALLOCATION_REJECTED', job_id: e.id, gpu_id: e.gpu, reason: e.reason })
    } else if (e.k === 'start') {
      const eta = t + J[e.id].duration_s
      push(t, { type: 'JOB_STARTED', job_id: e.id, gpu_ids: e.gpus, eta_t: eta })
      for (const g of e.gpus) (running[g] ??= new Set()).add(e.id)
      jobState[e.id] = 'running'; startedWait[e.id] = t - arrivedAt[e.id]
    } else if (e.k === 'fail') {
      push(t, { type: 'JOB_FAILED', job_id: e.id, reason: e.reason, requeued: e.requeued })
      for (const g in running) running[g].delete(e.id)
      jobState[e.id] = 'waiting'
    } else if (e.k === 'done') {
      const j = J[e.id]
      const g = Object.keys(running).find((k) => running[k].has(e.id))
      const tier = GPUS.find((x) => x.id === g).tier
      const cost = Math.round(j.duration_s * RATE[tier] * 10) / 10
      const onTime = t <= j.deadline_t
      const wait = t - arrivedAt[e.id] - j.duration_s
      push(t, { type: 'JOB_COMPLETED', job_id: e.id, on_time: onTime, wait_s: Math.max(0, wait), cost })
      running[g].delete(e.id); jobState[e.id] = 'done'
      completed++; if (onTime) onTimeN++; costTotal += cost; waits.push(Math.max(0, wait))
    } else if (e.k === 'disable') {
      disabled.add(e.g); push(t, { type: 'GPU_DISABLED', gpu_id: e.g })
    } else if (e.k === 'restore') {
      disabled.delete(e.g); push(t, { type: 'GPU_RESTORED', gpu_id: e.g })
    }
  }
  // telemetry: premium-0 active +2C/tick (contract default, illustrative), others +0.6; idle -1C/tick; cloud stays cool
  const utils = []
  for (const g of GPUS) {
    const n = running[g.id]?.size ?? 0
    if (t > 0 && g.tier !== 'cloud') {
      const up = g.id === 'premium-0' ? 2 : 0.6 // premium-0 is the scripted hot chef; others run cooler
      temp[g.id] = Math.round(Math.max(38, temp[g.id] + (n > 0 && !disabled.has(g.id) ? up : -1)) * 10) / 10
    }
    const used = [...(running[g.id] ?? [])].reduce((s, id) => s + J[id].vram_gb, 0)
    const util = disabled.has(g.id) ? 0 : n ? Math.min(98, 52 + 18 * n + Math.round(used / g.vram_gb * 20)) : 0
    if (g.tier !== 'cloud') utils.push(util)
    const health = healthOf(g.id)
    push(t, { type: 'GPU_TELEMETRY', gpu_id: g.id, temp: temp[g.id], util, vram_used_gb: used, health })
    const rank = { normal: 0, warning: 1, critical: 2, down: 0 }
    if (g.tier !== 'cloud' && rank[health] > (lvl[g.id] ?? 0)) {
      push(t, { type: 'THERMAL_WARNING', gpu_id: g.id, level: health, temp: temp[g.id] })
      if (health === 'critical') incidents++
    }
    lvl[g.id] = rank[health]
  }
  const sorted = [...waits].sort((a, b) => a - b)
  push(t, {
    type: 'METRICS', completed, waiting: Object.values(jobState).filter((s) => s === 'waiting').length, received,
    avg_wait_s: waits.length ? Math.round((waits.reduce((a, b) => a + b, 0) / waits.length) * 10) / 10 : 0,
    p95_wait_s: sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] : 0,
    slo_rate: completed ? Math.round((onTimeN / completed) * 1000) / 1000 : 1,
    avg_util: Math.round((utils.reduce((a, b) => a + b, 0) / utils.length) * 10) / 10,
    cost: Math.round(costTotal * 10) / 10, thermal_incidents: incidents, starved: 0,
  })
}

const out = { run_id: 'replay-sample', note: 'SIMULATED hand-scripted recording for UI development. Not produced by the backend.', config, events }
writeFileSync(new URL('../public/sample-events.json', import.meta.url), JSON.stringify(out))
const peak = Math.max(...events.filter((e) => e.type === 'GPU_TELEMETRY' && e.gpu_id === 'premium-0').map((e) => e.temp))
const crit = events.find((e) => e.type === 'THERMAL_WARNING' && e.level === 'critical')
console.log(`events=${events.length} seq=${seq} ticks=${TICKS} premium-0 peak=${peak}C first critical tick=${crit?.t} completed=${completed} incidents=${incidents}`)
