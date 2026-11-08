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
from .data import UNIT, Cluster, Workload, add_cloud
from .cloud import pool_prices, tier_prices, POOL_TIER, provenance
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
    sim_kw: dict | None = None
    cloud: dict | None = None
    n_owned: int = 5
    pool: str = "a100"


def add_orders(w: Workload, orders: list[dict], pidx: int, node_gpus: int = 8) -> Workload:
    """New orders: jobs that are NOT in the Alibaba trace, submitted live. Validated, then merged into the workload in time order."""
    if len(orders) > 500:
        raise ValueError("too many orders (max 500)")
    rows = []
    for i, o in enumerate(orders):
        g, d, at = float(o.get("gpus", 1)), float(o.get("duration_min", 15)), float(o.get("at_min", 0))
        ng = int(o.get("max_gpus", node_gpus))
        if not (0 < g <= ng) or not (1 <= d <= 720) or at < 0:
            raise ValueError(f"order {i + 1}: gpus must be in (0,{ng}], duration 1-720 min, at_min >= 0")
        if o.get("priority", "high") not in ("high", "spot"):
            raise ValueError(f"order {i + 1}: priority must be high or spot")
        rows.append((f"ORDER-{i + 1:03d}", at * 60.0, d * 60.0, int(round(g * UNIT)), 0 if o.get("priority", "high") == "high" else 1, int(o.get("pool_idx", pidx))))
    if not rows:
        return w
    sub = np.concatenate([w.submit, [r[1] for r in rows]]); order = np.argsort(sub, kind="stable")
    cat = lambda a, b, dt: np.concatenate([a, np.array(b, dtype=dt)])[order]
    return Workload(job_id=np.concatenate([w.job_id.astype(object), np.array([r[0] for r in rows], dtype=object)])[order], submit=sub[order],
                    dur=cat(w.dur, [r[2] for r in rows], float), pool=cat(w.pool, [r[5] for r in rows], np.int64), req=cat(w.req, [r[3] for r in rows], np.int64),
                    prio=cat(w.prio, [r[4] for r in rows], np.int64), org=cat(w.org.astype(object), ["order"] * len(rows), object),
                    eval_mask=cat(w.eval_mask, [True] * len(rows), bool), t0=w.t0, elapsed0=cat(w.elapsed0 if w.elapsed0 is not None else np.zeros(len(w)), [0.0] * len(rows), float))


