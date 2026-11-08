import React,{useState,useSyncExternalStore,useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';
import {Pause,Play,Plus,Layers3,PanelRight,ChevronDown,MoreHorizontal,RotateCcw,AlertTriangle,Wrench,X,MousePointer2,CheckCircle2,Clock3,Move3d} from 'lucide-react';
import {BackendSubtitle,BackendMetrics,PoolPanel,ScenarioBar,StatusBanner,LinkPanel,Scoreboard,evidenceLine} from './backend-panels.jsx';
import {Button,Tooltip,DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuItem,DropdownMenuSeparator,DropdownMenuLabel,CameraTabs} from './components/index.jsx';

const labels={idle:'Available',reserved:'In transit',running:'Processing',cooling:'Cooling',failed:'Failed'};
const availability={idle:'Ready for the next assignment.',reserved:'A job is travelling to this GPU.',running:'Processing the assigned job.',cooling:'Cooling before the next assignment.',failed:'Unavailable. Repair to accept new work.'};

export function mountOverlay(host,actions,initial){
  let model=initial;const listeners=new Set();
  const store={subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},get:()=>model};
  const update=patch=>{model={...model,...patch};listeners.forEach(fn=>fn());};
  function App(){
    const s=useSyncExternalStore(store.subscribe,store.get);
    const [open,setOpen]=useState(true);const [mobile,setMobile]=useState(()=>matchMedia('(max-width:760px)').matches);
    useEffect(()=>{const q=matchMedia('(max-width:760px)');const fn=()=>{setMobile(q.matches);setOpen(!q.matches);};fn();q.addEventListener('change',fn);return()=>q.removeEventListener('change',fn);},[]);
    useEffect(()=>{if(s.inspectRequest)setOpen(true);},[s.inspectRequest]);
    const snap=s.snapshot,gpu=snap.gpus[s.selected]||snap.gpus[0],progress=Math.round(gpu.progress*100);
    useEffect(()=>{host.dataset.inspectorOpen=String(open);},[open]);
    return <div className="ui-shell" data-inspector-open={open}>
      <a className="skip-link" href="#device-select">Skip to device controls</a>
      <header className="workbench-header">
        <div className="brand"><h1>GPU Fabric</h1><p>Interactive server room</p></div>
        <dl className="activity"><div><dt>Processing</dt><dd>{snap.stats.running}<span>/{snap.gpus.length}</span></dd></div><div><dt>Queued</dt><dd>{snap.stats.queued??snap.queue.length}</dd></div><div><dt>Completed</dt><dd>{new Intl.NumberFormat('en-GB').format(snap.stats.completed)}</dd></div></dl>
        <div className="view-controls"><CameraTabs items={[{id:'room',label:'Room'},{id:'hall',label:'GPU hall'},{id:'gpu',label:'GPU detail'}]} value={s.cameraView} onChange={actions.onView}/><Tooltip content={open?'Hide device inspector':'Show device inspector'}><Button variant="ghost" className="inspector-toggle" onClick={()=>setOpen(!open)} aria-label={open?'Hide device inspector':'Show device inspector'} aria-expanded={open} aria-controls="device-inspector"><PanelRight size={18}/></Button></Tooltip></div>
      </header>
      <div className="stage-heading"><div><Move3d size={15}/><span>{s.cameraView==='gpu'?`${gpu.id} hardware detail`:s.cameraView==='hall'?'GPU compute hall':'Server room overview'}</span></div><span className="stage-help">Drag to orbit. Scroll to zoom.</span></div>
      {s.backend&&<StatusBanner s={s} actions={actions}/>}
      {!s.assetReady&&!s.error&&<div className="asset-loading" role="status">Loading GPU hardware…</div>}
      {s.error&&<div className="asset-loading error" role="alert">GPU hardware could not load. Reload to retry.</div>}
      <aside className="device-panel" id="device-inspector" aria-label="GPU inspector" hidden={!open}>
        <div className="panel-heading"><h2>Device inspector</h2><span className={`play-state ${s.paused?'paused':''}`}><i/>{s.paused?'Paused':'Live'}</span>{mobile&&<Button variant="ghost" className="icon-button" onClick={()=>setOpen(false)} aria-label="Close device inspector"><X size={17}/></Button>}</div>
        <label className="field-label" htmlFor="device-select">Select GPU</label><div className="select-wrap"><select id="device-select" value={s.selected} onChange={e=>actions.onSelectGPU(Number(e.target.value))}>{snap.gpus.map(g=><option key={g.id} value={g.index}>{g.label||`${g.id} / Pod ${Math.floor(g.index/6)+1}`}</option>)}</select><ChevronDown size={15}/></div>
        <section className="device-details"><div className="device-name"><h3>{gpu.id}</h3><span className={`state-badge ${gpu.status}`}><i/>{labels[gpu.status]}</span></div>{s.backend?<BackendSubtitle gpu={gpu}/>:<p className="device-subtitle">Illustrative accelerator, Pod {Math.floor(gpu.index/6)+1}</p>}
          <dl className="device-metrics"><div><dt>Temperature</dt><dd className={(gpu.temperature>70||gpu.alert)?'warm':''}>{gpu.temperature==null?'—':gpu.temperature.toFixed(1)}<span> °C{s.backend?' (proxy)':''}</span></dd></div><div><dt>Utilisation</dt><dd>{Math.round(gpu.utilisation)}<span>%</span></dd></div><div><dt>Assigned job</dt><dd className="job-id">{gpu.jobId||'None'}</dd></div></dl>
          {s.backend&&<BackendMetrics gpu={gpu}/>}
          <div className="progress-label"><span>Job progress</span><strong>{progress}%</strong></div><div className="job-progress" role="progressbar" aria-label="Job progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><i style={{transform:`scaleX(${gpu.progress})`}}/></div>
          <p className={`availability ${gpu.status==='failed'?'failed':''}`}>{gpu.status==='failed'?<AlertTriangle size={14}/>:<CheckCircle2 size={14}/>}<span>{availability[gpu.status]}</span></p>
          <div className="device-actions"><Button variant="outline" className="fail-action" disabled={gpu.status==='failed'} onClick={actions.onFailGPU}><AlertTriangle size={14}/>Fail GPU</Button><Button variant="outline" disabled={gpu.status!=='failed'} onClick={actions.onRepairGPU}><Wrench size={14}/>Repair</Button></div>
        </section>
        <section className="queue-section"><div className="section-heading"><h2>Incoming jobs</h2><span>{snap.stats.queued??snap.queue.length} waiting</span></div>{snap.queue.length?<ul className="job-list">{snap.queue.slice(0,5).map(job=><li key={job.id}><span className={`queue-mark ${job.priority==='high'?'high':''}`}/><span>{job.position?`#${job.position} `:''}{job.id}</span><small>{job.priority==='high'?'High priority':'Spot'}{job.gpus?` · ${job.gpus} GPU`:''}</small></li>)}</ul>:<div className="queue-empty"><CheckCircle2 size={19}/><div><strong>{s.backend?(snap.stats.queued?'No jobs waiting in this pool':'Queue is clear'):'Queue is clear'}</strong><p>{s.backend?(snap.stats.queued?`${snap.stats.queued} waiting in other pools (see Pools)`:'Waiting for the next arrival from the backend.'):'New jobs arrive automatically.'}</p></div></div>}</section>
        {s.backend&&<Scoreboard snap={snap} actions={actions}/>}
        {s.backend&&<PoolPanel snap={snap} selectedPool={gpu.pool}/>}
        {s.backend&&<LinkPanel snap={snap}/>}
        <div className="latest-event"><Clock3 size={14}/><p role="status" aria-live="polite" aria-atomic="true">{s.latestEvent}</p></div>
      </aside>
      <div className="scene-legend" aria-label="GPU status legend"><span><i/>Available</span><span><i className="busy"/>Processing</span><span><i className="failed"/>Failed</span><span><i className="transit"/>In transit</span></div>
      <section className="control-strip" aria-label="Simulation controls"><div className="transport"><Button onClick={actions.onTogglePaused} aria-label={s.paused?'Resume':'Pause'}>{s.paused?<Play size={15}/>:<Pause size={15}/>}<span>{s.paused?'Resume':'Pause'}</span></Button><Tooltip content={s.backend?"Inject one high-priority job (1 GPU, 15 min) into the selected pool":"Add one high-priority job"}><Button variant="outline" disabled={s.busy} onClick={actions.onAddJob}><Plus size={15}/><span>Add job</span></Button></Tooltip><Tooltip content={s.backend?"4× arrival spike for 30 simulated minutes":"Add a burst of 28 jobs"}><Button variant="outline" disabled={s.busy} onClick={actions.onBurst}><Layers3 size={15}/><span>Job burst</span></Button></Tooltip></div>
        <div className="playback">{s.backend&&<ScenarioBar s={s} actions={actions}/>}<label>Policy<select aria-label="Scheduling policy" value={snap.policy==='round-robin'?'round_robin':snap.policy} onChange={e=>actions.onPolicy(e.target.value)} disabled={s.busy}>{s.policies?s.policies.map(p=><option key={p.name} value={p.name} title={p.description}>{p.label}</option>):<><option value="priority">Priority first</option><option value="fcfs">First come, first served</option><option value="round_robin">Round robin</option></>}</select></label><label>Speed<select aria-label="Playback speed" value={s.speed} onChange={e=>actions.onSpeed(Number(e.target.value))}><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" className="icon-button" aria-label="More options"><MoreHorizontal size={20}/></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuLabel>Scene controls</DropdownMenuLabel><DropdownMenuItem onSelect={()=>actions.onView('room')}><Move3d size={15}/>Room overview</DropdownMenuItem><DropdownMenuItem onSelect={()=>setOpen(true)}><PanelRight size={15}/>Show inspector</DropdownMenuItem><DropdownMenuSeparator/><DropdownMenuItem onSelect={actions.onReset}><RotateCcw size={15}/>Reset scenario</DropdownMenuItem></DropdownMenuContent></DropdownMenu></div>
      </section>
      <footer className="evidence-strip">{s.backend?<><span><i/>Backend simulation</span><p>{evidenceLine(snap)}</p></>:<><span><i/>Illustrative scenario</span><p>Jobs, assignments and temperatures are synthetic.{s.fallbackNote?` ${s.fallbackNote} Showing the labelled synthetic demo instead.`:''}</p></>}</footer>
    </div>;
  }
  flushSync(()=>createRoot(host).render(<App/>));
  return {update};
}
