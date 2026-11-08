import { THREE, THREEAddons, ViewerEvent } from '@x-viewer/core';
import { GPUSimulation } from './gpu-simulation.js';
import { mountOverlay } from './ui-dist/overlay.js';
import { BackendClient } from './backend-client.js';
import { ReplayEngine } from './replay-engine.js';
import { mockRackState } from './rack-test-data.js';

const COLORS={idle:0x20be92,reserved:0x62c9f1,running:0xf1b14a,cooling:0x64b8b4,failed:0xe94f64,busy:0xf1b14a,overloaded:0xf06a3e,unavailable:0xe94f64};

export async function mountGPULab({viewer,room}) {
  const ui=document.createElement('div');ui.className='gpu-ui';document.body.append(ui);
  const params=new URLSearchParams(location.search);
  const requestedMode=params.get('mode')||'auto';            // auto: backend if reachable, else labelled synthetic demo
  const rackTestMode=requestedMode==='rack-test';
  const apiBase=params.get('api')||'http://127.0.0.1:8000';
  let overlay=null,latestEvent='Ready to dispatch jobs.',cameraView='hall',inspectRequest=0;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let paused=reducedMotion,speed=1,selected=0,selectedRackPool=null,lastTime,uiTime=0,assetReady=false;
  const lab=new THREE.Group();lab.name='GPU scheduling laboratory';room.add(lab);
  const pods=[[-14.5,5],[-8.5,5],[-14.5,10],[-8.5,10]];
  const slots=[],rings=[],assetGroups=[],particlePool=[],podLabels=[],rackVisuals=[],rackTargets=new Map();
  const boxGeom=new THREE.BoxGeometry(1,1,1);
  const mat=(color,metalness=.25,roughness=.5)=>new THREE.MeshStandardMaterial({color,metalness,roughness});
  const dark=mat(0x243d3b,.65,.32),edge=mat(0xb7c8c4,.6,.38),plinth=mat(0xe3ebe6,.25,.55);
  function box(parent,name,size,position,material){const o=new THREE.Mesh(boxGeom,material);o.name=name;o.scale.set(...size);o.position.set(...position);parent.add(o);return o;}
  function label(text,position,size=1.5){const canvas=document.createElement('canvas');canvas.width=512;canvas.height=128;const ctx=canvas.getContext('2d');ctx.clearRect(0,0,512,128);ctx.fillStyle='#33584c';ctx.font='500 38px Arial';ctx.textAlign='center';ctx.fillText(text,256,78);const texture=new THREE.CanvasTexture(canvas);const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));sprite.position.set(...position);sprite.scale.set(size,size/4,1);sprite.userData={canvas,ctx,texture};lab.add(sprite);return sprite;}
  function relabel(sprite,text){const {canvas,ctx,texture}=sprite.userData;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#33584c';ctx.font='500 38px Arial';ctx.textAlign='center';ctx.fillText(text,canvas.width/2,78);texture.needsUpdate=true;}
  pods.forEach(([x,z],pod)=>{
    const p=new THREE.Group();p.position.set(x,0,z);p.name=`GPU Pod ${pod+1}`;lab.add(p);
    box(p,'Chassis',[2.85,1.0,1.85],[0,.55,0],dark);box(p,'Open compute tray',[3.0,.10,2.0],[0,1.10,0],edge);
    box(p,'Pod plinth',[3.16,.12,2.17],[0,.05,0],plinth);
    for(let j=0;j<6;j++){box(p,'Vent',[.32,.025,.018],[-1.03+j*.41,.72, .94],edge);box(p,'Vent',[.32,.025,.018],[-1.03+j*.41,.58,.94],edge);}
    podLabels[pod]=label(`POD ${String(pod+1).padStart(2,'0')}`,[x,.3,z+1.1],1.3);
    for(let j=0;j<6;j++){
      const index=pod*6+j,position=new THREE.Vector3(x+(j%3-1)*.93,1.23,z+(j<3?-.45:.45));
      slots.push({index,position,pod});
      const ring=new THREE.Mesh(new THREE.BoxGeometry(.83,.035,.39),new THREE.MeshStandardMaterial({color:COLORS.idle,emissive:COLORS.idle,emissiveIntensity:.4,metalness:.3,roughness:.35}));
      ring.position.copy(position);ring.position.y-=.035;ring.userData.gpuIndex=index;lab.add(ring);rings.push(ring);
    }
  });
  const portal=new THREE.Vector3(-18.1,1.5,7.1);
  box(lab,'Job gateway',[.38,1.8,.38],[portal.x,.95,portal.z],dark);
  const gateway=new THREE.Mesh(new THREE.TorusGeometry(.44,.035,8,40),new THREE.MeshStandardMaterial({color:0x49c2b0,emissive:0x49c2b0,emissiveIntensity:.8}));gateway.position.copy(portal);lab.add(gateway);
  label('JOB GATEWAY',[portal.x,2.35,portal.z],1.8);
  for(const [x,z] of pods){const curve=new THREE.CatmullRomCurve3([portal,new THREE.Vector3(-17,1.5,7.1),new THREE.Vector3(x,1.5,7.1),new THREE.Vector3(x,1.25,z)]);const path=new THREE.Mesh(new THREE.TubeGeometry(curve,20,.014,5,false),new THREE.MeshBasicMaterial({color:0x87c7b6,transparent:true,opacity:.35}));path.name='Routing guide';lab.add(path);}
  const selector=new THREE.Mesh(new THREE.TorusGeometry(.57,.019,8,48),new THREE.MeshBasicMaterial({color:0x173f35,depthTest:false}));selector.rotation.x=-Math.PI/2;lab.add(selector);
  const eventNames={'job-arrival':'Job entered the queue','job-dispatch':'Job routed to GPU','job-start':'GPU started processing','job-complete':'Job completed','gpu-failed':'GPU failed; work requeued','gpu-repaired':'GPU repaired and available','job-requeued':'Interrupted job returned to queue'};
  const onEngineEvent=event=>{latestEvent=event.text||`${eventNames[event.type]||event.type}${event.jobId?' · '+event.jobId:''}`;overlay?.update({latestEvent});};
  // Engine: the scheduling backend when reachable. The synthetic demo is only a labelled fallback; it is never mixed with backend data.
  let engine=null,mode='synthetic',presets=[],policies=null,backendNote=null,backendClient=null;
  if(!['synthetic','rack-test'].includes(requestedMode)){
    try{
      backendClient=new BackendClient(apiBase,{forcePolling:params.get('transport')==='polling'});
      const [m,pr]=await Promise.all([backendClient.meta(),backendClient.presets()]);
      presets=pr;policies=m.policies.map(p=>({name:p.name,description:p.description,label:({fifo:'First come, first served',priority_fifo:'Priority first',backfill_median:'Backfill',sjf_hint:'Shortest predicted job',sjf_oracle:'Shortest job (oracle)',rl_ppo:'Learned (RL)'})[p.name]||p.name}));
      const sc=pr.find(x=>x.name===(params.get('preset')||'live_demo'))||pr[0];
      engine=new ReplayEngine({client:backendClient,scenario:sc,policy:params.get('policy')||'priority_fifo',onEvent:onEngineEvent,paused:reducedMotion,onChange:()=>{if(engine)updateUI(engine.snapshot());}});
      mode='backend';
    }catch(error){
      backendNote=`Scheduling backend not reachable at ${apiBase} (${error.message}).`;
      if(requestedMode==='backend'){backendClient=backendClient||new BackendClient(apiBase,{forcePolling:params.get('transport')==='polling'});engine=new ReplayEngine({client:backendClient,scenario:{name:'live_demo',start_day:90,days:1},onEvent:onEngineEvent,paused:true,onChange:()=>{if(engine)updateUI(engine.snapshot());}});engine.status='error';engine.error=backendNote;mode='backend';}
    }
  }
  if(!engine){
    engine=new GPUSimulation({gpuCount:24,initialJobs:12,onEvent:onEngineEvent});
    engine.setPolicy('priority');
    if(rackTestMode){
      mode='rack-test';
      const testState=mockRackState(params.get('rackState')||'stress'),baseSnapshot=engine.snapshot.bind(engine);
      engine.snapshot=()=>{const base=baseSnapshot(),queued=Object.values(testState.pools).reduce((n,p)=>n+p.queue_hp+p.queue_spot,0);return {...base,evidence:'clearly_labelled_mock_test_data',rackPools:testState.rackPools,pools:testState.pools,queue:[],stats:{...base.stats,queued},run:{...base.run,pools:testState.meta},testMode:{label:'Local mock rack test',phase:testState.phase}};};
      latestEvent=`Local rack test data · ${testState.phase} state`;
    }
    if(backendNote)latestEvent=`${backendNote} Showing the labelled synthetic demo instead.`;
  }
  const backendMode=mode==='backend';
  const facilityMode=backendMode||rackTestMode;
  const queueChips=[];
  if(backendMode){   // queue positions as chips above the gateway: the backend's queue head for the selected pool, in backend order
    for(let i=0;i<12;i++){const c=new THREE.Mesh(boxGeom,new THREE.MeshStandardMaterial({color:COLORS.reserved,emissive:COLORS.reserved,emissiveIntensity:.35}));c.scale.set(.34,.14,.34);c.position.set(portal.x,2.7+i*.2,portal.z);c.visible=false;c.name='Queue position chip';lab.add(c);queueChips.push(c);}
  }
  function choose(index){selected=index;selectedRackPool=null;engine.setFocusPool?.(null);engine.setFocusBoard?.(index);inspectRequest++;updateUI(engine.snapshot());}
  function chooseRack(poolId){selectedRackPool=poolId;engine.setFocusPool?.(poolId);inspectRequest++;updateUI(engine.snapshot());}
  function view(name){cameraView=name;
    const look=name==='gpu'?slots[selected].position.clone():name==='hall'?new THREE.Vector3(-11.5,1,7.5):new THREE.Vector3(-1,0,1);
    const eye=name==='gpu'?look.clone().add(new THREE.Vector3(.95,1.35,1.25)):name==='hall'?new THREE.Vector3(-19,14,18):new THREE.Vector3(44,43,47);
    viewer.cameraManager.flyTo(eye,look,!reducedMotion);viewer.enableRender();updateUI(engine.snapshot());
  }
  function updateUI(state){overlay?.update({snapshot:state,selected,selectedRackPool,paused,speed,cameraView,assetReady,latestEvent,inspectRequest,backend:backendMode,policies,presets,presetName:engine.scenario?.name,busy:state.status==='computing',fallbackNote:backendMode?null:backendNote});
    ui.dataset.ready='true';ui.dataset.assetLoaded=String(assetReady);ui.dataset.running=String(state.stats.running);ui.dataset.failed=String(state.stats.failed);ui.dataset.completed=String(state.stats.completed);ui.dataset.paused=String(paused);ui.dataset.gpuCount=String(state.gpus.length);ui.dataset.selectedGpu=state.gpus[selected].id;
    ui.dataset.mode=mode;ui.dataset.queued=String(state.stats.queued??state.queue.length);ui.dataset.selectedRackPool=selectedRackPool||'';
    if(backendMode){ui.dataset.connection=`${state.connection.mode}:${state.connection.status}`;ui.dataset.status=state.status;ui.dataset.simTime=String(Math.round(state.time));ui.dataset.alerts=String(state.stats.alerts);ui.dataset.policy=state.policy;ui.dataset.scenarioId=state.run.scenarioId||'';ui.dataset.error=state.error||'';}
  }
  const syntheticActions={onView:view,onSelectGPU:choose,
    onTogglePaused(){paused=!paused;updateUI(engine.snapshot());},
    onAddJob(){engine.submitJob({priority:'high',duration:8});updateUI(engine.snapshot());},
    onBurst(){engine.burst(28);updateUI(engine.snapshot());},
    onFailGPU(){engine.failGPU(selected);updateUI(engine.snapshot());},
    onRepairGPU(){engine.repairGPU(selected);updateUI(engine.snapshot());},
    onPolicy(policy){engine.setPolicy(policy);updateUI(engine.snapshot());},
    onSpeed(value){speed=value;updateUI(engine.snapshot());},
    onReset(){engine.reset();paused=reducedMotion;speed=1;engine.setPolicy('priority');updateUI(engine.snapshot());}
  };
  // What-if controls in backend mode only edit scenario parameters; the backend simulates and the room replays the result.
  const backendActions={onView:view,onSelectGPU:choose,
    onTogglePaused(){paused=!paused;engine.setPaused(paused);updateUI(engine.snapshot());},
    onAddJob(){return engine.addJob(engine.snapshot().gpus[selected].pool,{gpus:1,priority:'hp',duration_s:900});},
    onSubmitJob(job){return engine.addJob(job.pool,{gpus:job.gpus,priority:job.priority,duration_s:job.duration_s});},
    onBurst(){return engine.burst({duration_h:.5,mult:4});},
    onFailGPU(){return engine.failBoard(selected);},
    onRepairGPU(){return engine.repairBoard(selected);},
    onPolicy(name){return engine.setPolicy(name);},
    onSpeed(value){speed=value;engine.setSpeed(value);updateUI(engine.snapshot());},
    onReset(){return engine.reset();},
    onScenario(name){const sc=presets.find(p=>p.name===name);return sc?engine.selectScenario(sc):null;},
    onCooling(on){return engine.coolingFault(on);},
    onRetry(){return engine.load(engine.scenario,engine.policy,0);},
    onCompare(){return engine.compare();}
  };
  const actions=backendMode?backendActions:syntheticActions;
  overlay=mountOverlay(ui,actions,{snapshot:engine.snapshot(),selected,paused,speed,cameraView,assetReady,latestEvent,inspectRequest,backend:backendMode,policies,presets,presetName:engine.scenario?.name,busy:false,fallbackNote:backendMode?null:backendNote});
  const firstLoad=backendMode&&backendClient&&!engine.error?engine.load(engine.scenario,engine.policy,0):Promise.resolve();
  if(facilityMode){
    const rackIndices=[0,40,80,120,160,240];
    rackIndices.forEach((start,poolIndex)=>{
      const zone=new THREE.Group();zone.name=`Functional rack zone ${poolIndex+1}`;lab.add(zone);
      for(let offset=0;offset<20;offset++){
        const rack=room.getObjectByName(`Rack ${start+offset+1}`);if(!rack)continue;
        const bounds=new THREE.Box3().setFromObject(rack),center=bounds.getCenter(new THREE.Vector3()),size=bounds.getSize(new THREE.Vector3());
        const beacon=new THREE.Mesh(new THREE.BoxGeometry(Math.max(.16,size.x*.72),.055,Math.max(.16,size.z*.72)),new THREE.MeshStandardMaterial({color:COLORS.idle,emissive:COLORS.idle,emissiveIntensity:.75,transparent:true,opacity:.92}));
        beacon.position.set(center.x,bounds.max.y+.05,center.z);beacon.name='Backend pool rack beacon';beacon.userData.poolIndex=poolIndex;zone.add(beacon);
        const hitbox=new THREE.Mesh(new THREE.BoxGeometry(Math.max(.5,size.x),Math.max(2,size.y),Math.max(.5,size.z)),new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false}));
        hitbox.position.copy(center);hitbox.name='Backend pool rack hitbox';hitbox.userData.poolIndex=poolIndex;zone.add(hitbox);rackVisuals.push({beacon,hitbox,poolIndex});
      }
      if(zone.children.length){const b=new THREE.Box3().setFromObject(zone),c=b.getCenter(new THREE.Vector3());rackTargets.set(poolIndex,c);label(`POOL ${poolIndex+1} · AGGREGATE`,[c.x,b.max.y+.35,c.z],2.1);}
    });
  }
  function ancestorFan(object){for(let p=object;p;p=p.parent)if(/^FAN_[01]$/.test(p.name))return p;return null;}
  // Instance repeated GLB mesh primitives across all 24 boards: reuse Blender geometry.
  try{
    const gltf=await new THREEAddons.GLTFLoader().loadAsync('./assets/gpu/gpu-board.glb');gltf.scene.updateMatrixWorld(true);
    const groups=new Map();
    gltf.scene.traverse(part=>{if(!part.isMesh)return;const material=Array.isArray(part.material)?part.material[0]:part.material;const key=part.geometry.uuid+material.uuid;let group=groups.get(key);if(!group){group={geometry:part.geometry,material:material.clone(),parts:[]};groups.set(key,group);}const fan=ancestorFan(part);let pivot=null,local=null;if(fan){pivot=fan.matrixWorld.clone();local=fan.matrixWorld.clone().invert().multiply(part.matrixWorld);}group.parts.push({matrix:part.matrixWorld.clone(),pivot,local});});
    for(const group of groups.values()){
      const mesh=new THREE.InstancedMesh(group.geometry,group.material,group.parts.length*slots.length);mesh.name=`Blender GPU ${group.material.name}`;mesh.userData.instanceGPU=[];mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      const records=[];
      slots.forEach(slot=>{const base=new THREE.Matrix4().compose(slot.position,new THREE.Quaternion(),new THREE.Vector3(2.5,2.5,2.5));for(const part of group.parts){const index=records.length;const matrix=base.clone().multiply(part.matrix);mesh.setMatrixAt(index,matrix);mesh.userData.instanceGPU[index]=slot.index;records.push({index,gpuIndex:slot.index,base,part});}});
      mesh.computeBoundingSphere();lab.add(mesh);assetGroups.push({mesh,records,status:/STATUS_LED|GPU_DIE/i.test(group.material.name)});
    }
    assetReady=true;document.getElementById('room-loading')?.remove();
  }catch(error){console.error('GPU GLB failed to load',error);overlay.update({error:error.message});ui.dataset.assetError=error.message;const loading=document.getElementById('room-loading');if(loading)loading.textContent='GPU model could not load. Reload the page to retry.';}
  const raycaster=new THREE.Raycaster();raycaster.layers.enableAll();let down;
  const canvas=viewer.renderer.domElement;
  // The upstream viewer places an overlay canvas above its renderer canvas.
  // Listen on their common container so pointer events from either reach picking.
  document.addEventListener('pointerdown',e=>{if(e.target.closest?.('.gpu-ui, [data-ui-overlay]')){down=null;return;}down=[e.clientX,e.clientY];},true);
  document.addEventListener('pointerup',e=>{if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;ui.dataset.lastPointer=`${e.clientX},${e.clientY}`;const r=canvas.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),viewer.camera);const hit=raycaster.intersectObjects([...assetGroups.map(x=>x.mesh),...rings,...rackVisuals.map(x=>x.hitbox)],false)[0];ui.dataset.lastPick=hit?hit.object.name:'none';if(hit){const poolIndex=hit.object.userData.poolIndex;if(poolIndex!==undefined){const state=engine.snapshot(),pool=state.rackPools?.[poolIndex];if(pool)chooseRack(pool.id);return;}const index=hit.object.userData.gpuIndex??hit.object.userData.instanceGPU?.[hit.instanceId];if(index!==undefined)choose(index);}},true);
  for(let i=0;i<48;i++){const orb=new THREE.Mesh(new THREE.IcosahedronGeometry(.10,1),new THREE.MeshBasicMaterial({color:0x64dcbd}));orb.visible=false;lab.add(orb);particlePool.push(orb);}
  const spinMatrix=new THREE.Matrix4(),color=new THREE.Color();let visualTime=0,podLabelsSet=false;
  viewer.addEventListener(ViewerEvent.OnAnimate,({timeStamp})=>{
    const now=timeStamp/1000;const dt=lastTime===undefined?0:Math.min(Math.max(now-lastTime,0),.25);lastTime=now;
    if(!paused){engine.tick(dt*speed,dt);visualTime+=dt*speed;}
    const state=engine.snapshot();
    rackVisuals.forEach(v=>{const pool=state.rackPools?.[v.poolIndex];if(!pool)return;const c=COLORS[pool.status]||COLORS.idle;v.beacon.material.color.set(c);v.beacon.material.emissive.set(c);v.beacon.material.emissiveIntensity=pool.status==='overloaded'?.95:.65;});
    state.gpus.forEach((gpu,i)=>{const temp=backendMode?((gpu.temperature??40)-40)/45:((gpu.temperature??30)-30)/60;let c=gpu.status==='running'?color.set(COLORS.running).lerp(new THREE.Color(0xf05b3e),Math.max(0,Math.min(1,temp))):color.set(COLORS[gpu.status]||COLORS.idle);if(gpu.alert)c=color.set(0xff2d2d).lerp(new THREE.Color(0xffb199),.5+.5*Math.sin(visualTime*8));rings[i].material.color.copy(c);rings[i].material.emissive.copy(c);rings[i].material.emissiveIntensity=gpu.alert?.95:gpu.status==='running'?.55+.25*Math.sin(visualTime*6):.25;});
    for(const group of assetGroups){let animated=false;for(const record of group.records){const gpu=state.gpus[record.gpuIndex];if(group.status){color.set(gpu.alert?0xff2d2d:(COLORS[gpu.status]||COLORS.idle));group.mesh.setColorAt(record.index,color);}if(record.part.pivot){const angle=gpu.status==='failed'?0:visualTime*(gpu.status==='running'?30:5);spinMatrix.makeRotationY(angle);const m=record.base.clone().multiply(record.part.pivot).multiply(spinMatrix).multiply(record.part.local);group.mesh.setMatrixAt(record.index,m);animated=true;}}if(group.status&&group.mesh.instanceColor)group.mesh.instanceColor.needsUpdate=true;if(animated)group.mesh.instanceMatrix.needsUpdate=true;}
    particlePool.forEach(p=>p.visible=false);let particleIndex=0;
    for(const job of state.inFlight){let targets=(job.assignedGpuIds||[]).map(id=>state.gpus.find(g=>g.id===id)).filter(Boolean).map(g=>slots[g.index].position);if(!targets.length&&job.pool){const pi=state.rackPools?.findIndex(p=>p.id===job.pool),target=rackTargets.get(pi);if(target)targets=[target];}for(const target of targets){if(particleIndex>=particlePool.length)continue;const p=particlePool[particleIndex++];let t=1-Math.min(1,Math.max(0,job.transitRemaining/1.2));if(job.reverse)t=1-t;const start=portal.clone(),control=new THREE.Vector3((portal.x+target.x)/2,3.0,7.1);const curve=new THREE.QuadraticBezierCurve3(start,control,target);p.visible=true;p.position.copy(curve.getPoint(t));p.material.color.set(job.kind==='evict'?COLORS.failed:job.priority==='high'?COLORS.running:COLORS.reserved);p.scale.setScalar(1+.2*Math.sin(visualTime*16));}}
    if(backendMode){
      if(state.run.display&&!podLabelsSet){state.run.display.pods.forEach((p,k)=>relabel(podLabels[k],`POD ${k+1} · ${p.label.replace('NVIDIA ','').replace(' (unidentified)','*')}`.slice(0,34)));podLabelsSet=true;}
      state.queue.slice(0,queueChips.length).forEach((q,k)=>{const c=queueChips[k];c.visible=true;const col=q.priority==='high'?COLORS.running:COLORS.reserved;c.material.color.set(col);c.material.emissive.set(col);});
      for(let k=state.queue.length;k<queueChips.length;k++)queueChips[k].visible=false;
    }
    selector.position.copy(slots[selected].position);selector.position.y+=.05;selector.scale.setScalar(1+.035*Math.sin(visualTime*3));
    if(rackTestMode){const rect=canvas.getBoundingClientRect(),seen=new Set();ui.dataset.rackTargets=JSON.stringify(rackVisuals.filter(v=>!seen.has(v.poolIndex)&&seen.add(v.poolIndex)).map(v=>{const p=v.hitbox.getWorldPosition(v.hitbox.position.clone()).project(viewer.camera);return {poolIndex:v.poolIndex,x:rect.left+(p.x+1)*rect.width/2,y:rect.top+(1-p.y)*rect.height/2};}));}
    uiTime+=dt;if(uiTime>.15){updateUI(state);uiTime=0;}
    room.updateWorldMatrix(false,true);viewer.enableRender();
  });
  await firstLoad;
  updateUI(engine.snapshot());
  viewer.setHomeView({eye:new THREE.Vector3(44,43,47),look:new THREE.Vector3(-1,0,1)});view('hall');
  ui.dataset.gpuAssetMeshes=String(assetGroups.length);ui.dataset.sourceFoundation='thingraph/server-room';ui.dataset.rackTestMode=String(rackTestMode);
  return {engine,lab,selectGPU:choose,view,assetReady,mode,actions,presets,policies,backendNote};
}
