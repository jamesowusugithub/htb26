import { buildRackPools } from './rack-fabric.js';

const META = [
  ['a100', 'NVIDIA A100', 96, 768], ['a10', 'NVIDIA A10', 128, 512],
  ['h800', 'NVIDIA H800', 80, 640], ['series1', 'Alibaba series 1', 120, 480],
  ['a800', 'NVIDIA A800', 72, 576], ['series2', 'Alibaba series 2', 64, 256],
].map(([id,label,nodes,capacity_gpus])=>({id,label,nodes,capacity_gpus}));

const PHASES = {
  normal: [[0,0,0],[220,0,0],[410,1,0],[0,0,0],[180,0,0],[96,0,0]],
  stress: [[740,8,14],[430,0,2],[615,6,4],[470,11,23],[510,2,7],[245,9,18]],
  failure: [[340,0,0],[250,0,0],[0,0,0],[210,1,0],[390,0,0],[0,0,0]],
};

export function mockRackState(phase='stress') {
  const values=PHASES[phase]||PHASES.stress;
  const pools=Object.fromEntries(META.map((m,i)=>{
    const [busy,queue_hp,queue_spot]=values[i],failed=phase==='failure'&&(i===2||i===5);
    return [m.id,{busy_gpus:busy,capacity_gpus:failed?0:m.capacity_gpus,queue_hp,queue_spot,running_jobs:Math.ceil(busy/8),max_free_gpus_on_one_node:failed?0:Math.max(0,8-Math.ceil((busy/m.capacity_gpus)*8)),queue_head:[]}];
  }));
  return {phase,pools,rackPools:buildRackPools(META,pools,[],null),meta:META};
}