def build_kitchen(jobs: pd.DataFrame, pools: list[dict], start_day: float, minutes: float, pool_id: str = "a100",
                  nodes: int = 5, gpus_per_node: int = 8, orders: list | None = None, cloud: dict | None = None, kitchen: list | None = None) -> Kitchen:
    ids = [p["id"] for p in pools]
    s, e = start_day * 86400, start_day * 86400 + minutes * 60
    if kitchen:                                                # custom kitchen: one entry per chef = {pool: GPU type id, gpus: GPUs on that node}
        if not 2 <= len(kitchen) <= 5:
            raise ValueError("a kitchen has 2-5 chefs (nodes)")
        ent = []
        for c in kitchen:
            if c["pool"] not in ids or not 1 <= int(c["gpus"]) <= 8:
                raise ValueError(f"bad kitchen entry {c}: pool must be one of {ids}, gpus 1-8")
            ent.append((ids.index(c["pool"]), int(c["gpus"])))
        ent.sort(key=lambda x: x[0])                           # nodes must be grouped by pool
        pidxs = sorted({p for p, _ in ent}); maxg = {p: max(g for q, g in ent if q == p) for p in pidxs}
        pool_id = ids[ent[0][0]]; pidx = ent[0][0]
        sub = jobs[jobs.pool.isin(pidxs)]
        sub = sub[sub.req.to_numpy() <= sub.pool.map(maxg).to_numpy() * UNIT]     # a job larger than any node of its type could never start: leave it out
        w = data.make_workload(sub, s, e, carryover=False)
        if orders:
            orders = [{**o, "pool_idx": ids.index(o["pool"]) if o.get("pool") in ids and ids.index(o["pool"]) in pidxs else pidx,
                       "max_gpus": maxg[ids.index(o["pool"]) if o.get("pool") in ids and ids.index(o["pool"]) in pidxs else pidx]} for o in orders]
            w = add_orders(w, orders, pidx, 8)
        node_pool = np.array([p for p, _ in ent], dtype=np.int64); node_g = np.array([g for _, g in ent], dtype=np.int64)
        nodes, gpus_per_node = len(ent), int(node_g.max())
        cl = Cluster(pools, node_pool, node_g, np.ones(len(pools))); owned_g = node_g
    else:
        pidx = ids.index(pool_id); pidxs = [pidx]
        sub = jobs[(jobs.pool == pidx)]
        w = data.make_workload(sub, s, e, carryover=False)
        if orders:
            w = add_orders(w, orders, pidx, gpus_per_node)
        node_pool = np.full(nodes, pidx, dtype=np.int64)
        cl = Cluster(pools, node_pool, np.full(nodes, gpus_per_node, dtype=np.int64), np.ones(len(pools))); owned_g = np.full(nodes, gpus_per_node)
    sim_kw, cloud_meta = {}, None
    if cloud and int(cloud.get("nodes", 0)) > 0:
        cn, cg = int(cloud["nodes"]), int(cloud.get("gpus_per_node", 8))
        wait_min, mult = float(cloud.get("overflow_wait_min", 30.0)), float(cloud.get("price_multiplier", 1.0))
        cl = add_cloud(cl, {ids[p]: cn for p in pidxs}, cg)
        from .cloud import DEFAULT_MAX_JOB_COST_USD
        budget = float(cloud.get("max_job_cost_usd", DEFAULT_MAX_JOB_COST_USD))
        sim_kw = {"cloud_price": pool_prices([p["id"] for p in pools], mult), "overflow_wait_s": wait_min * 60.0, "max_job_cost_usd": budget}
        price = float(sim_kw["cloud_price"][pidx])
        cloud_meta = {"enabled": True, "nodes": cn * len(pidxs), "gpus_per_node": cg, "gpus": cn * cg * len(pidxs), "overflow_wait_min": wait_min, "price_usd_per_gpu_hour": round(price, 2),
                      "price_multiplier": mult, "max_job_cost_usd": budget, "evidence": "SIMULATED fallback, not Alibaba data", "price_basis": provenance()["note"]}
    meta = {"source": "Alibaba GPU trace (harmonised jobs.parquet)", "pool": pool_id, "window_start_day": start_day, "window_minutes": minutes,
            "jobs": int(len(w)), "kitchen_nodes": nodes, "gpus_per_node": gpus_per_node,
            "real_pool_nodes_in_simulation": "about 290 A100 nodes", "time_unit": "min", "tick_s": TICK_S,
            "scale_note": f"Real jobs, small demo kitchen ({nodes} nodes: " + ", ".join(f"{pools[p]['label']} x{g}" for p, g in zip(node_pool.tolist(), owned_g.tolist())) + ") instead of thousands, so queues are visible. Scale is illustrative; the full-scale numbers are in the scoreboard."}
    meta["orders"] = len(orders or [])
    if cloud_meta:
        meta["cloud"] = cloud_meta
        meta["scale_note"] += f" Takeaway = SIMULATED cloud fallback ({cloud_meta['gpus']} GPUs, jobs waiting over {wait_min:g} min are sent there at an assumed ${cloud_meta['price_usd_per_gpu_hour']}/GPU-hour, only if the predicted rental cost is under ${budget:g}); it is not observed in the Alibaba trace."
    return Kitchen(w, cl, meta, sim_kw, cloud_meta, nodes, pool_id)


