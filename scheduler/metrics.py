"""Metrics reconstructed from a finished simulation (S) and its workload (w)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .data import UNIT, Cluster, Workload
from .sim import State, SC_ERR, SC_NPREEMPT, SC_NSNAP

TAU = 10.0  # bounded-slowdown floor (s)


def job_table(S: State, w: Workload, cluster: Cluster) -> pd.DataFrame:
    wait = S.start_first - S.submit
    run = S.dur
    bsld = np.maximum(1.0, (wait + run) / np.maximum(run, TAU))
    pool_ids = np.array([p["id"] for p in cluster.pools])
    return pd.DataFrame({
        "job_id": w.job_id, "pool": pool_ids[w.pool], "priority": np.where(w.prio == 0, "hp", "spot"),
        "gpus": w.req / UNIT, "submit_s": S.submit, "start_s": S.start_first, "finish_s": S.finish,
        "wait_s": wait, "duration_s": run, "bsld": bsld, "preemptions": S.npre,
        "wasted_gpu_s": S.wasted, "evaluated": w.eval_mask})


def _q(x, q):
    return float(np.quantile(x, q)) if len(x) else float("nan")


def summarize(S: State, w: Workload, cluster: Cluster, util_hi: float | None = None) -> dict:
    jt = job_table(S, w, cluster)
    ev = jt[jt.evaluated & (jt.start_s >= 0)]

    def block(d):
        return {"jobs": int(len(d)), "wait_mean_s": float(d.wait_s.mean()) if len(d) else float("nan"),
                "wait_p50_s": _q(d.wait_s, .5), "wait_p95_s": _q(d.wait_s, .95), "wait_p99_s": _q(d.wait_s, .99),
                "bsld_mean": float(d.bsld.mean()) if len(d) else float("nan"), "bsld_p95": _q(d.bsld, .95),
                "preemptions": int(d.preemptions.sum()), "wasted_gpu_h": float(d.wasted_gpu_s.sum() / 3600)}

    n = int(S.sc[SC_NSNAP])
    t = S.snap_t[:n]
    hi = util_hi if util_hi is not None else float(S.submit.max())
    sel = (t >= 0) & (t <= hi)
    util = {}
    for p, pd_ in enumerate(cluster.pools):
        cap = max(S.pool_cap[p], 1)
        util[pd_["id"]] = float((S.snap_busy[:n, p][sel] / cap).mean()) if sel.any() else float("nan")
    out = {"overall": block(ev), "hp": block(ev[ev.priority == "hp"]), "spot": block(ev[ev.priority == "spot"]),
           "pools": {pid: {"hp": block(ev[(ev.pool == pid) & (ev.priority == "hp")]),
                           "spot": block(ev[(ev.pool == pid) & (ev.priority == "spot")])}
                     for pid in util},
           "utilisation": util, "error_flags": int(S.sc[SC_ERR]), "total_preemption_events": int(S.sc[SC_NPREEMPT])}
    caps = S.pool_cap.astype(float)
    out["utilisation_overall"] = float(sum(util[k] * caps[i] for i, k in enumerate(util)) / caps.sum())
    return out


def timeline(S: State, cluster: Cluster) -> pd.DataFrame:
    """Per-pool snapshot series for plots/frontend."""
    n = int(S.sc[SC_NSNAP])
    rows = []
    for p, pd_ in enumerate(cluster.pools):
        cap = S.pool_cap[p] / UNIT
        rows.append(pd.DataFrame({
            "t": S.snap_t[:n], "pool": pd_["id"], "busy_gpus": S.snap_busy[:n, p] / UNIT, "capacity_gpus": cap,
            "queue_hp": S.snap_qhp[:n, p], "queue_spot": S.snap_qsp[:n, p], "running_jobs": S.snap_run[:n, p],
            "max_free_gpus_on_one_node": S.snap_maxfull[:n, p]}))
    return pd.concat(rows, ignore_index=True)
