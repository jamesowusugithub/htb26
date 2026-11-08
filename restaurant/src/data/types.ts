// Types mirror contracts/CONTRACT.md (frozen). Backend is authoritative.
export type Priority = 'low' | 'medium' | 'high' | 'vip'
export type TierName = 'premium' | 'standard' | 'cloud'
export type Health = 'normal' | 'warning' | 'critical' | 'down'
export type SchedulerName = 'rl' | 'fifo' | 'priority' | 'hint' | 'fallback_heuristic'
export type Action = 'assign' | 'cloud' | 'hold' | 'split'

export interface Job {
  id: string
  priority: Priority
  vram_gb: number
  compute_units: number
  duration_s: number
  deadline_t: number
  splittable: boolean
  tiers: TierName[]
  /** real-trace mode only */
  hint_min?: number
  gpus?: number
  arrival_t?: number
}

interface Base {
  seq: number
  t: number
}
export type SimEvent =
  | (Base & { type: 'SCHEDULER_CHANGED'; scheduler: SchedulerName })
  | (Base & { type: 'JOB_ARRIVED'; job: Job })
  | (Base & {
      type: 'DECISION'
      job_id: string
      action: Action
      target_gpu_ids: string[]
      scheduler: SchedulerName
      factors: { queue_len: number; deadline_slack: number; pred_temp: number; cost: number; hint_min?: number; waited_min?: number }
      mask_summary: { valid: number; total: number }
    })
  | (Base & { type: 'ALLOCATION_REJECTED'; job_id: string; gpu_id: string; reason: 'memory' | 'tier' | 'thermal' | 'down' })
  | (Base & { type: 'JOB_STARTED'; job_id: string; gpu_ids: string[]; eta_t: number })
  | (Base & { type: 'JOB_COMPLETED'; job_id: string; on_time: boolean; wait_s: number; cost: number })
  | (Base & { type: 'JOB_FAILED'; job_id: string; reason: string; requeued: boolean })
  | (Base & { type: 'GPU_TELEMETRY'; gpu_id: string; temp: number; util: number; vram_used_gb: number; health: Health })
  | (Base & { type: 'THERMAL_WARNING'; gpu_id: string; level: 'warning' | 'critical'; temp: number })
  | (Base & { type: 'GPU_DISABLED'; gpu_id: string })
  | (Base & { type: 'GPU_RESTORED'; gpu_id: string })
  | (Base & { type: 'METRICS' } & Metrics)

export interface Metrics {
  completed: number
  waiting: number
  received: number
  avg_wait_s: number
  p95_wait_s: number
  slo_rate: number
  avg_util: number
  cost: number
  thermal_incidents: number
  starved: number
}

export interface GpuConfig {
  name?: string
  id: string
  tier: TierName
  vram_gb: number
  compute: number
}
export interface Config {
  nodes: { id: string; gpus: GpuConfig[] }[]
  thresholds: { warning: number; critical: number }
  overflow_threshold: number
  scheduler: SchedulerName
  trace?: boolean
}

export interface Decision {
  job_id: string
  action: Action
  target_gpu_ids: string[]
  scheduler: SchedulerName
  factors: { queue_len: number; deadline_slack: number; pred_temp: number; cost: number; hint_min?: number; waited_min?: number }
  mask_summary: { valid: number; total: number }
  t: number
  seq: number
}

export type JobStatus = 'arrived' | 'assigned' | 'held' | 'cloud' | 'running' | 'done' | 'failed'
export interface JobView {
  job: Job
  status: JobStatus
  gpuIds: string[]
  etaT?: number
  onTime?: boolean
  arrivedSeq: number
  doneT?: number
}

export interface GpuView {
  name?: string
  id: string
  tier: TierName
  vram_gb: number
  compute: number
  temp: number
  util: number
  vram_used_gb: number
  health: Health
  disabled: boolean
}

export interface SimState {
  t: number
  lastSeq: number
  gpuOrder: string[]
  gpus: Record<string, GpuView>
  jobs: Record<string, JobView>
  metrics: Metrics
  scheduler: SchedulerName | null
  lastDecision: Decision | null
  thresholds: { warning: number; critical: number }
  coins: number
  missed: number
  rejections: { t: number; job_id: string; gpu_id: string; reason: string }[]
}

export const EMPTY_METRICS: Metrics = {
  completed: 0, waiting: 0, received: 0, avg_wait_s: 0, p95_wait_s: 0,
  slo_rate: 1, avg_util: 0, cost: 0, thermal_incidents: 0, starved: 0,
}

/** Cosmetic effects the Phaser scene may play. Never authoritative. */
export type FxEvent = SimEvent
