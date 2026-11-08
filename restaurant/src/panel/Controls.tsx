import { Crown, Flame, Pause, Play, Power, PowerOff, RotateCcw, Users, Zap } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Chef, OrderSpec } from '../data/ReplaySource'
import type { Controller } from '../data/controller'
import { isTrace } from '../data/traceMeta'

const SPEEDS = [0.5, 1, 2, 4, 8, 16]
const SCHEDS = ['rl', 'fifo', 'priority'] as const
const GPU_TYPES: [string, string][] = [['a10', 'NVIDIA A10'], ['a100', 'A100 80GB'], ['a800', 'A800'], ['h800', 'H800'], ['series1', 'Alibaba series 1'], ['series2', 'Alibaba series 2']]
const DEFAULT_KITCHEN: Chef[] = [{ pool: 'a100', gpus: 8 }, { pool: 'a100', gpus: 8 }, { pool: 'a100', gpus: 8 }, { pool: 'a100', gpus: 8 }, { pool: 'a100', gpus: 8 }]
const TIP = 'Replay mode: the recording has no backend to talk to'

function Group({ title, children, tip }: { title: string; children: ReactNode; tip?: boolean }) {
  return (
    <div className="group" title={tip ? TIP : undefined}>
      <h3>{title}</h3>
      <div className="row">{children}</div>
    </div>
  )
}

