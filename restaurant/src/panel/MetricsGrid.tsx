import { Activity, CheckCircle2, Clock, Coins, Flame, Gauge, Inbox, Target } from 'lucide-react'
import type { ReactNode } from 'react'
import type { SimState } from '../data/types'
import { isTrace, traceMeta } from '../data/traceMeta'

function Tile({ icon, label, value, unit }: { icon: ReactNode; label: string; value: string; unit?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{icon}{label}</div>
      <div className="tile-value">{value}{unit && <small>{unit}</small>}</div>
    </div>
  )
}

export function MetricsGrid({ state }: { state: SimState }) {
  const m = state.metrics
  const trace = isTrace()
  return (
    <section className="card" aria-labelledby="h-metrics">
      <h2 id="h-metrics">Restaurant metrics <span className="sim">{trace ? 'simulated scheduling of real jobs' : 'simulated'}</span></h2>
      <div className="tiles">
        <Tile icon={<Inbox size={13} aria-hidden />} label="Received" value={String(m.received)} />
        <Tile icon={<CheckCircle2 size={13} aria-hidden />} label="Completed" value={String(m.completed)} />
        <Tile icon={<Clock size={13} aria-hidden />} label="Waiting" value={String(m.waiting)} />
        <Tile icon={<Activity size={13} aria-hidden />} label="Avg wait" value={m.avg_wait_s.toFixed(1)} unit={trace ? ' min' : ' s'} />
        {!trace && <Tile icon={<Target size={13} aria-hidden />} label="On-time (SLO)" value={(m.slo_rate * 100).toFixed(0)} unit="%" />}
        {trace && <Tile icon={<Target size={13} aria-hidden />} label="Slowest 5% wait" value={m.p95_wait_s.toFixed(1)} unit=" min" />}
        <Tile icon={<Gauge size={13} aria-hidden />} label="Avg GPU util" value={m.avg_util.toFixed(0)} unit="%" />
        {!trace && <Tile icon={<Coins size={13} aria-hidden />} label="Cost" value={m.cost.toFixed(1)} unit=" sim$" />}
        {trace && traceMeta()?.cloud && <Tile icon={<Coins size={13} aria-hidden />} label="Takeaway cost (simulated)" value={m.cost.toFixed(2)} unit=" USD" />}
        <Tile icon={<Flame size={13} aria-hidden />} label="Thermal incidents" value={String(m.thermal_incidents)} />
      </div>
    </section>
  )
}
