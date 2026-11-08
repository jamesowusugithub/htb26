import { LiveSource } from './LiveSource'
import { ReplaySource, type OrderSpec } from './ReplaySource'
import type { ConnStatus, EventSource, SourceKind } from './source'
import { applyEvent, emptyState, snapshotToState, stateFromConfig } from './store'
import type { Config, SimEvent, SimState } from './types'

export interface UiMeta {
  kind: SourceKind | 'none'
  status: ConnStatus
  fallbackReason: string | null
  speed: number
  playing: boolean
  runId: string | null
  duration: number
  error: string | null
}

type Listener = () => void

/** Single owner of state. React reads it via subscribe(); Phaser via onEvents/onReset. */
export class Controller {
  state: SimState = emptyState()
  config: Config | null = null
  meta: UiMeta = { kind: 'none', status: 'connecting', fallbackReason: null, speed: 1, playing: false, runId: null, duration: 0, error: null }
  private source: EventSource | null = null
  private listeners = new Set<Listener>()
  private fxListeners = new Set<(evs: SimEvent[]) => void>()
  private resetListeners = new Set<() => void>()
  version = 0
  private notifyQueued = false

  subscribe = (l: Listener) => { this.listeners.add(l); return () => { this.listeners.delete(l) } }
  getVersion = () => this.version
  onEvents(l: (evs: SimEvent[]) => void) { this.fxListeners.add(l); return () => { this.fxListeners.delete(l) } }
  onReset(l: () => void) { this.resetListeners.add(l); return () => { this.resetListeners.delete(l) } }

  private notify() {
    this.version++
    if (this.notifyQueued) return
    this.notifyQueued = true
    queueMicrotask(() => { this.notifyQueued = false; this.listeners.forEach((l) => l()) })
  }

  private setMeta(p: Partial<UiMeta>) { this.meta = { ...this.meta, ...p }; this.notify() }

  async init(wanted: SourceKind, requestedRun: string | null) {
    if (wanted === 'replay') return this.attach(new ReplaySource(), null)
    try {
      await this.attach(new LiveSource(requestedRun), null)
    } catch (e) {
      console.warn('live source failed, falling back to replay', e)
      this.source?.stop()
      this.config = null
      this.state = emptyState()
      await this.attach(new ReplaySource(), 'backend offline - replay mode')
    }
  }

  private async attach(src: EventSource, fallbackReason: string | null) {
    this.source = src
    this.setMeta({ kind: src.kind, fallbackReason, status: 'connecting', error: null, playing: src.kind === 'replay', speed: 1 })
    await src.start({
      onConfig: (c) => { this.config = c; this.state = stateFromConfig(c); this.notify() },
      onEvents: (evs) => {
        for (const e of evs) applyEvent(this.state, e)
        this.fxListeners.forEach((l) => l(evs))
        this.notify()
      },
      onSnapshot: (raw) => {
        this.state = snapshotToState(raw, this.config, this.state)
        this.resetListeners.forEach((l) => l())
        const r = raw as { ticking?: unknown; speed?: unknown }
        this.setMeta({
          ...(typeof r.ticking === 'boolean' ? { playing: r.ticking } : {}),
          ...(typeof r.speed === 'number' ? { speed: r.speed } : {}),
        })
      },
      onState: (s) => {
        this.state = s
        this.resetListeners.forEach((l) => l())
        this.notify()
      },
      onStatus: (status, detail) => this.setMeta({ status, error: status === 'error' ? (detail ?? null) : this.meta.error }),
    })
    if (src instanceof LiveSource) this.setMeta({ runId: src.runId })
    this.setMeta({ duration: src.duration ?? 0 })
  }

  get isReplay() { return this.meta.kind === 'replay' }
  get canOrder() { return this.source instanceof ReplaySource && this.source.canOrder }
  get orderCount() { return this.source instanceof ReplaySource ? this.source.orderCount : 0 }
  /** New orders go to the backend, where the trained scheduler decides; the animation then reloads at the same tick. */
  async placeOrders(specs: OrderSpec[]) {
    if (!(this.source instanceof ReplaySource)) throw new Error('no recording attached')
    try {
      await this.source.placeOrders(specs)
      this.setMeta({ error: null })
    } catch (e) {
      this.setMeta({ error: `new order: ${String(e)}` })
      throw e
    }
  }

  // ---- controls ----
  async call(path: string, body?: unknown) {
    if (!(this.source instanceof LiveSource)) throw new Error('replay mode: controls are disabled')
    try {
      await this.source.call(path, body)
      this.setMeta({ error: null })
    } catch (e) {
      this.setMeta({ error: `${path}: ${String(e)}` })
      throw e
    }
  }
  async play(p: boolean) {
    if (this.source instanceof LiveSource) await this.call(p ? '/start' : '/pause')
    else this.source?.setPlaying?.(p)
    this.setMeta({ playing: p })
  }
  async setSpeed(s: number) {
    if (this.source instanceof LiveSource) await this.call('/speed', { speed: s })
    else this.source?.setSpeed?.(s)
    this.setMeta({ speed: s })
  }
  async reset() {
    if (this.source instanceof LiveSource) { await this.call('/reset'); await this.source.resync() }
    else this.source?.reset?.()
  }
  seek(t: number) { this.source?.seek?.(t) }
  stop() { this.source?.stop() }
}
