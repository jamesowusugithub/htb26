"""Gymnasium environment: choose which queued job to start (masked), on a window of the Alibaba trace.

Reward = -(weighted queue-time accrued since the last step) / q_ref, q_ref a fixed constant (~median priority-FIFO
queue-time on training windows). Weighted queue-time = HP job-hours x1 + spot job-hours x0.3 (Little's law: total
weighted wait). `info['qint_ratio_vs_priority_fifo']` reports the episode total relative to priority-FIFO.
Work-conserving by default: the 'advance' action is masked while any candidate fits (`allow_hold=True` lifts this).
"""
from __future__ import annotations
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from . import data
from .policies import POLICIES
from .sim import (build_state, PRIO_FIFO, FC_QINT, FC_CLOUDCOST, SC_ERR, SC_NPREEMPT, SC_NRUN, SC_DONE)
from .rl_core import run_until_decision, apply_action
from .metrics import summarize
from .whatif import Scenario, build_workload, build_cluster, sim_kwargs
from .run_baselines import run_policy


class SchedulingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, jobs, cluster, hint, *, train_days=(45.0, 125.0), days=3.0, arrival_mult=(0.8, 1.4),
                 capacity_jitter=(0.9, 1.1), K=8, D=512, seed=0, max_steps=400_000, q_ref=1e5, allow_hold=False, fixed=None, log_events=False, snapshot_dt=None,
                 burst_prob=0.0, offload=False, cloud_prob=0.0, cost_weight=0.0, offload_min_wait_s=1800.0):
        super().__init__()
        self.jobs, self.base_cluster, self.hint = jobs, cluster, hint
        self.train_days, self.days, self.arrival_mult, self.capacity_jitter = train_days, days, arrival_mult, capacity_jitter
        self.K, self.D, self.max_steps, self.q_ref, self.allow_hold = K, D, max_steps, q_ref, allow_hold
        self.log_events, self.snapshot_dt = log_events, snapshot_dt
        self.offload, self.cloud_prob, self.cost_weight, self.offload_min_wait_s = offload, cloud_prob, cost_weight, offload_min_wait_s
        self.burst_prob = burst_prob          # chance a training episode gets a BurstGPT (trace 1/2) arrival shape
        self.fixed = fixed                       # dict(start_day, days, arrival_mult, capacity, seed) for evaluation
        self.rng = np.random.default_rng(seed)
        P = cluster.n_pools
        self.observation_space = spaces.Box(-1.0, 10.0, shape=(P + 6 + K * 8 + (2 if offload else 0),), dtype=np.float32)
        self.action_space = spaces.Discrete(K + (2 if offload else 1))   # K candidate slots + "advance" (+ "send head to the simulated cloud")
        self.S = None

    # ------------------------------------------------------------------ helpers
    def _scenario(self, options):
        if options and "scenario" in options:
            return options["scenario"]
        if self.fixed is not None:
            return Scenario(**self.fixed)
        lo, hi = self.train_days
        start = float(self.rng.uniform(lo, hi - self.days))
        cap = float(self.rng.uniform(*self.capacity_jitter))
        prof, src = (None, None)
        if self.burst_prob > 0 and self.rng.random() < self.burst_prob:
            from .burst_profiles import sample
            prof, src = sample(self.rng, hours=int(np.ceil(self.days * 24)))
        cloud = None
        if self.cloud_prob > 0 and self.rng.random() < self.cloud_prob:       # SIMULATED cloud capacity for this training episode
            cloud = {"nodes_per_pool": int(self.rng.choice([2, 5, 10])), "gpus_per_node": 8, "overflow_wait_s": 0.0, "max_job_cost_usd": 30.0,
                     "offload_min_wait_s": self.offload_min_wait_s}
        return Scenario(start_day=start, days=self.days, arrival_mult=float(self.rng.uniform(*self.arrival_mult)),
                        capacity=cap, seed=int(self.rng.integers(1 << 30)), arrival_profile=prof, arrival_profile_source=src, cloud=cloud)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if options and "workload" in options:       # caller-supplied workload + cluster (used by the restaurant demo kitchen)
            self.sc = options.get("scenario") or Scenario(days=float(options.get("days", 1.0)))
            self.w, self.cluster = options["workload"], options["cluster"]
        else:
            self.sc = self._scenario(options)
            self.w = build_workload(self.jobs, self.sc)
            self.cluster = build_cluster(self.base_cluster, self.sc)
        est = self.hint.predict_seconds(self.w.job_id)
        est = np.where(np.isfinite(est), est, np.nanmedian(est)).astype(np.float64)
        self.est = est
        self.sim_kw = (options or {}).get("sim_kw") or sim_kwargs(self.sc, self.cluster)
        if self.sim_kw.get("util_cap", 1.0) < 1.0:
            raise ValueError("thermal derating is not supported by the RL environment (its fit mask does not model the cap); use the rule-based policies")
        ref_kw = dict(self.sim_kw)
        if ref_kw.get("overflow_wait_s", 0) > 0:
            ref_kw["overflow_est"] = est        # reference run prices cloud offloads with the hint too
        base = run_policy(self.cluster, self.w, POLICIES["priority_fifo"], snapshot_dt=None, **ref_kw)
        self.base_qint = max(float(base.fc[FC_QINT]), 1e-6)
        self.S = build_state(self.cluster, self.w, PRIO_FIFO, preempt=True, est=est, early_stop=False,
                             snapshot_dt=self.snapshot_dt, log_events=self.log_events, rl_k=self.K, rl_offload=self.offload, **self.sim_kw)
        self.steps = 0
        self.stall = 0
        self.n_started = 0
        self.last_q = 0.0
        self.last_q = 0.0                       # queue time accrued before the first decision counts toward step 1
        self.last_c = 0.0
        self.done = run_until_decision(self.S, self.D) == 1
        return self.S.obs.copy(), {"scenario_id": self.sc.scenario_id}

    def action_masks(self) -> np.ndarray:
        if self.done:
            return np.ones(self.K + (2 if self.offload else 1), dtype=bool)
        m = self.S.amask.astype(bool)
        if not self.allow_hold and (m[: self.K].any() or (self.offload and m[self.K + 1])):
            m[self.K] = False
        return m

    def step(self, action):
        S = self.S
        bad = apply_action(S, int(action)) if not self.done else 0
        self.steps += 1
        self.done = self.done or run_until_decision(S, self.D) == 1
        q = float(S.fc[FC_QINT])
        cst = float(S.fc[FC_CLOUDCOST])
        reward = -((q - self.last_q) + self.cost_weight * (cst - self.last_c)) / self.q_ref - (0.01 if bad else 0.0)   # cost_weight: weighted job-hours per USD
        self.last_q, self.last_c = q, cst
        started = int(S.sc[SC_NRUN]) + int(S.sc[SC_DONE])
        self.stall = 0 if started != self.n_started else self.stall + 1
        self.n_started = started
        truncated = (not self.done) and (self.steps >= self.max_steps or self.stall > 5000)
        info = {}
        if self.done or truncated:
            info["metrics"] = self.final_metrics()
            info["qint_ratio_vs_priority_fifo"] = q / self.base_qint
            info["cloud_cost_usd"] = cst
        return S.obs.copy(), reward, bool(self.done), bool(truncated), info

    def final_metrics(self):
        return summarize(self.S, self.w, self.cluster, util_hi=self.sc.days * 86400)
