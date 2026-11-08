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
  duration = 0

  async start(h: SourceHandlers) {
    this.h = h
    // ?trace=NAME plays a recording made from the REAL trace: from our backend if ?api=URL is given, else public/traces/NAME.json
    const q = new URLSearchParams(location.search)
    const trace = q.get('trace'), api = q.get('api')
    const url = trace ? (api ? `${api.replace(/\/$/, '')}/restaurant/trace?policy=${encodeURIComponent(trace)}` : `${import.meta.env.BASE_URL}traces/${trace}.json`) : `${import.meta.env.BASE_URL}sample-events.json`
    const res = await fetch(url)
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
    this.rec = (await res.json()) as Recording
    setTraceMeta(this.rec.trace_meta ?? null)
    this.duration = this.rec.events.reduce((m, e) => Math.max(m, e.t), 0)
    h.onConfig(this.rec.config)
    h.onStatus('open', 'replay')
    this.rebuild(0)
    this.timer = window.setInterval(() => this.step(0.1), 100)
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
