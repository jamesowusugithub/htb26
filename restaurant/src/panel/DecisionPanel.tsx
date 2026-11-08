import { ArrowRight, Cloud, Hourglass, Split, Hand } from 'lucide-react'
import type { SimState } from '../data/types'
import { SchedulerLabel } from './Header'
import { isTrace } from '../data/traceMeta'

export function DecisionPanel({ state }: { state: SimState }) {
  const d = state.lastDecision
  const trace = isTrace()
  const job = d ? state.jobs[d.job_id]?.job : undefined
  const rej = state.rejections[state.rejections.length - 1]
  const what = !d ? null
    : d.action === 'assign' ? { icon: <ArrowRight size={16} aria-hidden />, text: `Send to ${d.target_gpu_ids.join(', ').toUpperCase()}` }
    : d.action === 'cloud' ? { icon: <Cloud size={16} aria-hidden />, text: 'Send to cloud takeaway' }
    : d.action === 'hold' ? { icon: <Hourglass size={16} aria-hidden />, text: 'Hold in waiting area' }
    : { icon: <Split size={16} aria-hidden />, text: `Split across ${d.target_gpu_ids.join(', ').toUpperCase()}` }
  return (
    <section className="card" aria-labelledby="h-decision">
      <h2 id="h-decision"><Hand size={15} aria-hidden /> Manager decision</h2>
      {!d ? (
        <p className="muted">Waiting for the manager to decide on a customer...</p>
      ) : (
        <div aria-live="polite">
          <div className="decision-head">
            <span className="mono">{d.job_id}</span>
            {job && <span className={`chip prio-${job.priority}`}>{job.priority}</span>}
            <span className="decision-action">{what!.icon}{what!.text}</span>
          </div>
          <dl className="factors">
            <div><dt>Queue length</dt><dd>{d.factors.queue_len}</dd></div>
            {trace
              ? <div><dt>Predicted runtime</dt><dd>{d.factors.hint_min != null ? `${d.factors.hint_min} min` : 'n/a'}{job ? <small> (actual {job.duration_s} min)</small> : null}</dd></div>
              : <div><dt>Deadline slack</dt><dd>{d.factors.deadline_slack} s</dd></div>}
            <div><dt>{trace ? 'Chef temp (proxy)' : 'Predicted temp'}</dt><dd>{d.factors.pred_temp ? `${d.factors.pred_temp} C` : 'n/a'}</dd></div>
            {!trace && <div><dt>Cost</dt><dd>{d.factors.cost} sim$</dd></div>}
            {d.mask_summary.total > 0 && <div><dt>Choices offered</dt><dd>{d.mask_summary.valid} of {d.mask_summary.total}</dd></div>}
            <div className="wide"><dt>Scheduler</dt><dd><SchedulerLabel s={d.scheduler} /></dd></div>
          </dl>
        </div>
      )}
      {rej && state.t - rej.t < 6 && (
        <p className="reject">Safety layer said no: {rej.job_id} on {rej.gpu_id} ({rej.reason})</p>
      )}
      <p className="caption">{trace ? 'predicted runtime is our hint model; the actual runtime is only known afterwards' : 'factors shown, not a full explanation of the policy'}</p>
    </section>
  )
}
