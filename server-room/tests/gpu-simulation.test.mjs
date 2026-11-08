import test from 'node:test';
import assert from 'node:assert/strict';
import {GPUSimulation} from '../gpu-simulation.js';

const empty = options => new GPUSimulation({gpuCount: 2, autoArrival: false, initialJobs: 0, ...options});

test('travel precedes processing and a completed job releases capacity', () => {
  const sim = empty({gpuCount: 1});
  sim.submitJob({duration: 1, priority: 'spot'});
  sim.tick(.1);
  assert.equal(sim.snapshot().gpus[0].status, 'reserved');
  sim.tick(1.2);
  assert.equal(sim.snapshot().gpus[0].status, 'running');
  sim.tick(1.2);
  assert.equal(sim.snapshot().stats.completed, 1);
  assert.equal(sim.snapshot().gpus[0].status, 'cooling');
  sim.tick(1.3);
  assert.equal(sim.snapshot().gpus[0].status, 'idle');
});

test('failure releases the whole gang and requeues once, failed device unavailable', () => {
  const sim = empty();
  const job = sim.submitJob({duration: 5, gpuCount: 2});
  sim.tick(1.5);
  assert.equal(sim.snapshot().stats.running, 2);
  sim.failGPU('GPU-01');
  assert.equal(sim.snapshot().stats.requeued, 1);
  assert.equal(sim.snapshot().gpus[0].status, 'failed');
  assert.equal(sim.snapshot().queue[0].id, job.id);
  sim.failGPU('GPU-01');
  assert.equal(sim.snapshot().stats.requeued, 1);
  sim.tick(10);
  assert.equal(sim.snapshot().stats.completed, 0);
  sim.repairGPU('GPU-01');
  sim.tick(8);
  assert.equal(sim.snapshot().stats.completed, 1);
});

test('priority admission preserves FIFO within priority and FCFS does not reorder', () => {
  const sim = empty({gpuCount: 1});
  const spot = sim.submitJob({priority: 'spot'});
  const hp = sim.submitJob({priority: 'high'});
  sim.tick(.01);
  assert.equal(sim.snapshot().gpus[0].jobId, hp.id);
  const fifo = empty({gpuCount: 1});
  fifo.setPolicy('fcfs');
  const first = fifo.submitJob({priority: 'spot'});
  fifo.submitJob({priority: 'high'});
  fifo.tick(.01);
  assert.equal(fifo.snapshot().gpus[0].jobId, first.id);
  assert.equal(sim.snapshot().queue[0].id, spot.id);
});

test('same seed and input steps produce identical state, zero tick does not advance', () => {
  const a = new GPUSimulation({gpuCount: 4, seed: 8});
  const b = new GPUSimulation({gpuCount: 4, seed: 8});
  a.tick(12); b.tick(12);
  assert.deepEqual(a.snapshot(), b.snapshot());
  const before = a.snapshot();
  a.tick(0);
  assert.deepEqual(a.snapshot(), before);
  const snap = a.snapshot(); snap.gpus[0].temperature = 900;
  assert.notEqual(a.snapshot().gpus[0].temperature, 900);
});

test('all failed GPUs admit no jobs and invalid resource requirements fail explicitly', () => {
  const sim = empty();
  sim.failGPU(0); sim.failGPU(1);
  sim.submitJob({duration: 2}); sim.tick(5);
  assert.equal(sim.snapshot().stats.queued, 1);
  assert.equal(sim.snapshot().stats.running, 0);
  assert.throws(() => sim.submitJob({gpuCount: 3}), RangeError);
  assert.throws(() => sim.tick(-1), RangeError);
});
