import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRackPools, rackIndicesForPool } from '../rack-fabric.js';
import { mockRackState } from '../rack-test-data.js';

test('maps six pools to separate columns of 20 visual racks', () => {
  const groups=Array.from({length:6},(_,i)=>rackIndicesForPool(i));
  assert.ok(groups.every(g=>g.length===20));
  assert.equal(new Set(groups.flat()).size,120);
});

test('uses backend pool values and labels overload without inventing node detail', () => {
  const pools=buildRackPools([{id:'a100',label:'A100',nodes:12,capacity_gpus:96}],{a100:{busy_gpus:90,capacity_gpus:96,queue_hp:2,queue_spot:3,running_jobs:7,max_free_gpus_on_one_node:0}},[],null);
  assert.equal(pools[0].status,'overloaded');
  assert.equal(pools[0].queue,5);
  assert.equal(pools[0].capacityGpus,96);
  assert.equal(pools[0].thermalAvailable,false);
});

test('aggregates mapped board failures and proxy temperature only where supplied', () => {
  const display={boards:[{pool:'a100',nodes:4},{pool:'a100',nodes:4}]};
  const boards=[{nodes:4,nodes_down:4,temp_c:78,alert:true},{nodes:4,nodes_down:0,temp_c:65,alert:false}];
  const [pool]=buildRackPools([{id:'a100',label:'A100',nodes:8,capacity_gpus:64}],{a100:{busy_gpus:8,capacity_gpus:64}},boards,display);
  assert.equal(pool.nodesDown,4);assert.equal(pool.nodesMapped,8);assert.equal(pool.maxTemperature,78);assert.equal(pool.thermalAlerts,1);
});

test('local rack test phases exercise idle, busy, overloaded and failed indicators',()=>{
  const statuses=new Set(['normal','stress','failure'].flatMap(phase=>mockRackState(phase).rackPools.map(pool=>pool.status)));
  assert.deepEqual([...statuses].sort(),['busy','failed','idle','overloaded']);
});
