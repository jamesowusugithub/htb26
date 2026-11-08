import type { EventSource, SourceHandlers } from './source'
import type { Config, SimEvent } from './types'

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

async function json<T>(url: string, init?: RequestInit, timeoutMs = 4000): Promise<T> {
  const ctl = new AbortController()
  const to = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const r = await fetch(url, { ...init, signal: ctl.signal, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
    if (!r.ok) throw new Error(`${init?.method ?? 'GET'} ${url} -> HTTP ${r.status}`)
    return (await r.json()) as T
  } finally {
    clearTimeout(to)
  }
}

interface Frame { seq_from: number; seq_to: number; t: number; events: SimEvent[]; reset?: boolean }

export class LiveSource implements EventSource {
  readonly kind = 'live' as const
  runId: string | null = null
  private h!: SourceHandlers
  private ws: WebSocket | null = null
  private stopped = false
  private lastSeq = 0
  private attempts = 0
  private resyncing = false
  private resyncAgain = false
  private buffer: Frame[] = []
  private retryTimer: number | undefined

  constructor(private requestedRun: string | null) {}

  async start(h: SourceHandlers) {
    this.h = h
    h.onStatus('connecting')
    // Throws when the backend is unreachable; the controller then falls back to replay (loudly).
    const cfg = await json<Config>(`${API_URL}/api/rest/config`, undefined, 2500)
    h.onConfig(cfg)
    this.runId = this.requestedRun
    if (!this.runId) {
      // no ?run=: attach to the backend's canonical shared demo run (same one the rack view attaches to)
      const r = await json<{ run_id: string }>(`${API_URL}/api/rest/runs/demo`, { method: 'POST', body: '{}' })
      this.runId = r.run_id
    }
    await this.resync()
    this.connect()
  }

  stop() {
    this.stopped = true
    window.clearTimeout(this.retryTimer)
    this.ws?.close()
  }

  async call(path: string, body?: unknown) {
    if (!this.runId) throw new Error('no run')
    return json<unknown>(`${API_URL}/api/rest/runs/${this.runId}${path}`, { method: 'POST', body: JSON.stringify(body ?? {}) })
  }

  private wsUrl() {
    return `${API_URL.replace(/^http/, 'ws')}/ws/rest/${this.runId}?from_seq=${this.lastSeq}`
  }

  private connect() {
    if (this.stopped) return
    const ws = new WebSocket(this.wsUrl())
    this.ws = ws
    ws.onopen = () => {
      this.attempts = 0
      this.h.onStatus('open')
      void this.resync() // reconnect => always resync from snapshot
    }
    ws.onmessage = (m) => {
      try { this.onFrame(JSON.parse(String(m.data)) as Frame) } catch (e) { console.warn('bad WS frame', e) }
    }
    ws.onerror = () => { /* onclose follows */ }
    ws.onclose = () => {
      if (this.stopped) return
      this.h.onStatus('reconnecting')
      const delay = Math.min(8000, 500 * 2 ** this.attempts++) + Math.random() * 250
      this.retryTimer = window.setTimeout(() => this.connect(), delay)
    }
  }

  async resync() {
    if (this.resyncing) { this.resyncAgain = true; return }
    this.resyncing = true
    try {
      const snap = await json<{ last_seq?: number }>(`${API_URL}/api/rest/runs/${this.runId}/snapshot`)
      this.lastSeq = typeof snap.last_seq === 'number' ? snap.last_seq : 0
      this.h.onSnapshot(snap)
    } catch (e) {
      console.warn('snapshot failed', e)
      this.h.onStatus('error', String(e))
    } finally {
      this.resyncing = false
      const pending = this.buffer.filter((f) => !f.reset) // a reset seen mid-resync is handled by resyncAgain
      this.buffer = []
      const again = this.resyncAgain
      this.resyncAgain = false
      if (again) void this.resync()
      else pending.forEach((f) => this.onFrame(f))
    }
  }

  private onFrame(f: Frame) {
    if (f.reset) { this.buffer = []; void this.resync(); return } // run was reset server-side: snapshot is the truth
    if (this.resyncing) { this.buffer.push(f); return }
    if (!f.events?.length) return
    if (this.lastSeq > 0 && f.seq_from > this.lastSeq + 1) {
      // gap: events were missed, snapshot is the truth
      this.buffer.push(f)
      void this.resync()
      return
    }
    const fresh = f.events.filter((e) => e.seq > this.lastSeq) // dedupe by seq
    if (!fresh.length) {
      // seq went backwards => run was reset server-side; snapshot is the truth
      if (f.seq_to < this.lastSeq) void this.resync()
      return
    }
    this.lastSeq = fresh[fresh.length - 1].seq
    this.h.onEvents(fresh)
  }
}
