/**
 * Synthetic, deterministic event demo for the server-room visualisation.
 * These temperatures, runtimes, device identities and failures are illustrative.
 * No values are measured telemetry, learned predictions or replayed placement.
 *
 * API: new GPUSimulation({ gpuCount, seed, autoArrival, arrivalInterval,
 * initialJobs, onEvent }); tick(seconds); submitJob({priority,duration,gpuCount});
 * burst(count); failGPU(id); repairGPU(id); setPolicy('fcfs'|'priority'|'round-robin');
 * reset(); snapshot(); subscribe(listener) -> unsubscribe function.
 * Durations and time use seconds, temperatures Celsius, utilisation percent.
 */
export class GPUSimulation {
  constructor({gpuCount = 24, seed = 26, autoArrival = true, arrivalInterval = 1.8,
    initialJobs = 8, onEvent} = {}) {
    if (!Number.isInteger(gpuCount) || gpuCount < 1) throw new RangeError('gpuCount must be a positive integer');
    this.options = {gpuCount, seed: seed >>> 0, autoArrival, arrivalInterval: Math.max(0.2, arrivalInterval), initialJobs};
    this.listeners = new Set(onEvent ? [onEvent] : []);
    this.reset();
  }

  reset() {
    this.time = 0;
    this.randomState = this.options.seed || 1;
    this.policy = this.policy || 'priority';
    this.nextJob = 1;
    this.roundRobinCursor = 0;
    this.arrivalClock = 0;
    this.gpus = Array.from({length: this.options.gpuCount}, (_, i) => ({
      id: `GPU-${String(i + 1).padStart(2, '0')}`, index: i, model: 'H100 schematic',
      status: 'idle', temperature: 34 + (i % 4), utilisation: 0,
      jobId: null, completed: 0, failed: 0, progress: 0, cooldownRemaining: 0,
    }));
    this.jobs = new Map();
    this.queue = [];
    this.events = [];
    this.stats = {submitted: 0, completed: 0, failureEvents: 0, requeued: 0};
    this.emit('reset');
    this.burst(Math.min(this.options.initialJobs, this.options.gpuCount));
    return this.snapshot();
  }

