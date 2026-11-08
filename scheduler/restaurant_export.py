"""Export a REAL-TRACE run in the event format of the 2D restaurant animation (restaurant/).

What is real: the jobs (arrival time, GPU request, priority, duration) are Alibaba trace rows; every decision comes from
our simulator / trained RL policy; the predicted runtime shown for each customer is our hint model's prediction.
What is a deliberate demo simplification (and is written into the recording's `trace_meta` so the UI can say so):
the kitchen is SMALL (a few A100 nodes instead of ~290), because the real pool has thousands of concurrent jobs and the
scene can show about a dozen. Temperatures are the thermal PROXY; nothing about VRAM, deadlines, SLO or cost is invented
(those fields are neutral and hidden in trace mode).
"""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np
import pandas as pd
from . import data
from .data import UNIT, Cluster, Workload
from .duration_model import DurationHint
from .policies import POLICIES
from .run_baselines import run_policy
from .sim import (EV_ARRIVE, EV_START, EV_FINISH, EV_PREEMPT, EV_NODEEVICT, SC_NEV)
from .thermal import ThermalProxy

TICK_S = 60.0                                     # one animation tick = one simulated minute
SCHED_LABEL = {"fifo": "fifo", "priority_fifo": "priority", "sjf_hint": "hint", "rl_ppo": "rl"}
CHEFS = [("premium-0", "A100 node 1", "premium"), ("premium-1", "A100 node 2", "premium"), ("standard-0", "A100 node 3", "standard"),
         ("standard-1", "A100 node 4", "standard"), ("standard-2", "A100 node 5", "standard")]


@dataclass
class Kitchen:
    workload: Workload
    cluster: Cluster
    meta: dict


def build_kitchen(jobs: pd.DataFrame, pools: list[dict], start_day: float, minutes: float, pool_id: str = "a100",
                  nodes: int = 5, gpus_per_node: int = 8) -> Kitchen:
    pidx = [p["id"] for p in pools].index(pool_id)
    sub = jobs[(jobs.pool == pidx)]
    s, e = start_day * 86400, start_day * 86400 + minutes * 60
    w = data.make_workload(sub, s, e, carryover=False)
    node_pool = np.full(nodes, pidx, dtype=np.int64)
    cl = Cluster(pools, node_pool, np.full(nodes, gpus_per_node, dtype=np.int64), np.ones(len(pools)))
    meta = {"source": "Alibaba GPU trace (harmonised jobs.parquet)", "pool": pool_id, "window_start_day": start_day, "window_minutes": minutes,
            "jobs": int(len(w)), "kitchen_nodes": nodes, "gpus_per_node": gpus_per_node,
            "real_pool_nodes_in_simulation": "about 290 A100 nodes", "time_unit": "min", "tick_s": TICK_S,
            "scale_note": f"Real jobs, small demo kitchen ({nodes} A100 nodes instead of ~290) so queues are visible. Scale is illustrative; the full-scale numbers are in the scoreboard."}
    return Kitchen(w, cl, meta)


def _run_sim(k: Kitchen, policy: str, hint: DurationHint):
    spec = POLICIES[policy]
    est = None
    if spec.est_mode == "hint":
        est = hint.predict_seconds(k.workload.job_id)
        est = np.where(np.isfinite(est), est, np.nanmedian(est))
    S = run_policy(k.cluster, k.workload, spec, est=est, log_events=True, snapshot_dt=None, early_stop=False)
    return S, {}


