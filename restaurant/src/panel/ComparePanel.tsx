import { BarChart3 } from 'lucide-react'
import { useState } from 'react'
import type { CompareResult } from '../data/ReplaySource'
import type { Controller } from '../data/controller'

const ORDER = ['fifo', 'priority_fifo', 'sjf_hint', 'rl_ppo']
const NAME: Record<string, string> = { fifo: 'First come', priority_fifo: 'Priority', sjf_hint: 'Predicted runtime', rl_ppo: 'Trained RL' }

function ranks(a: number[]) { const idx = a.map((v, i) => [v, i]).sort((x, y) => x[0] - y[0]); const r = new Array(a.length).fill(0); idx.forEach(([, i], k) => { r[i] = k }); return r }
function spearman(x: number[], y: number[]) {
  if (x.length < 3) return NaN
  const a = ranks(x), b = ranks(y), n = x.length, ma = (n - 1) / 2
  let num = 0, da = 0, db = 0
  for (let i = 0; i < n; i++) { num += (a[i] - ma) * (b[i] - ma); da += (a[i] - ma) ** 2; db += (b[i] - ma) ** 2 }
  return num / Math.sqrt(da * db)
}

function Bars({ title, unit, get, res, lowerBetter = true }: { title: string; unit: string; get: (k: string) => number; res: CompareResult; lowerBetter?: boolean }) {
  const vals = ORDER.map((k) => get(k)), max = Math.max(...vals, 1e-9)
  const best = lowerBetter ? Math.min(...vals) : Math.max(...vals)
  return (
    <div className="cmp-chart" role="img" aria-label={`${title}: ${ORDER.map((k, i) => `${NAME[k]} ${vals[i].toFixed(1)}`).join(', ')}`}>
      <h4>{title} <small>{unit}{lowerBetter ? ' · lower is better' : ' · higher is better'}</small></h4>
      {ORDER.map((k, i) => (
        <div className="bar-row" key={k}>
          <span className="bar-name">{NAME[k]}</span>
          <span className="bar-track"><span className={`bar ${k === 'rl_ppo' ? 'rl' : ''} ${vals[i] === best ? 'best' : ''}`} style={{ width: `${Math.max(2, (vals[i] / max) * 100)}%` }} /></span>
          <span className="bar-val mono">{vals[i].toFixed(1)}</span>
        </div>
      ))}
      <span hidden>{Object.keys(res.policies).length}</span>
    </div>
  )
}

function Scatter({ pts }: { pts: { predicted_min: number; actual_min: number }[] }) {
  const P = pts.filter((p) => p.predicted_min > 0 && p.actual_min > 0)
  if (P.length < 3) return null
  const lo = Math.log10(1), hi = Math.log10(Math.max(...P.flatMap((p) => [p.predicted_min, p.actual_min]), 10))
  const W = 240, H = 200, pad = 28
  const sx = (v: number) => pad + ((Math.log10(Math.max(v, 1)) - lo) / (hi - lo)) * (W - pad - 6)
  const sy = (v: number) => H - pad - ((Math.log10(Math.max(v, 1)) - lo) / (hi - lo)) * (H - pad - 6)
  const rho = spearman(P.map((p) => p.predicted_min), P.map((p) => p.actual_min))
  return (
    <div className="cmp-chart">
      <h4>Predicted vs actual runtime <small>{P.length} jobs · rank correlation {rho.toFixed(2)}</small></h4>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Scatter of predicted against actual runtime in minutes, log scale, rank correlation ${rho.toFixed(2)}`} className="scatter">
        <line x1={pad} y1={H - pad} x2={W - 6} y2={H - pad} stroke="#8b7a5c" /><line x1={pad} y1={H - pad} x2={pad} y2={6} stroke="#8b7a5c" />
        <line x1={sx(1)} y1={sy(1)} x2={sx(10 ** hi)} y2={sy(10 ** hi)} stroke="#c8b78f" strokeDasharray="4 3" />
        {P.map((p, i) => <circle key={i} cx={sx(p.predicted_min)} cy={sy(p.actual_min)} r={2.6} fill="#1f6f5c" fillOpacity={0.6} />)}
        <text x={W / 2} y={H - 6} fontSize="9" textAnchor="middle" fill="#6b5b3e">predicted (min, log)</text>
        <text x={8} y={H / 2} fontSize="9" textAnchor="middle" fill="#6b5b3e" transform={`rotate(-90 8 ${H / 2})`}>actual (min, log)</text>
      </svg>
      <p className="note">Dashed line = perfect prediction. The model only sees job history before the window, never the true runtime.</p>
    </div>
  )
}

export function ComparePanel({ ctl }: { ctl: Controller }) {
  const [res, setRes] = useState<CompareResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!ctl.canOrder) return null
  const run = () => { setBusy(true); setErr(''); ctl.compare().then(setRes).catch((e) => setErr(String(e.message ?? e))).finally(() => setBusy(false)) }
  return (
    <section className="card" aria-labelledby="h-compare">
      <h2 id="h-compare"><BarChart3 size={14} aria-hidden /> Compare managers <span className="sim">same jobs, same orders</span></h2>
      <button className="btn primary" disabled={busy} onClick={run}>{busy ? 'Running all four managers...' : 'Compare all managers on this kitchen'}</button>
      {err && <p className="reject" role="alert">{err}</p>}
      {res && (
        <div className="cmp">
          <Bars res={res} title="Average wait" unit="sim min" get={(k) => res.policies[k].avg_wait_min} />
          <Bars res={res} title="Slowest 5% wait" unit="sim min" get={(k) => res.policies[k].p95_wait_min} />
          <Bars res={res} title="Customers served" unit={`of ${res.policies.rl_ppo.received}`} get={(k) => res.policies[k].completed} lowerBetter={false} />
          <Bars res={res} title="Takeaway cost (simulated)" unit="USD" get={(k) => res.policies[k].cloud_cost_usd} />
          <Scatter pts={res.predictions} />
          <p className="note">{res.kitchen?.scale_note} Waits are simulated minutes; takeaway cost is a simulated rental, not an Alibaba bill.</p>
        </div>
      )}
    </section>
  )
}
