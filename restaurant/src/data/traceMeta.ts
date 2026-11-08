// Set when the animation plays a recording generated from the REAL Alibaba trace (scheduler/restaurant_export.py).
// In that mode the UI shows only what the trace contains: no VRAM, deadlines, SLO or cost.
export interface TraceMeta {
  source: string; pool: string; window_start_day: number; window_minutes: number; jobs: number; kitchen_nodes: number
  gpus_per_node: number; scale_note: string; scheduler: string; scheduler_label: string; thermal: string; hint: string; time_unit: string
}
let meta: TraceMeta | null = null
export const setTraceMeta = (m: TraceMeta | null) => { meta = m }
export const traceMeta = () => meta
export const isTrace = () => meta !== null
