import React from 'react';
import {AlertTriangle,Flame,Wifi,Loader2,Zap,Thermometer} from 'lucide-react';

// Panels shown only in backend mode. Every number is displayed exactly as the backend sent it; temperatures and power are
// the backend's H100-profile PROXY and are labelled as such.
const fmt=(v,d=0)=>v==null?'n/a':Number(v).toFixed(d);
const pct=x=>x==null?'n/a':`${Math.round(x)}%`;

export function BackendSubtitle({gpu}){
  return <p className="device-subtitle">Board {gpu.index+1} · {gpu.model} · slice {gpu.slice+1} of 6 · {gpu.nodes} nodes ({fmt(gpu.capacityGpus)} GPUs)</p>;
}

export function BackendMetrics({gpu}){
  const f=gpu.forecast;
  return <dl className="device-metrics backend-metrics">
    <div><dt>Power <em className="proxy-tag">proxy</em></dt><dd>{gpu.powerW==null?<span>n/a for this hardware</span>:<>{fmt(gpu.powerW)}<span> W</span></>}</dd></div>
    <div><dt>Nodes down</dt><dd className={gpu.nodesDown?'warm':''}>{gpu.nodesDown}<span> / {gpu.nodes}</span></dd></div>
    {f&&<div className="forecast-row"><dt>In 30 min <em className="proxy-tag">projection</em></dt><dd>{pct(f.util_pct)} · {fmt(f.temp_c,1)}<span> °C</span></dd></div>}
    {gpu.alert&&<div className="alert-row"><AlertTriangle size={14}/><span>Overheating: above the assumed alert threshold (proxy temperature)</span></div>}
  </dl>;
}

export function PoolPanel({snap,selectedPool}){
  const run=snap.run, pools=snap.pools||{};
  const labels=Object.fromEntries((run?.pools||[]).map(p=>[p.id,p.label]));
  const ids=Object.keys(pools);
  if(!ids.length)return null;
  return <section className="pool-section" aria-label="Pool totals">
    <div className="section-heading"><h2>Pools</h2><span>{ids.length} GPU models</span></div>
    <table className="pool-table"><thead><tr><th>Pool</th><th>GPUs busy</th><th>Queue HP / spot</th></tr></thead><tbody>
      {ids.map(id=>{const p=pools[id];return <tr key={id} className={id===selectedPool?'selected':''}>
        <td>{labels[id]||id}</td><td>{Math.round(p.busy_gpus)}<small>/{Math.round(p.capacity_gpus)}</small></td><td>{p.queue_hp} / {p.queue_spot}</td></tr>;})}
    </tbody></table>
    <p className="proxy-note">All six pools are simulated; only four are drawn as pods.</p>
  </section>;
}

// Demand forecast (calculated, not observed): GPUs requested by jobs arriving in the next 30 min, per pool, with a P10-P90 band, shown against what arrived.
export function ForecastPanel({snap}){
  const d=snap.run?.demand;
  if(!d)return null;
  if(!d.available)return <section className="forecast-section" aria-label="Demand forecast"><div className="section-heading"><h2>Demand forecast</h2><span>unavailable</span></div><p className="proxy-note">{d.reason}</p></section>;
  const H=d.horizon_s, t=snap.time||0, S=d.series;
  let now=null,done=null;
  for(const e of S){ if(e.t<=t)now=e; if(e.t+H<=t)done=e; }
  const ids=Object.keys((now||S[0]).pools), labels=Object.fromEntries((snap.run?.pools||[]).map(p=>[p.id,p.label]));
  const all=d.heldout_skill?.per_pool?.ALL;
  return <section className="forecast-section" aria-label="Demand forecast">
    <div className="section-heading"><h2>Demand forecast</h2><span>next {Math.round(H/60)} min <em className="proxy-tag">calculated</em></span></div>
    {!now?<p className="proxy-note">The first forecast is issued {Math.round(S[0].t/60)} min into the window.</p>:
    <table className="forecast-table"><thead><tr><th>Pool (GPUs requested)</th><th>Expected</th><th>P10–P90</th><th>Last: said → got</th></tr></thead><tbody>
      {ids.map(id=>{const v=now.pools[id], l=done?.pools[id];return <tr key={id} className={id===snap.gpus?.[0]?.pool?'':''}>
        <td>{labels[id]||id}</td><td>{fmt(v.next_gpus,1)}</td><td>{fmt(v.p10,0)}–{fmt(v.p90,0)}</td><td>{l?`${fmt(l.next_gpus,1)} → ${fmt(l.realised_gpus,1)}`:'—'}</td></tr>;})}
    </tbody></table>}
    <p className="proxy-note">{all?`On held-out trace days the forecast error was ${Math.round(100*all.skill_vs_persistence)}% lower than "same rate as the last 30 min" overall; it has little skill on the A10 pool and does not anticipate sudden spikes. The P10–P90 band held ${Math.round(100*all.p10_p90_coverage)}% of outcomes (aimed at 80%). `:''}{d.in_training_period?'This window overlaps the days the model was trained on, so it flatters the model. ':''}Trained on trace days before 100.</p>
  </section>;
}

