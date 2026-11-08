import { Crown, Flame, Pause, Play, Power, PowerOff, RotateCcw, Users, Zap } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { Controller } from '../data/controller'
import { isTrace } from '../data/traceMeta'

const SPEEDS = [0.5, 1, 2, 4, 8, 16]
const SCHEDS = ['rl', 'fifo', 'priority'] as const
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
