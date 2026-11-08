import type { GpuView, JobView, SimState } from '../data/types'
import { isTrace } from '../data/traceMeta'

const TIER: Record<string, string> = { premium: 'Premium', standard: 'Standard', cloud: 'Cloud' }
const ZONE: Record<string, string> = { premium: 'Kitchen A', standard: 'Kitchen B', cloud: 'Takeaway' }

function Bar({ pct, tone, label }: { pct: number; tone: string; label: string }) {
  return (
    <div className="bar" role="progressbar" aria-label={label} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <span className={tone} style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  )
}

function Card({ g, jobs, state }: { g: GpuView; jobs: JobView[]; state: SimState }) {
  const th = state.thresholds
  const tone = g.disabled ? 'tone-off' : g.temp >= th.critical ? 'tone-bad' : g.temp >= th.warning ? 'tone-warn' : 'tone-ok'
  const health = g.disabled ? 'down' : g.health
  return (
    <li className={`gpu gpu-${health}`} data-testid={`gpu-${g.id}`}>
      <div className="gpu-head">
        <strong className="mono">{g.name ?? g.id}</strong>
        <span className="chip">{(isTrace() ? ZONE : TIER)[g.tier] ?? g.tier}</span>
        <span className={`chip health-${health}`}>{health}</span>
      </div>
      <div className="gpu-row"><span>Util</span><Bar pct={g.util} tone="tone-blue" label={`${g.id} utilisation`} /><b className="mono">{Math.round(g.util)}%</b></div>
      <div className="gpu-row"><span>{isTrace() ? 'GPUs' : 'VRAM'}</span><Bar pct={g.tier === 'cloud' && !isTrace() ? 0 : (g.vram_used_gb / g.vram_gb) * 100} tone="tone-blue" label={`${g.id} memory`} /><b className="mono">{g.vram_used_gb}/{g.tier === 'cloud' && !isTrace() ? 'pool' : g.vram_gb}{isTrace() ? ' GPUs' : ' GB'}</b></div>
      {g.tier === 'cloud' && isTrace() ? <div className="gpu-row"><span>Temp</span><span className="muted">n/a (cloud, not measured)</span></div> : <div className="gpu-row"><span>Temp</span><Bar pct={((g.temp - 30) / 70) * 100} tone={tone} label={`${g.id} temperature`} /><b className="mono">{g.temp.toFixed(0)}&deg;C</b></div>}
      <div className="gpu-job">
        {jobs.length === 0 ? <span className="muted">no active job</span> : jobs.map((j) => (
          <span key={j.job.id} className="job"><i className={`dot prio-${j.job.priority}`} aria-hidden />{j.job.id} <span className="muted">done at t={j.etaT ?? '?'}</span></span>
        ))}
      </div>
    </li>
  )
}

export function GpuCards({ state }: { state: SimState }) {
  const running = Object.values(state.jobs).filter((j) => j.status === 'running')
  return (
    <section className="card" aria-labelledby="h-gpus">
      <h2 id="h-gpus">Chefs (GPUs) <span className="sim">simulated telemetry</span></h2>
      {state.gpuOrder.length === 0 ? <p className="muted">No GPUs yet.</p> : (
        <ul className="gpus">
          {state.gpuOrder.map((id) => (
            <Card key={id} g={state.gpus[id]} state={state} jobs={running.filter((j) => j.gpuIds.includes(id))} />
          ))}
        </ul>
      )}
    </section>
  )
}
