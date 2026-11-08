import { THREE, THREEAddons, ViewerEvent } from '@x-viewer/core';
import { GPUSimulation } from './gpu-simulation.js';

const COLORS={idle:0x20be92,reserved:0x62c9f1,running:0xf1b14a,cooling:0x64b8b4,failed:0xe94f64};

export async function mountGPULab({viewer,room}) {
  const ui=document.createElement('div');ui.className='gpu-ui';
  ui.innerHTML=`<header class="gpu-header"><div class="gpu-brand"><span class="gpu-brand-symbol">▦</span><div><div class="gpu-title">GPU Fabric</div><div class="gpu-subtitle">An interactive compute room</div></div></div><nav class="gpu-view-tabs" aria-label="Camera view"><button id="view-room" class="active">Room</button><button id="view-hall">GPU hall</button><button id="view-gpu">GPU detail</button></nav></header>
  <div class="gpu-hint"><kbd>Drag</kbd> to rotate · <kbd>Scroll</kbd> to zoom · Click a GPU to inspect</div>
  <aside class="gpu-panel" aria-label="GPU inspector"><div class="gpu-panel-head"><span class="gpu-eyebrow">Compute fabric</span><span class="gpu-live" id="live-label">RUNNING</span></div><div class="gpu-counts"><div><strong id="stat-active">0</strong><span>active</span></div><div><strong id="stat-queue">0</strong><span>queued</span></div><div><strong id="stat-done">0</strong><span>completed</span></div></div><section class="gpu-inspector"><div class="gpu-selected-title"><strong id="gpu-name">GPU-01</strong><span id="gpu-state" class="gpu-state">idle</span></div><div class="gpu-model">Illustrative accelerator · Pod 01</div><div class="gpu-metric"><span>Temperature</span><b id="gpu-temp">30 °C</b></div><div class="gpu-metric"><span>Utilisation</span><b id="gpu-util">0%</b></div><div class="gpu-metric"><span>Assigned job</span><b id="gpu-job">None</b></div><div class="gpu-metric"><span>Progress</span><b id="gpu-progress-label">0%</b></div><div class="gpu-progress"><i id="gpu-progress"></i></div><div class="gpu-mini-actions"><button id="gpu-fail" class="danger">Fail GPU</button><button id="gpu-repair">Repair</button></div><small id="gpu-availability">Available for new jobs</small></section><section class="gpu-queue"><div class="gpu-queue-title"><span>Incoming jobs</span><span id="queue-size">0 waiting</span></div><div class="gpu-queue-list" id="queue-list"></div></section><div class="gpu-log" id="event-log" aria-live="polite">Ready to dispatch jobs.</div></aside>
  <div class="gpu-legend"><span><i class="gpu-dot"></i>Available</span><span><i class="gpu-dot busy"></i>Processing</span><span><i class="gpu-dot failed"></i>Failed</span><span><i class="gpu-dot route"></i>In transit</span></div>
  <div class="gpu-dock" aria-label="Simulation controls"><button id="sim-pause" class="primary">Pause</button><button id="sim-add">+ Job</button><button id="sim-burst">Job burst</button><span class="gpu-divider"></span><select id="sim-policy" aria-label="Scheduling policy"><option value="priority">Priority first</option><option value="fcfs">First come, first served</option><option value="round_robin">Round robin</option></select><select id="sim-speed" aria-label="Playback speed"><option value="1">1× speed</option><option value="2">2× speed</option><option value="4">4× speed</option></select><button id="sim-reset">Reset</button></div>
  <div class="gpu-evidence">Illustrative jobs, assignments, failures and temperatures · Not a replay of measured cluster activity.</div>`;
  document.body.append(ui);
  const $=id=>document.getElementById(id);
  const lab=new THREE.Group();lab.name='GPU scheduling laboratory';room.add(lab);
  let paused=false,speed=1,selected=0,lastTime,uiTime=0,assetReady=false;
  const pods=[[-14.5,5],[-8.5,5],[-14.5,10],[-8.5,10]];
  const slots=[],rings=[],assetGroups=[],particlePool=[];
  const boxGeom=new THREE.BoxGeometry(1,1,1);
  const mat=(color,metalness=.25,roughness=.5)=>new THREE.MeshStandardMaterial({color,metalness,roughness});
  const dark=mat(0x243d3b,.65,.32),edge=mat(0xb7c8c4,.6,.38),plinth=mat(0xe3ebe6,.25,.55);
  function box(parent,name,size,position,material){const o=new THREE.Mesh(boxGeom,material);o.name=name;o.scale.set(...size);o.position.set(...position);parent.add(o);return o;}
  function label(text,position,size=1.5){const canvas=document.createElement('canvas');canvas.width=512;canvas.height=128;const ctx=canvas.getContext('2d');ctx.clearRect(0,0,512,128);ctx.fillStyle='#33584c';ctx.font='500 38px Arial';ctx.textAlign='center';ctx.fillText(text,256,78);const texture=new THREE.CanvasTexture(canvas);const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));sprite.position.set(...position);sprite.scale.set(size,size/4,1);lab.add(sprite);return sprite;}
  pods.forEach(([x,z],pod)=>{
    const p=new THREE.Group();p.position.set(x,0,z);p.name=`GPU Pod ${pod+1}`;lab.add(p);
    box(p,'Chassis',[2.85,1.0,1.85],[0,.55,0],dark);box(p,'Open compute tray',[3.0,.10,2.0],[0,1.10,0],edge);
    box(p,'Pod plinth',[3.16,.12,2.17],[0,.05,0],plinth);
    for(let j=0;j<6;j++){box(p,'Vent',[.32,.025,.018],[-1.03+j*.41,.72, .94],edge);box(p,'Vent',[.32,.025,.018],[-1.03+j*.41,.58,.94],edge);}
    label(`POD ${String(pod+1).padStart(2,'0')}`,[x,.3,z+1.1],1.3);
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
  const engine=new GPUSimulation({gpuCount:24,initialJobs:12,onEvent:event=>{
    $('event-log').textContent=`${eventNames[event.type]||event.type}${event.jobId?' · '+event.jobId:''}`;
  }});
  engine.setPolicy('priority');
  function choose(index){selected=index;updateUI(engine.snapshot());}
  function view(name){document.querySelectorAll('.gpu-view-tabs button').forEach(b=>b.classList.toggle('active',b.id===`view-${name}`));
    if(name==='room')viewer.flyTo(new THREE.Vector3(46,41,49),new THREE.Vector3(-1,0,1));
    if(name==='hall')viewer.flyTo(new THREE.Vector3(1,16,25),new THREE.Vector3(-12,0.8,7));
    if(name==='gpu'){const p=slots[selected].position;viewer.flyTo(p.clone().add(new THREE.Vector3(1.5,1.8,2.2)),p.clone());}
    viewer.enableRender();
  }
  $('view-room').onclick=()=>view('room');$('view-hall').onclick=()=>view('hall');$('view-gpu').onclick=()=>view('gpu');
  $('sim-pause').onclick=()=>{paused=!paused;$('sim-pause').textContent=paused?'Resume':'Pause';$('live-label').textContent=paused?'PAUSED':'RUNNING';};
  $('sim-add').onclick=()=>engine.submitJob({priority:'high',duration:8});$('sim-burst').onclick=()=>engine.burst(28);
  $('gpu-fail').onclick=()=>{engine.failGPU(selected);updateUI(engine.snapshot());};$('gpu-repair').onclick=()=>{engine.repairGPU(selected);updateUI(engine.snapshot());};
  $('sim-policy').onchange=e=>engine.setPolicy(e.target.value);$('sim-speed').onchange=e=>speed=Number(e.target.value);
  $('sim-reset').onclick=()=>{engine.reset();paused=false;speed=1;$('sim-pause').textContent='Pause';$('live-label').textContent='RUNNING';$('sim-speed').value='1';$('sim-policy').value='priority';engine.setPolicy('priority');updateUI(engine.snapshot());};
  function updateUI(state){const gpu=state.gpus[selected];$('stat-active').textContent=state.stats.running;$('stat-queue').textContent=state.queue.length;$('stat-done').textContent=state.stats.completed;
    $('gpu-name').textContent=gpu.id;$('gpu-state').textContent=gpu.status;$('gpu-state').className=`gpu-state ${gpu.status}`;
    ui.querySelector('.gpu-model').textContent=`Illustrative accelerator · Pod ${String(slots[selected].pod+1).padStart(2,'0')}`;
    $('gpu-temp').textContent=`${gpu.temperature.toFixed(1)} °C`;$('gpu-util').textContent=`${Math.round(gpu.utilisation)}%`;$('gpu-job').textContent=gpu.jobId||'None';$('gpu-progress-label').textContent=`${Math.round(gpu.progress*100)}%`;$('gpu-progress').style.width=`${gpu.progress*100}%`;
    $('gpu-availability').textContent=gpu.status==='failed'?'Unavailable until repaired':gpu.status==='idle'?'Available for new jobs':gpu.status==='reserved'?'Reserved · job travelling to GPU':gpu.status==='cooling'?'Cooling before next assignment':'Processing assigned job';
    $('gpu-fail').disabled=gpu.status==='failed';$('gpu-repair').disabled=gpu.status!=='failed';
    $('queue-size').textContent=`${state.queue.length} waiting`;$('queue-list').replaceChildren();
    state.queue.slice(0,8).forEach(job=>{const el=document.createElement('span');el.className=`gpu-job-chip ${job.priority==='high'?'high':''}`;el.textContent=job.id;$('queue-list').append(el);});
    if(!state.queue.length){const el=document.createElement('span');el.className='gpu-queue-empty';el.textContent='Queue clear · new jobs arrive automatically';$('queue-list').append(el);}
    ui.dataset.ready='true';ui.dataset.assetLoaded=String(assetReady);ui.dataset.running=String(state.stats.running);ui.dataset.failed=String(state.stats.failed);ui.dataset.completed=String(state.stats.completed);ui.dataset.paused=String(paused);ui.dataset.gpuCount=String(state.gpus.length);
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
    assetReady=true;
  }catch(error){console.error('GPU GLB failed to load',error);$('event-log').textContent='GPU model failed to load. Check the asset URL.';ui.dataset.assetError=error.message;}
  const raycaster=new THREE.Raycaster();raycaster.layers.enableAll();let down;
  const canvas=viewer.renderer.domElement;
  // The upstream viewer places an overlay canvas above its renderer canvas.
  // Listen on their common container so pointer events from either reach picking.
  document.addEventListener('pointerdown',e=>{if(e.target.closest?.('.gpu-ui')){down=null;return;}down=[e.clientX,e.clientY];},true);
  document.addEventListener('pointerup',e=>{if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;ui.dataset.lastPointer=`${e.clientX},${e.clientY}`;const r=canvas.getBoundingClientRect();raycaster.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),viewer.camera);const hit=raycaster.intersectObjects([...assetGroups.map(x=>x.mesh),...rings],false)[0];ui.dataset.lastPick=hit?hit.object.name:'none';if(hit){const index=hit.object.userData.gpuIndex??hit.object.userData.instanceGPU?.[hit.instanceId];if(index!==undefined)choose(index);}},true);
  for(let i=0;i<48;i++){const orb=new THREE.Mesh(new THREE.IcosahedronGeometry(.10,1),new THREE.MeshBasicMaterial({color:0x64dcbd}));orb.visible=false;lab.add(orb);particlePool.push(orb);}
  const spinMatrix=new THREE.Matrix4(),color=new THREE.Color();let visualTime=0;
  viewer.addEventListener(ViewerEvent.OnAnimate,({timeStamp})=>{
    const now=timeStamp/1000;const dt=lastTime===undefined?0:Math.min(Math.max(now-lastTime,0),.25);lastTime=now;
    if(!paused){engine.tick(dt*speed);visualTime+=dt*speed;}
    const state=engine.snapshot();
    state.gpus.forEach((gpu,i)=>{const temp=(gpu.temperature-30)/60;const c=gpu.status==='running'?color.set(COLORS.running).lerp(new THREE.Color(0xf05b3e),Math.max(0,Math.min(1,temp))):color.set(COLORS[gpu.status]||COLORS.idle);rings[i].material.color.copy(c);rings[i].material.emissive.copy(c);rings[i].material.emissiveIntensity=gpu.status==='running'?.55+.25*Math.sin(visualTime*6):.25;});
    for(const group of assetGroups){let animated=false;for(const record of group.records){const gpu=state.gpus[record.gpuIndex];if(group.status){color.set(COLORS[gpu.status]||COLORS.idle);group.mesh.setColorAt(record.index,color);}if(record.part.pivot){const angle=gpu.status==='failed'?0:visualTime*(gpu.status==='running'?30:5);spinMatrix.makeRotationY(angle);const m=record.base.clone().multiply(record.part.pivot).multiply(spinMatrix).multiply(record.part.local);group.mesh.setMatrixAt(record.index,m);animated=true;}}if(group.status&&group.mesh.instanceColor)group.mesh.instanceColor.needsUpdate=true;if(animated)group.mesh.instanceMatrix.needsUpdate=true;}
    particlePool.forEach(p=>p.visible=false);let particleIndex=0;
    for(const job of state.inFlight){for(const id of job.assignedGpuIds||[]){const gpu=state.gpus.find(g=>g.id===id);if(!gpu||particleIndex>=particlePool.length)continue;const p=particlePool[particleIndex++],target=slots[gpu.index].position;const t=1-Math.min(1,Math.max(0,job.transitRemaining/1.2));const start=portal.clone(),control=new THREE.Vector3((portal.x+target.x)/2,3.0,7.1);const curve=new THREE.QuadraticBezierCurve3(start,control,target);p.visible=true;p.position.copy(curve.getPoint(t));p.material.color.set(job.priority==='high'?COLORS.running:COLORS.reserved);p.scale.setScalar(1+.2*Math.sin(visualTime*16));}}
    selector.position.copy(slots[selected].position);selector.position.y+=.05;selector.scale.setScalar(1+.035*Math.sin(visualTime*3));
    uiTime+=dt;if(uiTime>.15){updateUI(state);uiTime=0;}
    room.updateWorldMatrix(false,true);viewer.enableRender();
  });
  updateUI(engine.snapshot());
  viewer.setHomeView({eye:new THREE.Vector3(46,41,49),look:new THREE.Vector3(-1,0,1)});view('room');
  ui.dataset.gpuAssetMeshes=String(assetGroups.length);ui.dataset.sourceFoundation='thingraph/server-room';
  return {engine,lab,selectGPU:choose,view,assetReady};
}
