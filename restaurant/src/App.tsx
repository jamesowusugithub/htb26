import { useEffect, useMemo, useRef, useState } from 'react'
import { Controller } from './data/controller'
import { createGame } from './game'
import { DecisionPanel } from './panel/DecisionPanel'
import { Controls } from './panel/Controls'
import { GpuCards } from './panel/GpuCards'
import { Header } from './panel/Header'
import { Legend } from './panel/Legend'
import { MetricsGrid } from './panel/MetricsGrid'
import { useController } from './useController'

export default function App() {
  const ctl = useMemo(() => new Controller(), [])
  const hostRef = useRef<HTMLDivElement>(null)
  const [booted, setBooted] = useState(false)
  useController(ctl)

  useEffect(() => {
    const q = new URLSearchParams(location.search)
    const wanted = q.get('source') === 'replay' || q.has('trace') ? 'replay' : 'live'
    let game: ReturnType<typeof createGame> | null = null
    let cancelled = false
    ctl.init(wanted, q.get('run')).then(() => {
      if (cancelled || !hostRef.current) return
      game = createGame(hostRef.current, ctl)
      setBooted(true)
    })
    return () => {
      cancelled = true
      ctl.stop()
      game?.destroy(true)
    }
  }, [ctl])

  const { state, meta } = ctl
  return (
    <div className="app">
      <Header ctl={ctl} />
      <main className="layout">
        <section className="stage" aria-label="Restaurant view">
          <div className="canvas-frame" tabIndex={0} role="group" aria-label="Restaurant scene (scrolls sideways on small screens)">
            <div ref={hostRef} className="canvas-host" role="img" aria-label="Animated pixel restaurant: customers are GPU jobs, chefs are GPUs, the manager is the scheduler" />
            {!booted && <div className="canvas-loading">Opening the restaurant...</div>}
          </div>
          <Legend />
          {meta.kind === 'replay' && <ReplayScrub ctl={ctl} />}
        </section>
        <aside className="panel" aria-label="Dashboard">
          <MetricsGrid state={state} />
          <DecisionPanel state={state} />
          <GpuCards state={state} />
          <Controls ctl={ctl} />
        </aside>
      </main>
    </div>
  )
}

function ReplayScrub({ ctl }: { ctl: Controller }) {
  const { state, meta } = ctl
  return (
    <div className="scrub">
      <label htmlFor="scrub">Replay tick</label>
      <input id="scrub" type="range" min={0} max={meta.duration} value={Math.min(state.t, meta.duration)} onChange={(e) => ctl.seek(Number(e.target.value))} />
      <span className="mono">{state.t}/{meta.duration}</span>
    </div>
  )
}
