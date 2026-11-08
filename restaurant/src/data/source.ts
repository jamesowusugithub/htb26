import type { Config, SimEvent, SimState } from './types'

export type SourceKind = 'live' | 'replay'
export type ConnStatus = 'connecting' | 'open' | 'reconnecting' | 'ended' | 'error'

export interface SourceHandlers {
  onConfig(c: Config): void
  /** Ordered, de-duplicated events. */
  onEvents(events: SimEvent[]): void
  /** Authoritative full state; replaces everything and must reset animation. */
  onSnapshot(raw: unknown): void
  /** Replay seek/reset: already-reduced authoritative state. */
  onState(s: SimState): void
  onStatus(s: ConnStatus, detail?: string): void
}

export interface RunControl {
  runId: string | null
  call(path: string, body?: unknown): Promise<unknown>
}

export interface EventSource {
  readonly kind: SourceKind
  start(h: SourceHandlers): Promise<void>
  stop(): void
  /** Replay only: jump to tick. */
  seek?(t: number): void
  /** local play state, replay only */
  setPlaying?(p: boolean): void
  setSpeed?(s: number): void
  reset?(): void
  readonly duration?: number
}