export function Controls({ ctl }: { ctl: Controller }) {
  const { meta, state } = ctl
  const replay = ctl.isReplay
  const [gpu, setGpu] = useState('')
  const sel = gpu || state.gpuOrder.find((g) => !g.startsWith('cloud')) || ''
  const gpuIds = state.gpuOrder.filter((g) => !g.startsWith('cloud'))
  const run = (p: Promise<unknown>) => { p.catch(() => undefined) } // errors are surfaced via meta.error
  const [ord, setOrd] = useState<OrderSpec>({ gpus: 4, priority: 'high', duration_min: 60 })
  const [busy, setBusy] = useState(false)
  const [kit, setKit] = useState<Chef[]>(ctl.chefs ?? DEFAULT_KITCHEN)
  const setChef = (i: number, c: Partial<Chef>) => setKit(kit.map((x, j) => (j === i ? { ...x, ...c } : x)))
  const applyKitchen = () => { setBusy(true); ctl.setKitchen(kit).catch(() => undefined).finally(() => setBusy(false)) }
  const place = (specs: OrderSpec[]) => { setBusy(true); ctl.placeOrders(specs).catch(() => undefined).finally(() => setBusy(false)) }

  const off = replay
  const trace = isTrace()
  const q = new URLSearchParams(location.search)
  const cur = q.get('trace')
  const api = q.get('api')
  const TRACES: [string, string][] = [['fifo', 'First come'], ['priority_fifo', 'Priority'], ['sjf_hint', 'Predicted runtime'], ['rl_ppo', 'Trained RL']]
  return (
    <section className="card" aria-labelledby="h-controls">
      <h2 id="h-controls">Controls</h2>
      {trace && (
        <Group title="Same real jobs, different manager">
          <div className="seg" role="group" aria-label="Recording">
            {TRACES.map(([k, l]) => (
              <a key={k} className={`segbtn ${cur === k ? 'on' : ''}`} aria-current={cur === k} href={`?trace=${k}${api ? `&api=${encodeURIComponent(api)}` : ''}`}>{l}</a>
            ))}
          </div>
        </Group>
      )}
      {trace && ctl.canOrder && (
        <Group title={`Kitchen: ${kit.reduce((a, c) => a + c.gpus, 0)} GPUs on ${kit.length} chefs`}>
          <div className="kitchen">
            {kit.map((c, i) => (
              <div className="chef-row" key={i}>
                <span className="mono">Chef {i + 1}</span>
                <select className="select" aria-label={`Chef ${i + 1} GPU type`} value={c.pool} onChange={(e) => setChef(i, { pool: e.target.value })}>
                  {GPU_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <select className="select" aria-label={`Chef ${i + 1} GPUs`} value={c.gpus} onChange={(e) => setChef(i, { gpus: Number(e.target.value) })}>
                  {[1, 2, 4, 8].map((g) => <option key={g} value={g}>{g} GPU{g > 1 ? 's' : ''}</option>)}
                </select>
              </div>
            ))}
          </div>
          <button className="btn" disabled={busy || kit.length >= 5} onClick={() => setKit([...kit, { pool: 'a100', gpus: 8 }])}>+ Chef</button>
          <button className="btn" disabled={busy || kit.length <= 2} onClick={() => setKit(kit.slice(0, -1))}>- Chef</button>
          <button className="btn primary" disabled={busy} onClick={applyKitchen}>{busy ? 'Rebuilding...' : 'Apply kitchen'}</button>
        </Group>
      )}
      {trace && ctl.canOrder && (
        <Group title={`New order (not in the trace)${ctl.orderCount ? ` - ${ctl.orderCount} placed` : ''}`}>
          <select className="select" aria-label="GPU type for the order" value={ord.pool ?? kit[0]?.pool} onChange={(e) => setOrd({ ...ord, pool: e.target.value })}>
            {Array.from(new Set(kit.map((c) => c.pool))).map((k) => <option key={k} value={k}>{GPU_TYPES.find((t) => t[0] === k)?.[1] ?? k}</option>)}
          </select>
          <select className="select" aria-label="GPUs requested" value={ord.gpus} onChange={(e) => setOrd({ ...ord, gpus: Number(e.target.value) })}>
            {[1, 2, 4, 8].map((g) => <option key={g} value={g}>{g} GPU{g > 1 ? 's' : ''}</option>)}
          </select>
          <select className="select" aria-label="Priority" value={ord.priority} onChange={(e) => setOrd({ ...ord, priority: e.target.value as 'high' | 'spot' })}>
            <option value="high">high priority</option><option value="spot">spot</option>
          </select>
          <select className="select" aria-label="Runtime" value={ord.duration_min} onChange={(e) => setOrd({ ...ord, duration_min: Number(e.target.value) })}>
            {[15, 60, 180].map((d) => <option key={d} value={d}>{d} min</option>)}
          </select>
          <button className="btn primary" disabled={busy} onClick={() => place([ord])}>{busy ? 'Asking the manager...' : 'Place order'}</button>
          <button className="btn" disabled={busy} onClick={() => place(Array.from({ length: 6 }, () => ({ gpus: 8, priority: 'high' as const, duration_min: 120 })))}><Zap size={15} aria-hidden /> Rush: 6 big orders</button>
        </Group>
      )}
      <Group title="Run">
        <button className="btn primary" onClick={() => run(ctl.play(!meta.playing))} aria-pressed={meta.playing}>
          {meta.playing ? <><Pause size={15} aria-hidden /> Pause</> : <><Play size={15} aria-hidden /> Start</>}
        </button>
        <button className="btn" onClick={() => run(ctl.reset())}><RotateCcw size={15} aria-hidden /> Reset</button>
      </Group>
      <Group title="Speed">
        <div className="seg" role="group" aria-label="Simulation speed">
          {SPEEDS.map((s) => (
            <button key={s} className={`segbtn ${meta.speed === s ? 'on' : ''}`} aria-pressed={meta.speed === s} onClick={() => run(ctl.setSpeed(s))}>{s}x</button>
          ))}
        </div>
      </Group>
      {!trace && <Group title="Traffic" tip={replay}>
        <button className="btn" disabled={off} onClick={() => run(ctl.call('/job', {}))}><Users size={15} aria-hidden /> Normal</button>
        <button className="btn" disabled={off} onClick={() => run(ctl.call('/spike', { n: 12 }))}><Zap size={15} aria-hidden /> Spike</button>
        <button className="btn" disabled={off} onClick={() => run(ctl.call('/vip', {}))}><Crown size={15} aria-hidden /> VIP</button>
      </Group>}
      {!trace && <Group title="Pick a GPU" tip={replay}>
        <select className="select" aria-label="GPU to act on" value={sel} onChange={(e) => setGpu(e.target.value)} disabled={off}>
          {gpuIds.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <button className="btn" disabled={off || !sel} onClick={() => run(ctl.call('/force_heat', { gpu_id: sel, delta: 20 }))}><Flame size={15} aria-hidden /> Heat +20</button>
        <button className="btn" disabled={off || !sel} onClick={() => run(ctl.call('/disable_gpu', { gpu_id: sel }))}><PowerOff size={15} aria-hidden /> Disable</button>
        <button className="btn" disabled={off || !sel} onClick={() => run(ctl.call('/restore_gpu', { gpu_id: sel }))}><Power size={15} aria-hidden /> Restore</button>
      </Group>}
      {!trace && <Group title="Scheduler" tip={replay}>
        <div className="seg" role="group" aria-label="Scheduler">
          {SCHEDS.map((s) => (
            <button key={s} className={`segbtn ${state.scheduler === s ? 'on' : ''}`} disabled={off} aria-pressed={state.scheduler === s} onClick={() => run(ctl.call('/scheduler', { scheduler: s }))}>{s}</button>
          ))}
        </div>
      </Group>}
      {replay && <p className="note">Replay mode: play, pause, speed, reset and the tick slider work on the recording. Traffic, heat, GPU and scheduler buttons need the live backend.</p>}
      {meta.error && <p className="reject" role="alert">Control failed: {meta.error}</p>}
    </section>
  )
}