const POLICY_LABEL={fifo:'First come, first served',priority_fifo:'Priority first',backfill_median:'Backfill',sjf_hint:'Shortest predicted job',rl_ppo:'Learned (RL)',sjf_oracle:'Shortest job (oracle)',backfill_oracle:'Backfill (oracle)'};
export function LinkPanel({snap}){
  const l=snap.link,[,force]=React.useReducer(x=>x+1,0);
  React.useEffect(()=>{const t=setInterval(force,500);return()=>clearInterval(t);},[]);
  const age=l.lastBatchAt?((Date.now()-l.lastBatchAt)/1000):null;
  return <section className="link-section" aria-label="Backend link"><div className="section-heading"><h2>Backend link</h2><span className={`link-dot ${age!=null&&age<3?'live':'stale'}`}>{age!=null&&age<3?'receiving':'idle'}</span></div>
    <dl className="link-grid"><div><dt>Server</dt><dd>{(l.base||'').replace('http://','')}</dd></div><div><dt>Transport</dt><dd>{snap.connection.mode}</dd></div><div><dt>Run</dt><dd>{(l.runId||'').slice(0,18)}</dd></div>
      <div><dt>Batches</dt><dd>{l.batches.toLocaleString('en-GB')}</dd></div><div><dt>Events applied</dt><dd>{l.events.toLocaleString('en-GB')}</dd></div><div><dt>Last data</dt><dd>{age==null?'—':`${age.toFixed(1)} s ago`}</dd></div></dl></section>;
}

export function Scoreboard({snap,actions}){
  const sb=snap.scoreboard,busy=snap.scoreboardStatus==='computing';
  return <section className="score-section" aria-label="Policy scoreboard"><div className="section-heading"><h2>Policy scoreboard</h2>
    <button className="ui-button score-btn" disabled={busy||snap.status==='computing'} onClick={actions.onCompare}>{busy?'Running 6 policies…':sb?'Re-run':'Compare policies'}</button></div>
    {sb?<><table className="pool-table score-table"><thead><tr><th>Policy</th><th>HP wait</th><th>HP p95</th><th>Spot wait</th></tr></thead><tbody>
      {sb.rows.map(r=><tr key={r.policy} className={`${r.policy==='rl_ppo'?'selected':''} ${r.realistic?'':'ceiling'}`}><td>{POLICY_LABEL[r.policy]||r.policy}{r.realistic?'':' *'}</td><td>{r.hp_wait_mean_h.toFixed(1)} h</td><td>{r.hp_wait_p95_h.toFixed(1)} h</td><td>{r.spot_wait_mean_h==null?'n/a':`${r.spot_wait_mean_h.toFixed(1)} h`}</td></tr>)}</tbody></table>
      <p className="proxy-note">Same workload, same cluster, scenario {sb.scenarioId}. * uses true durations: an unattainable ceiling. Waits are simulated. Computed by the backend in {sb.computeSeconds}s.</p></>
     :<p className="proxy-note">Runs this scenario under every policy in the backend, including the trained RL scheduler.</p>}
  </section>;
}

export function ScenarioBar({s,actions}){
  const snap=s.snapshot,busy=snap.status==='computing';
  return <div className="scenario-bar">
    <label>Scenario<select aria-label="What-if scenario" value={s.presetName||''} disabled={busy} onChange={e=>actions.onScenario(e.target.value)}>
      {(s.presets||[]).map(p=><option key={p.name} value={p.name} title={p.note}>{p.name.replace(/_/g,' ')}</option>)}</select></label>
    <button className={`ui-button cool-btn ${snap.effects.coolingFaultActive?'on':''}`} disabled={busy} onClick={()=>actions.onCooling(!snap.effects.coolingFaultActive)}
      title="Adds a +35 °C cooling fault (assumed size) to every board, or clears it">
      <Flame size={14}/><span>{snap.effects.coolingFaultActive?'Clear cooling fault':'Cooling fault'}</span></button>
  </div>;
}

export function StatusBanner({s,actions}){
  const snap=s.snapshot,fx=snap.effects,items=[];
  if(snap.status==='computing')items.push(<span key="c" className="chip busy"><Loader2 size={13} className="spin"/>Recomputing scenario in the backend…</span>);
  if(snap.error)items.push(<span key="e" className="chip error" role="alert"><AlertTriangle size={13}/>{snap.error}{actions.onRetry&&<button onClick={actions.onRetry}>Retry</button>}</span>);
  if(fx.burstActive)items.push(<span key="b" className="chip warn"><Zap size={13}/>Arrival spike ×{fx.burst.mult} in progress</span>);
  if(fx.coolingFaultActive)items.push(<span key="f" className="chip hot"><Thermometer size={13}/>Cooling fault +{fx.coolingDeltaC} °C</span>);
  if(snap.stats.failed)items.push(<span key="n" className="chip error"><AlertTriangle size={13}/>{snap.stats.failed} board{snap.stats.failed>1?'s':''} down</span>);
  if(snap.stats.alerts)items.push(<span key="a" className="chip hot"><Flame size={13}/>{snap.stats.alerts} overheating (proxy)</span>);
  if(snap.stats.arrivalsPerMin!=null)items.push(<span key="r" className="chip"><Wifi size={13}/>{snap.stats.arrivalsPerMin.toFixed(1)} arrivals / sim-min</span>);
  return items.length?<div className="status-banner" aria-live="polite">{items}</div>:null;
}

export function evidenceLine(snap){
  const r=snap.run,th=r?.thermal,fc=r?.forecast;
  const skill=fc&&fc.mae_util_pct_points!=null?` · 30-min forecast error ${fc.mae_util_pct_points.toFixed(1)} pp (persistence)`:'';
  return `Simulated replay of the Alibaba GPU trace · policy ${snap.policy}${th?` · temperature & power are a proxy from measured ${th.source_gpu.replace('nvidia_','').toUpperCase()} profiles, not this hardware`:''}${skill} · link: ${snap.connection.mode}`;
}