def _run_sim(k: Kitchen, policy: str, hint: DurationHint):
    spec = POLICIES[policy]
    est = None
    if spec.est_mode == "hint":
        est = hint.predict_seconds(k.workload.job_id)
        est = np.where(np.isfinite(est), est, np.nanmedian(est))
    kw = dict(k.sim_kw or {})
    if kw:                                                    # the cloud rule prices jobs with the hint, never the true duration
        oe = hint.predict_seconds(k.workload.job_id); kw["overflow_est"] = np.where(np.isfinite(oe), oe, np.nanmedian(oe))
    S = run_policy(k.cluster, k.workload, spec, est=est, log_events=True, snapshot_dt=None, early_stop=False, **kw)
    return S, {}


def _run_rl(k: Kitchen, jobs: pd.DataFrame, hint: DurationHint, model, K: int, shuffle: bool = False):
    from .env import SchedulingEnv
    env = SchedulingEnv(jobs, k.cluster, hint, K=K, log_events=True, snapshot_dt=None, shuffle_slots=shuffle)
    obs, _ = env.reset(options={"workload": k.workload, "cluster": k.cluster, "days": 1.0, "sim_kw": k.sim_kw or {}})
    info_by_job, done = {}, False
    while not done:
        mask = env.action_masks()
        a = int(model.predict(obs, action_masks=mask, deterministic=True)[0])
        real = int(env._perm[a]) if (shuffle and a < K) else a          # shuffled slot -> real candidate slot
        if a < K and env.S.cand_job[real] >= 0:
            j = int(env.S.cand_job[real]); p = int(env.S.pool[j])
            info_by_job.setdefault(j, []).append({"valid": int(mask[:K].sum()), "total": K, "queue_len": int(env.S.qc[p])})
        obs, r, te, tr, _ = env.step(a)
        done = te or tr
    return env.S, info_by_job


