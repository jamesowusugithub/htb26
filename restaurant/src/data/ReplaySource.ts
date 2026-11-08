import type { EventSource, SourceHandlers } from './source'
import { applyEvent, stateFromConfig } from './store'
import type { Config, SimEvent } from './types'
import { setTraceMeta, type TraceMeta } from './traceMeta'

interface Recording {
  run_id: string
  note?: string
  trace_meta?: TraceMeta
  config: Config
  events: SimEvent[]
}

export interface OrderSpec { gpus: number; priority: 'high' | 'spot'; duration_min: number }
interface Order extends OrderSpec { at_min: number }
const DEFAULT_CLOUD = { nodes: 1, gpus_per_node: 8, overflow_wait_min: 30, price_multiplier: 1.0 }

/** Plays public/sample-events.json. Clearly NOT live: the UI shows a REPLAY badge. */
export class ReplaySource implements EventSource {
  readonly kind = 'replay' as const
  private h!: SourceHandlers
  private rec!: Recording
  private timer: number | undefined
  private cursor = 0 // next event index
  private clock = 0 // fractional tick
  private playing = true
  private speed = 1
  private endedAt = 0
  private orders: Order[] = []
  private trace = ''
  private api = ''
  duration = 0
  get canOrder() { return !!this.api && !!this.trace }
  get orderCount() { return this.orders.length }
  get tick() { return Math.floor(this.clock) }

  async start(h: SourceHandlers) {
    this.h = h
    // ?trace=NAME plays a recording made from the REAL trace: from our backend if ?api=URL is given, else public/traces/NAME.json
    const q = new URLSearchParams(location.search)
    const trace = q.get('trace'), api = q.get('api')
    this.trace = trace ?? ''; this.api = api ? api.replace(/\/$/, '') : ''
    const url = trace ? (api ? `${api.replace(/\/$/, '')}/restaurant/trace?policy=${encodeURIComponent(trace)}` : `${import.meta.env.BASE_URL}traces/${trace}.json`) : `${import.meta.env.BASE_URL}sample-events.json`
    this.rec = this.canOrder ? await this.fetchRec() : await this.fetchStatic(url)
    setTraceMeta(this.rec.trace_meta ?? null)
    this.duration = this.rec.events.reduce((m, e) => Math.max(m, e.t), 0)
    h.onConfig(this.rec.config)
    h.onStatus('open', 'replay')
    this.rebuild(0)
    this.timer = window.setInterval(() => this.step(0.1), 100)
  }

  private async fetchStatic(url: string): Promise<Recording> {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
    return (await res.json()) as Recording
  }

  /** Ask OUR backend for the recording: the trained scheduler makes every decision, including for new orders and the simulated takeaway. */
  private async fetchRec(): Promise<Recording> {
    const res = await fetch(`${this.api}/restaurant/trace`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ policy: this.trace, orders: this.orders, cloud: DEFAULT_CLOUD }) })
    if (!res.ok) throw new Error(`backend said ${res.status}: ${(await res.text()).slice(0, 160)}`)
    return (await res.json()) as Recording
  }

  /** New orders (jobs not in the trace) are placed one tick ahead of the playhead; the past of the recording does not change. */
  async placeOrders(specs: OrderSpec[]) {
    if (!this.canOrder) throw new Error('orders need ?api=<backend URL>')
    const keep = Math.floor(this.clock), at = keep + 1
    const before = this.orders.length
    this.orders.push(...specs.map((s) => ({ ...s, at_min: at })))
    try {
      this.rec = await this.fetchRec()
    } catch (e) {
      this.orders.length = before
      throw e
    }
    setTraceMeta(this.rec.trace_meta ?? null)
    this.duration = this.rec.events.reduce((m, e) => Math.max(m, e.t), 0)
    this.h.onConfig(this.rec.config)
    this.rebuild(keep)
  }

  stop() {
    if (this.timer) window.clearInterval(this.timer)
  }

  setPlaying(p: boolean) { this.playing = p }
  setSpeed(s: number) { this.speed = s }
  reset() { this.rebuild(0) }

  seek(t: number) { this.rebuild(Math.max(0, Math.min(this.duration, Math.round(t)))) }

  /** Reduce events up to and including tick t into a state and hand it over wholesale. */
  private rebuild(t: number) {
    const s = stateFromConfig(this.rec.config)
    let i = 0
    while (i < this.rec.events.length && this.rec.events[i].t <= t) applyEvent(s, this.rec.events[i++])
    this.cursor = i
    this.clock = t
    this.endedAt = 0
    this.h.onState(s)
    this.h.onStatus('open', 'replay')
  }

  private step(dt: number) {
    if (!this.playing) return
    if (this.cursor >= this.rec.events.length) {
      // finished: loop after a short beat so a kiosk never sits dead
      this.endedAt += dt
      if (this.endedAt > 3) this.rebuild(0)
      return
    }
    this.clock += this.speed * dt
    const upto = Math.floor(this.clock)
    const batch: SimEvent[] = []
    while (this.cursor < this.rec.events.length && this.rec.events[this.cursor].t <= upto) batch.push(this.rec.events[this.cursor++])
    if (batch.length) this.h.onEvents(batch)
  }
}
