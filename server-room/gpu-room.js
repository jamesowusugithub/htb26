import { THREE, THREEAddons, ViewerEvent } from '@x-viewer/core';
import { GPUSimulation } from './gpu-simulation.js';
import { mountOverlay } from './ui-dist/overlay.js';

const COLORS={idle:0x20be92,reserved:0x62c9f1,running:0xf1b14a,cooling:0x64b8b4,failed:0xe94f64};

export async function mountGPULab({viewer,room}) {
  const ui=document.createElement('div');ui.className='gpu-ui';document.body.append(ui);
  let overlay=null,latestEvent='Ready to dispatch jobs.',cameraView='hall',inspectRequest=0;
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let paused=reducedMotion,speed=1,selected=0,lastTime,uiTime=0,assetReady=false;
  const lab=new THREE.Group();lab.name='GPU scheduling laboratory';room.add(lab);
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
    latestEvent=`${eventNames[event.type]||event.type}${event.jobId?' · '+event.jobId:''}`;overlay?.update({latestEvent});
  }});
  engine.setPolicy('priority');
  function choose(index){selected=index;inspectRequest++;updateUI(engine.snapshot());}
  function view(name){cameraView=name;
    const look=name==='gpu'?slots[selected].position.clone():name==='hall'?new THREE.Vector3(-11.5,1,7.5):new THREE.Vector3(-1,0,1);
    const eye=name==='gpu'?look.clone().add(new THREE.Vector3(.95,1.35,1.25)):name==='hall'?new THREE.Vector3(-19,14,18):new THREE.Vector3(44,43,47);
    viewer.cameraManager.flyTo(eye,look,!reducedMotion);viewer.enableRender();updateUI(engine.snapshot());
  }
  function updateUI(state){overlay?.update({snapshot:state,selected,paused,speed,cameraView,assetReady,latestEvent,inspectRequest});
    ui.dataset.ready='true';ui.dataset.assetLoaded=String(assetReady);ui.dataset.running=String(state.stats.running);ui.dataset.failed=String(state.stats.failed);ui.dataset.completed=String(state.stats.completed);ui.dataset.paused=String(paused);ui.dataset.gpuCount=String(state.gpus.length);ui.dataset.selectedGpu=state.gpus[selected].id;
  }
  const actions={onView:view,onSelectGPU:choose,
    onTogglePaused(){paused=!paused;updateUI(engine.snapshot());},
    onAddJob(){engine.submitJob({priority:'high',duration:8});updateUI(engine.snapshot());},
    onBurst(){engine.burst(28);updateUI(engine.snapshot());},
    onFailGPU(){engine.failGPU(selected);updateUI(engine.snapshot());},
    onRepairGPU(){engine.repairGPU(selected);updateUI(engine.snapshot());},
    onPolicy(policy){engine.setPolicy(policy);updateUI(engine.snapshot());},
    onSpeed(value){speed=value;updateUI(engine.snapshot());},
    onReset(){engine.reset();paused=reducedMotion;speed=1;engine.setPolicy('priority');updateUI(engine.snapshot());}
  };
  overlay=mountOverlay(ui,actions,{snapshot:engine.snapshot(),selected,paused,speed,cameraView,assetReady,latestEvent,inspectRequest});
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
  viewer.setHomeView({eye:new THREE.Vector3(44,43,47),look:new THREE.Vector3(-1,0,1)});view('hall');
  ui.dataset.gpuAssetMeshes=String(assetGroups.length);ui.dataset.sourceFoundation='thingraph/server-room';
  return {engine,lab,selectGPU:choose,view,assetReady};
}
