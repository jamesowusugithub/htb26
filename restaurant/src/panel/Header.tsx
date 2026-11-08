import { ChefHat, Radio, Film } from 'lucide-react'
import type { Controller } from '../data/controller'
import type { SchedulerName } from '../data/types'
import { isTrace, traceMeta } from '../data/traceMeta'

export function SchedulerLabel({ s }: { s: SchedulerName | null }) {
  if (!s) return <span className="sched">SCHEDULER: unknown</span>
  if (s === 'fallback_heuristic')
    return <span className="sched sched-bad" role="status">SCHEDULER: FALLBACK, NOT RL</span>
  const label = s === 'rl' ? 'RL policy (trained)' : s === 'hint' ? 'predicted runtime, shortest first' : s === 'priority' ? 'PRIORITY' : s.toUpperCase()
  return <span className="sched">SCHEDULER: {label}</span>
}

export function Header({ ctl }: { ctl: Controller }) {
  const { meta, state } = ctl
  const live = meta.kind === 'live'
  const linked = !live || meta.status === 'open' // LIVE is claimed only while the socket is actually connected
  const connLabel =
    meta.status === 'open' ? (live ? 'connected' : 'playing recording')
    : meta.status === 'reconnecting' ? 'reconnecting...'
    : meta.status === 'error' ? 'sync error'
    : 'connecting...'
  return (
    <>
      {meta.fallbackReason && (
        <div className="banner" role="alert">backend offline — replay mode</div>
      )}
      {isTrace() && (
        <div className="banner trace-banner" role="note" data-testid="trace-banner">
          {traceMeta()!.scale_note} Customers are real jobs ({traceMeta()!.jobs} from the Alibaba trace); the manager is <b>{traceMeta()!.scheduler_label}</b>; temperature is a proxy; times are in minutes.
        </div>
      )}
      <header className="topbar">
        <div className="brand">
          <ChefHat aria-hidden size={22} />
          <h1>The Restaurant</h1>
          <span className="tag">GPU scheduler as a kitchen</span>
        </div>
        <div className="badges">
          {meta.kind !== 'none' && (
            <span className={`source ${!live ? 'source-replay' : linked ? 'source-live' : 'source-lost'}`} data-testid="source-badge" aria-label={`Data source: ${!live ? 'REPLAY' : linked ? 'LIVE' : 'LIVE LINK LOST'}`}>
              {live ? <Radio size={14} aria-hidden /> : <Film size={14} aria-hidden />}
              SOURCE: {!live ? (isTrace() ? 'REAL ALIBABA TRACE (recorded run)' : 'REPLAY') : linked ? 'LIVE' : meta.status === 'connecting' ? 'CONNECTING' : 'DISCONNECTED'}
            </span>
          )}
          <span data-testid="scheduler-label"><SchedulerLabel s={state.scheduler} /></span>
          <span className="conn mono">{connLabel}</span>
          <span className="conn mono">t={state.t}</span>
          {live && meta.runId && (
            <>
              <span className="conn mono" data-testid="run-id">run {meta.runId}</span>
              <a className="conn mono" data-testid="open-other" target="_blank" rel="noreferrer"
                href={`${location.protocol}//${location.hostname}:5173/?source=rest&run=${encodeURIComponent(meta.runId)}`}>
                Open same run in rack view
              </a>
            </>
          )}
        </div>
      </header>
    </>
  )
}