  random() {
    this.randomState = (Math.imul(1664525, this.randomState) + 1013904223) >>> 0;
    return this.randomState / 4294967296;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(type, details = {}) {
    const event = {type, time: this.time, ...details};
    this.events.push(event);
    if (this.events.length > 80) this.events.shift();
    for (const listener of this.listeners) listener(event);
  }

  submitJob({priority, duration, gpuCount = 1, label} = {}) {
    if (!Number.isInteger(gpuCount) || gpuCount < 1 || gpuCount > this.gpus.length) {
      throw new RangeError('Job GPU count must fit the demo cluster');
    }
    const seconds = duration ?? 4 + this.random() * 8;
    if (!Number.isFinite(seconds) || seconds <= 0) throw new RangeError('Job duration must be positive');
    const job = {
      id: `JOB-${String(this.nextJob++).padStart(4, '0')}`,
      label: label || 'GPU workload', priority: priority === 'high' || priority === 'HP' ? 'high' : priority === 'spot' ? 'spot' : (this.random() < 0.3 ? 'high' : 'spot'),
      duration: seconds, gpuCount, status: 'queued', submittedAt: this.time,
      dispatchedAt: null, startedAt: null, completedAt: null,
      assignedGpuIds: [], progress: 0, remaining: seconds, transitRemaining: 0,
      attempts: 0, requeues: 0,
    };
    this.jobs.set(job.id, job);
    this.queue.push(job.id);
    this.stats.submitted++;
    this.emit('job-arrival', {jobId: job.id, priority: job.priority});
    return {...job};
  }

  burst(count = 12) {
    const created = [];
    for (let i = 0; i < Math.max(0, Math.floor(count)); i++) created.push(this.submitJob());
    return created;
  }

  setPolicy(policy) {
    const aliases = {'high-priority': 'priority', 'round_robin': 'round-robin', FCFS: 'fcfs'};
    const value = aliases[policy] || policy;
    if (!['fcfs', 'priority', 'round-robin'].includes(value)) throw new RangeError('Unknown demo policy');
    this.policy = value;
    this.emit('policy-change', {policy: value});
  }

  gpu(id) {
    const result = typeof id === 'number' ? this.gpus[id] : this.gpus.find(g => g.id === id);
    if (!result) throw new RangeError(`Unknown GPU: ${id}`);
    return result;
  }

  failGPU(id) {
    const gpu = this.gpu(id);
    if (gpu.status === 'failed') return false;
    const job = gpu.jobId ? this.jobs.get(gpu.jobId) : null;
    gpu.status = 'failed';
    gpu.failed++;
    gpu.utilisation = 0;
    gpu.jobId = null;
    gpu.progress = 0;
    this.stats.failureEvents++;
    this.emit('gpu-failed', {gpuId: gpu.id, jobId: job?.id ?? null});
    if (job && ['in-flight', 'running'].includes(job.status)) {
      for (const otherId of job.assignedGpuIds) {
        const other = this.gpu(otherId);
        if (other.id !== gpu.id) {
          other.status = 'cooling';
          other.cooldownRemaining = 0.8;
          other.jobId = null;
          other.progress = 0;
          other.utilisation = 0;
        }
      }
      job.status = 'queued';
      job.assignedGpuIds = [];
      job.progress = 0;
      job.remaining = job.duration;
      job.transitRemaining = 0;
      job.startedAt = null;
      job.dispatchedAt = null;
      job.requeues++;
      this.queue.unshift(job.id);
      this.stats.requeued++;
      this.emit('job-requeued', {jobId: job.id, failedGpuId: gpu.id});
    }
    return true;
  }

  repairGPU(id) {
    const gpu = this.gpu(id);
    if (gpu.status !== 'failed') return false;
    gpu.status = 'cooling';
    gpu.cooldownRemaining = 1;
    this.emit('gpu-repaired', {gpuId: gpu.id});
    return true;
  }

  dispatch() {
    if (this.policy === 'priority') {
      this.queue.sort((a, b) => Number(this.jobs.get(b).priority === 'high') - Number(this.jobs.get(a).priority === 'high') || this.jobs.get(a).submittedAt - this.jobs.get(b).submittedAt);
    }
    while (this.queue.length) {
      const job = this.jobs.get(this.queue[0]);
      let available = this.gpus.filter(g => g.status === 'idle');
      if (available.length < job.gpuCount) break; // Conservative head-of-line admission.
      if (this.policy === 'round-robin') {
        available.sort((a, b) => ((a.index - this.roundRobinCursor + this.gpus.length) % this.gpus.length) - ((b.index - this.roundRobinCursor + this.gpus.length) % this.gpus.length));
      }
      const selected = available.slice(0, job.gpuCount);
      this.roundRobinCursor = (selected.at(-1).index + 1) % this.gpus.length;
      this.queue.shift();
      job.status = 'in-flight';
      job.dispatchedAt = this.time;
      job.transitRemaining = 1.2;
      job.assignedGpuIds = selected.map(g => g.id);
      job.attempts++;
      for (const gpu of selected) {
        gpu.status = 'reserved';
        gpu.jobId = job.id;
        gpu.progress = 0;
      }
      this.emit('job-dispatch', {jobId: job.id, gpuIds: [...job.assignedGpuIds], travelDuration: 1.2});
    }
  }

  tick(dt) {
    if (!Number.isFinite(dt) || dt < 0) throw new RangeError('tick expects finite nonnegative seconds');
    if (dt === 0) return this.snapshot();
    let remaining = dt;
    while (remaining > 1e-9) {
      const step = Math.min(0.05, remaining);
      remaining -= step;
      this.time += step;
      if (this.options.autoArrival) {
        this.arrivalClock += step;
        while (this.arrivalClock >= this.options.arrivalInterval) {
          this.arrivalClock -= this.options.arrivalInterval;
          if (this.queue.length < 200) this.submitJob();
        }
      }
      for (const gpu of this.gpus) {
        if (gpu.status === 'cooling') {
          gpu.cooldownRemaining -= step;
          if (gpu.cooldownRemaining <= 1e-9) { gpu.status = 'idle'; gpu.cooldownRemaining = 0; }
        }
        const target = gpu.status === 'running' ? 77 + (gpu.index % 4) * 2 : 34 + (gpu.index % 4);
        gpu.temperature += (target - gpu.temperature) * (1 - Math.exp(-step / (gpu.status === 'running' ? 4 : 7)));
        gpu.utilisation = gpu.status === 'running' ? 88 + (gpu.index % 5) * 2 : 0;
      }
      for (const job of this.jobs.values()) {
        if (job.status === 'in-flight') {
          job.transitRemaining = Math.max(0, job.transitRemaining - step);
          if (job.transitRemaining <= 1e-9) {
            job.status = 'running';
            job.startedAt = this.time;
            for (const id of job.assignedGpuIds) this.gpu(id).status = 'running';
            this.emit('job-start', {jobId: job.id, gpuIds: [...job.assignedGpuIds]});
          }
        } else if (job.status === 'running') {
          job.remaining = Math.max(0, job.remaining - step);
          job.progress = Math.min(1, 1 - job.remaining / job.duration);
          for (const id of job.assignedGpuIds) this.gpu(id).progress = job.progress;
          if (job.remaining <= 1e-9) {
            job.status = 'completed'; job.completedAt = this.time; job.progress = 1;
            this.stats.completed++;
            for (const id of job.assignedGpuIds) {
              const gpu = this.gpu(id);
              gpu.status = 'cooling'; gpu.cooldownRemaining = 1.2;
              gpu.completed++; gpu.jobId = null; gpu.progress = 0; gpu.utilisation = 0;
            }
            this.emit('job-complete', {jobId: job.id, gpuIds: [...job.assignedGpuIds]});
          }
        }
      }
      this.dispatch();
    }
    return this.snapshot();
  }

  snapshot() {
    const jobs = [...this.jobs.values()].map(j => ({...j, assignedGpuIds: [...j.assignedGpuIds]}));
    const jobsById = new Map(jobs.map(job => [job.id, job]));
    const counts = Object.fromEntries(['idle', 'reserved', 'running', 'cooling', 'failed'].map(s => [s, this.gpus.filter(g => g.status === s).length]));
    return {time: this.time, policy: this.policy, evidence: 'synthetic_demo',
      gpus: this.gpus.map(g => ({...g})), jobs,
      queue: this.queue.map(id => jobsById.get(id)),
      inFlight: jobs.filter(j => j.status === 'in-flight'),
      stats: {...this.stats, queued: this.queue.length, ...counts},
      events: this.events.map(e => ({...e}))};
  }
}

export {GPUSimulation as SimulationEngine};
