import React,{useEffect,useState} from 'react';
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

export function RackPoolDetails({pool,onBack}){
  if(!pool)return null;
  return <section className="rack-pool-details" aria-label={`${pool.label} aggregate rack group`}>
    <div className="device-name"><h3>{pool.label}</h3><span className={`state-badge ${pool.status}`}><i/>{pool.status}</span></div>
    <p className="device-subtitle">Pool aggregate · 20 highlighted visual racks · {pool.nodeCount} simulated nodes</p>
    <dl className="device-metrics">
      <div><dt>GPU capacity</dt><dd>{fmt(pool.busyGpus)}<span> / {fmt(pool.capacityGpus)}</span></dd></div>
      <div><dt>Pool utilisation</dt><dd>{pct(pool.utilisation)}</dd></div>
      <div><dt>Running jobs</dt><dd>{pool.runningJobs}</dd></div>
      <div><dt>Queue</dt><dd>{pool.queueHp}<span> HP · </span>{pool.queueSpot}<span> spot</span></dd></div>
      <div><dt>Largest free node</dt><dd>{fmt(pool.maxFreeGpusOnOneNode)}<span> GPUs</span></dd></div>
      {pool.nodesMapped>0&&<div><dt>Nodes down</dt><dd className={pool.nodesDown?'warm':''}>{pool.nodesDown}<span> / {pool.nodesMapped}</span></dd></div>}
      <div><dt>Thermal</dt><dd>{pool.thermalAvailable?<>{fmt(pool.maxTemperature,1)}<span> °C max (proxy)</span></>:'Not mapped'}</dd></div>
    </dl>
    <p className="proxy-note">This rack column mirrors one backend pool. It does not claim that each visible rack is one physical GPU or one simulated node.</p>
    <button className="score-btn rack-back" onClick={onBack}>Inspect GPU boards</button>
  </section>;
}

export function CustomJobForm({snap,onSubmit,disabled}){
  const pools=snap.run?.pools||[],defaultPool=pools[0]?.id||'';
  const [pool,setPool]=useState(defaultPool),[gpus,setGpus]=useState(1),[priority,setPriority]=useState('hp'),[minutes,setMinutes]=useState(15),[status,setStatus]=useState('');
  useEffect(()=>{if(!pool&&defaultPool)setPool(defaultPool);},[pool,defaultPool]);
  if(!pools.length)return null;
  async function submit(e){e.preventDefault();setStatus('Submitting…');try{await onSubmit({pool,gpus:Number(gpus),priority,duration_s:Number(minutes)*60});setStatus('Submitted to backend scheduler');}catch(error){setStatus(`Submission failed: ${error.message||error}`);}}
  return <section className="custom-job-section" aria-label="Submit custom job"><div className="section-heading"><h2>Submit custom job</h2><span>Backend scheduled</span></div>
    <form className="custom-job-form" onSubmit={submit}>
      <label>GPU pool<select value={pool} onChange={e=>setPool(e.target.value)}>{pools.map(p=><option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
      <label>GPU count<input type="number" min="1" step="1" required value={gpus} onChange={e=>setGpus(e.target.value)}/></label>
      <label>Priority<select value={priority} onChange={e=>setPriority(e.target.value)}><option value="hp">High priority</option><option value="spot">Spot</option></select></label>
      <label>Expected duration (minutes)<input type="number" min="1" step="1" required value={minutes} onChange={e=>setMinutes(e.target.value)}/></label>
      <button className="score-btn" disabled={disabled||!pool} type="submit">Submit job</button>
    </form>{status&&<p className="form-status" role="status">{status}</p>}
  </section>;
}

export function ForecastPanel({snap,gpu}){
  const f=gpu?.forecast,skill=snap.run?.forecast;
  if(!f)return <section className="forecast-section"><div className="section-heading"><h2>Capacity forecast</h2><span>Unavailable</span></div><p className="proxy-note">The backend has no board-level forecast for this selected resource.</p></section>;
  const pressure=f.util_pct>=90?'High':f.util_pct>=70?'Moderate':'Low';
  return <section className="forecast-section" aria-label="Backend capacity forecast"><div className="section-heading"><h2>Capacity forecast</h2><span>30 minutes</span></div>
    <dl className="forecast-grid"><div><dt>Current simulated</dt><dd>{pct(gpu.utilisation)}</dd></div><div><dt>Chosen forecast</dt><dd>{pct(f.util_pct)}</dd></div><div><dt>Capacity pressure</dt><dd>{pressure}</dd></div><div><dt>Survival projection</dt><dd>{pct(f.projection_util_pct)}</dd></div></dl>
    <p className="proxy-note">Chosen method: persistence. Historical error: {skill?.mae_util_pct_points==null?'not available':`${fmt(skill.mae_util_pct_points,1)} percentage points`}. The backend supplies no prediction interval.</p>
    <p className="proxy-note">Pressure is a UI band calculated from forecast utilisation: moderate at 70%, high at 90%. The backend does not currently predict job arrivals over 1–24 hours.</p>
  </section>;
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