def to_recording(k: Kitchen, S, policy: str, hint: DurationHint, info_by_job: dict, max_ticks: int, thermal: ThermalProxy | None = None,
                 scheduler_note: str = "") -> dict:
    thermal = thermal or ThermalProxy.load()
    w = k.workload
    owned = np.flatnonzero(~np.asarray(k.cluster.cloud_mask()))          # the kitchen's own nodes (chefs); cloud nodes are the takeaway
    n_chefs = min(len(owned), len(CHEFS))
    owned = owned[:n_chefs]; chef_of = np.full(len(k.cluster.node_ngpu), -1, dtype=np.int64); chef_of[owned] = np.arange(n_chefs)
    owned_ngpu = np.asarray(k.cluster.node_ngpu)[owned].astype(float)
    chef_pool = np.asarray(k.cluster.node_pool)[owned]
    chef_ids = [f"{k.cluster.pools[int(p)]['id']}-{c + 1}" for c, p in enumerate(chef_pool)]          # the scene labels each chef with its GPU type
    chef_label = [f"{k.cluster.pools[int(p)]['label']} x{int(g)}" for p, g in zip(chef_pool, owned_ngpu)]
    cloud_gpus = float(k.cloud["gpus"]) if k.cloud else 0.0
    price = float(k.cloud["price_usd_per_gpu_hour"]) if k.cloud else 0.0
    tick = lambda t: int(t // TICK_S)
    est = hint.predict_seconds(w.job_id)
    est = np.where(np.isfinite(est), est, np.nanmedian(est))
    chefs = [{"id": chef_ids[c], "tier": CHEFS[c][2], "vram_gb": int(owned_ngpu[c]), "compute": 1, "name": f"{chef_label[c]} (node {c + 1})"} for c in range(n_chefs)]
    cfg = {"nodes": [{"id": "node-0", "gpus": chefs[:2]}] + ([{"id": "node-1", "gpus": chefs[2:]}] if len(chefs) > 2 else []),
           "thresholds": {"warning": 75, "critical": 85}, "overflow_threshold": 10, "scheduler": SCHED_LABEL[policy], "trace": True}
    if k.cloud:
        cfg["nodes"].append({"id": "node-cloud", "gpus": [{"id": "cloud-0", "tier": "cloud", "vram_gb": int(cloud_gpus), "compute": 1, "name": "Cloud takeaway (SIMULATED)"}]})
    start_of = {}
    raw = []                                                  # (tick, order, event-dict-without-seq)
    order = 0
    busy = np.zeros(n_chefs); queued = set(); running = {}
    busy_cloud = 0.0; cloud_cost = 0.0; job_cost = {}
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
                chef = int(chef_of[int(ev_node[i])])
                if chef < 0:                                          # a SIMULATED cloud node: the takeaway counter
                    queued.discard(j); running[j] = -1; busy_cloud += w.req[j] / UNIT
                    jc = float(w.dur[j]) / 3600.0 * float(w.req[j] / UNIT) * float(k.sim_kw["cloud_price"][int(w.pool[j])]); job_cost[j] = jc; cloud_cost += jc
                    qlen = len(queued)
                    out.append({"t": tk, "type": "DECISION", "job_id": str(w.job_id[j]), "action": "cloud", "target_gpu_ids": ["cloud-0"], "scheduler": SCHED_LABEL[policy],
                                "factors": {"queue_len": qlen, "deadline_slack": 0, "pred_temp": 0, "cost": round(jc, 2), "hint_min": round(float(est[j]) / 60.0, 1), "waited_min": round((float(ev_t[i]) - float(w.submit[j])) / 60.0, 1)},
                                "mask_summary": {"valid": 0, "total": 0}})
                    out.append({"t": tk, "type": "JOB_STARTED", "job_id": str(w.job_id[j]), "gpu_ids": ["cloud-0"], "eta_t": tk + max(1, math.ceil(float(w.dur[j]) / TICK_S))})
                    continue
                queued.discard(j); running[j] = chef; busy[chef] += w.req[j] / UNIT
                inf = (info_by_job.get(j) or [{}])[-1] if info_by_job else {}
                qlen = inf.get("queue_len", len(queued))
                out.append({"t": tk, "type": "DECISION", "job_id": str(w.job_id[j]), "action": "assign", "target_gpu_ids": [chef_ids[chef]], "scheduler": SCHED_LABEL[policy],
                            "factors": {"queue_len": qlen, "deadline_slack": 0, "pred_temp": round(float(temp[chef]), 1), "cost": 0, "hint_min": round(float(est[j]) / 60.0, 1)},
                            "mask_summary": {"valid": inf.get("valid", 0), "total": inf.get("total", 0)}})
                svc = float(S.remaining[j]) if False else float(w.dur[j])
                out.append({"t": tk, "type": "JOB_STARTED", "job_id": str(w.job_id[j]), "gpu_ids": [chef_ids[chef]], "eta_t": tk + max(1, math.ceil(svc / TICK_S))})
            elif typ == EV_FINISH:
                chef = running.pop(j, None)
                if chef == -1: busy_cloud -= w.req[j] / UNIT
                elif chef is not None: busy[chef] -= w.req[j] / UNIT
                done_n += 1; wt = float(S.start_first[j] - w.submit[j]) / 60.0; waits.append(wt)
                out.append({"t": tk, "type": "JOB_COMPLETED", "job_id": str(w.job_id[j]), "on_time": True, "wait_s": round(wt, 1), "cost": round(job_cost.get(j, 0.0), 2)})
            elif typ in (EV_PREEMPT, EV_NODEEVICT):
                chef = running.pop(j, None)
                if chef is not None: busy[chef] -= w.req[j] / UNIT
                queued.add(j)
                out.append({"t": tk, "type": "JOB_FAILED", "job_id": str(w.job_id[j]), "reason": "asked to leave for a higher-priority party", "requeued": True})
        for c in range(n_chefs):
            util = 100.0 * busy[c] / max(float(owned_ngpu[c]), 1.0)
            temp[c] = thermal.step(temp[c], util, TICK_S)
            out.append({"t": tk, "type": "GPU_TELEMETRY", "gpu_id": chef_ids[c], "temp": round(float(temp[c]), 1), "util": round(util, 1), "vram_used_gb": float(busy[c]), "health": "normal"})
        if k.cloud:
            out.append({"t": tk, "type": "GPU_TELEMETRY", "gpu_id": "cloud-0", "temp": 0, "util": round(100.0 * busy_cloud / max(cloud_gpus, 1.0), 1), "vram_used_gb": float(busy_cloud), "health": "normal"})
        wv = np.array(waits) if waits else np.zeros(1)
        out.append({"t": tk, "type": "METRICS", "completed": done_n, "waiting": len(queued), "received": recv, "avg_wait_s": round(float(wv.mean()), 1),
                    "p95_wait_s": round(float(np.quantile(wv, .95)), 1), "slo_rate": 1, "avg_util": round(float(busy.sum() / owned_ngpu.sum() * 100), 1),
                    "cost": round(cloud_cost, 2), "thermal_incidents": 0, "starved": 0})
    for n, e in enumerate(out, 1):
        e["seq"] = n
    return {"run_id": f"trace-{policy}", "note": f"REAL Alibaba trace jobs, small demo kitchen. Scheduler: {policy}. {scheduler_note}", "config": cfg,
            "trace_meta": {**k.meta, "scheduler": policy, "scheduler_label": SCHED_LABEL[policy],
                           "thermal": "proxy (measured H100 profile), not measured on these GPUs", "hint": "runtime hint model v3 (job-history + submit-burst features; new orders have no history, so the pool median is used)"}, "events": out}


def make_recordings(jobs: pd.DataFrame, pools: list[dict], hint: DurationHint, rl_model=None, rl_K: int = 16, start_day: float = 130.0,
                    minutes: float = 120.0, extra_minutes: float = 60.0, nodes: int = 5, rl_shuffle: bool = False) -> dict[str, dict]:
    k = build_kitchen(jobs, pools, start_day, minutes, nodes=nodes)
    max_ticks = int((minutes + extra_minutes))
    recs = {}
    for pol in ("fifo", "priority_fifo", "sjf_hint"):
        S, info = _run_sim(k, pol, hint)
        recs[pol] = to_recording(k, S, pol, hint, info, max_ticks)
    if rl_model is not None:
        S, info = _run_rl(k, jobs, hint, rl_model, rl_K, rl_shuffle)
        recs["rl_ppo"] = to_recording(k, S, "rl_ppo", hint, info, max_ticks, scheduler_note="Decisions by the trained MaskablePPO policy.")
    return recs


def make_recording(jobs: pd.DataFrame, pools: list[dict], hint: DurationHint, policy: str, rl_model=None, rl_K: int = 16, start_day: float = 145.0,
                   minutes: float = 150.0, extra_minutes: float = 60.0, nodes: int = 5, orders: list | None = None, cloud: dict | None = None, rl_shuffle: bool = False, kitchen: list | None = None) -> dict:
    """One recording for one scheduler, optionally with NEW ORDERS (jobs not in the trace) and the SIMULATED takeaway fallback."""
    if policy not in SCHED_LABEL:
        raise ValueError(f"unknown policy {policy!r}")
    k = build_kitchen(jobs, pools, start_day, minutes, nodes=nodes, orders=orders, cloud=cloud, kitchen=kitchen)
    max_ticks = int(minutes + extra_minutes)
    if policy == "rl_ppo":
        if rl_model is None:
            raise ValueError("rl_ppo requested but no trained model is loaded")
        S, info = _run_rl(k, jobs, hint, rl_model, rl_K, rl_shuffle)
        note = "Decisions by the trained MaskablePPO policy."
    else:
        S, info = _run_sim(k, policy, hint)
        note = ""
    return to_recording(k, S, policy, hint, info, max_ticks, scheduler_note=note)