def _run_rl(k: Kitchen, jobs: pd.DataFrame, hint: DurationHint, model, K: int):
    from .env import SchedulingEnv
    env = SchedulingEnv(jobs, k.cluster, hint, K=K, log_events=True, snapshot_dt=None)
    obs, _ = env.reset(options={"workload": k.workload, "cluster": k.cluster, "days": 1.0})
    info_by_job, done = {}, False
    while not done:
        mask = env.action_masks()
        a = int(model.predict(obs, action_masks=mask, deterministic=True)[0])
        if a < K and env.S.cand_job[a] >= 0:
            j = int(env.S.cand_job[a]); p = int(env.S.pool[j])
            info_by_job.setdefault(j, []).append({"valid": int(mask[:K].sum()), "total": K, "queue_len": int(env.S.qc[p])})
        obs, r, te, tr, _ = env.step(a)
        done = te or tr
    return env.S, info_by_job


def to_recording(k: Kitchen, S, policy: str, hint: DurationHint, info_by_job: dict, max_ticks: int, thermal: ThermalProxy | None = None,
                 scheduler_note: str = "") -> dict:
    thermal = thermal or ThermalProxy.load()
    w, n_chefs = k.workload, len(CHEFS)
    tick = lambda t: int(t // TICK_S)
    est = hint.predict_seconds(w.job_id)
    est = np.where(np.isfinite(est), est, np.nanmedian(est))
    cfg = {"nodes": [{"id": "node-0", "gpus": [{"id": c[0], "tier": c[2], "vram_gb": int(k.cluster.node_ngpu[i]), "compute": 1, "name": c[1]} for i, c in enumerate(CHEFS[:2])]},
                     {"id": "node-1", "gpus": [{"id": c[0], "tier": c[2], "vram_gb": int(k.cluster.node_ngpu[i + 2]), "compute": 1, "name": c[1]} for i, c in enumerate(CHEFS[2:])]}],
           "thresholds": {"warning": 75, "critical": 85}, "overflow_threshold": 10, "scheduler": SCHED_LABEL[policy], "trace": True}
    start_of = {}
    raw = []                                                  # (tick, order, event-dict-without-seq)
    order = 0
    busy = np.zeros(n_chefs); queued = set(); running = {}
    done_n = 0; recv = 0; waits = []
    temp = np.full(n_chefs, float(thermal.target(0.0)[0]))
    arrival_job = {}
    ev_t, ev_type, ev_job, ev_node = S.ev_t, S.ev_type, S.ev_job, S.ev_node
    by_tick: dict[int, list] = {}
    for i in range(int(S.sc[SC_NEV])):
        t = float(ev_t[i])
        if t < 0 or tick(t) > max_ticks:
            continue
        by_tick.setdefault(tick(t), []).append(i)
    pool_start = int(S.pool_start[w.pool[0]]) if len(w) else 0
    out = []
    job_dict = lambda j: {"id": str(w.job_id[j]), "priority": "high" if w.prio[j] == 0 else "low", "vram_gb": float(w.req[j] / UNIT), "compute_units": float(w.req[j] / UNIT),
                          "duration_s": max(1, math.ceil(w.dur[j] / TICK_S)), "deadline_t": 10 ** 6, "splittable": False, "tiers": ["premium", "standard"],
                          "hint_min": round(float(est[j]) / 60.0, 1), "gpus": float(w.req[j] / UNIT), "arrival_t": tick(float(w.submit[j]))}
    out.append({"t": 0, "type": "SCHEDULER_CHANGED", "scheduler": SCHED_LABEL[policy]})
    for tk in range(0, max_ticks + 1):
        for i in by_tick.get(tk, []):
            typ, j = int(ev_type[i]), int(ev_job[i])
            if typ == EV_ARRIVE:
                recv += 1; queued.add(j); out.append({"t": tk, "type": "JOB_ARRIVED", "job": job_dict(j)})
            elif typ == EV_START:
                chef = int(ev_node[i]) - pool_start
                queued.discard(j); running[j] = chef; busy[chef] += w.req[j] / UNIT
                inf = (info_by_job.get(j) or [{}])[-1] if info_by_job else {}
                qlen = inf.get("queue_len", len(queued))
                out.append({"t": tk, "type": "DECISION", "job_id": str(w.job_id[j]), "action": "assign", "target_gpu_ids": [CHEFS[chef][0]], "scheduler": SCHED_LABEL[policy],
                            "factors": {"queue_len": qlen, "deadline_slack": 0, "pred_temp": round(float(temp[chef]), 1), "cost": 0, "hint_min": round(float(est[j]) / 60.0, 1)},
                            "mask_summary": {"valid": inf.get("valid", 0), "total": inf.get("total", 0)}})
                svc = float(S.remaining[j]) if False else float(w.dur[j])
                out.append({"t": tk, "type": "JOB_STARTED", "job_id": str(w.job_id[j]), "gpu_ids": [CHEFS[chef][0]], "eta_t": tk + max(1, math.ceil(svc / TICK_S))})
            elif typ == EV_FINISH:
                chef = running.pop(j, None)
                if chef is not None: busy[chef] -= w.req[j] / UNIT
                done_n += 1; wt = float(S.start_first[j] - w.submit[j]) / 60.0; waits.append(wt)
                out.append({"t": tk, "type": "JOB_COMPLETED", "job_id": str(w.job_id[j]), "on_time": True, "wait_s": round(wt, 1), "cost": 0})
            elif typ in (EV_PREEMPT, EV_NODEEVICT):
                chef = running.pop(j, None)
                if chef is not None: busy[chef] -= w.req[j] / UNIT
                queued.add(j)
                out.append({"t": tk, "type": "JOB_FAILED", "job_id": str(w.job_id[j]), "reason": "asked to leave for a higher-priority party", "requeued": True})
        for c in range(n_chefs):
            util = 100.0 * busy[c] / max(float(k.cluster.node_ngpu[c]), 1.0)
            temp[c] = thermal.step(temp[c], util, TICK_S)
            out.append({"t": tk, "type": "GPU_TELEMETRY", "gpu_id": CHEFS[c][0], "temp": round(float(temp[c]), 1), "util": round(util, 1), "vram_used_gb": float(busy[c]), "health": "normal"})
        wv = np.array(waits) if waits else np.zeros(1)
        out.append({"t": tk, "type": "METRICS", "completed": done_n, "waiting": len(queued), "received": recv, "avg_wait_s": round(float(wv.mean()), 1),
                    "p95_wait_s": round(float(np.quantile(wv, .95)), 1), "slo_rate": 1, "avg_util": round(float(busy.sum() / k.cluster.node_ngpu.sum() * 100), 1),
                    "cost": 0, "thermal_incidents": 0, "starved": 0})
    for n, e in enumerate(out, 1):
        e["seq"] = n
    return {"run_id": f"trace-{policy}", "note": f"REAL Alibaba trace jobs, small demo kitchen. Scheduler: {policy}. {scheduler_note}", "config": cfg,
            "trace_meta": {**k.meta, "scheduler": policy, "scheduler_label": SCHED_LABEL[policy],
                           "thermal": "proxy (measured H100 profile), not measured on these GPUs", "hint": "runtime hint model v2 (job-history features)"}, "events": out}


def make_recordings(jobs: pd.DataFrame, pools: list[dict], hint: DurationHint, rl_model=None, rl_K: int = 16, start_day: float = 130.0,
                    minutes: float = 120.0, extra_minutes: float = 60.0, nodes: int = 5) -> dict[str, dict]:
    k = build_kitchen(jobs, pools, start_day, minutes, nodes=nodes)
    max_ticks = int((minutes + extra_minutes))
    recs = {}
    for pol in ("fifo", "priority_fifo", "sjf_hint"):
        S, info = _run_sim(k, pol, hint)
        recs[pol] = to_recording(k, S, pol, hint, info, max_ticks)
    if rl_model is not None:
        S, info = _run_rl(k, jobs, hint, rl_model, rl_K)
        recs["rl_ppo"] = to_recording(k, S, "rl_ppo", hint, info, max_ticks, scheduler_note="Decisions by the trained MaskablePPO policy.")
    return recs
