"""Operating outcomes beyond queue time: cost and thermal exposure, computed from a finished run's own event log.

COST   = cloud rental (simulated fallback, priced from tier assumptions) + the cost of compute WASTED by evictions (priced at the pool's tier price).
THERMAL = per-node temperature from the thermal PROXY (measured H100 profile + first-order lag; see thermal.py) driven by each node's utilisation;
          'violation' = node-hours at or above the ASSUMED alert threshold (80 C; no measured reading reaches it). Under normal ambient the proxy peaks near 50 C,
          so violations only appear under a cooling-fault scenario, which is why both cases are reported.
Neither the scheduler nor the reward sees temperature or price in the base policies; these numbers show what their decisions cost.
"""
from __future__ import annotations
import numpy as np
from .data import UNIT
from .cloud import pool_prices
from .sim import (SC_NEV, EV_START, EV_FINISH, EV_PREEMPT, EV_NODEEVICT, FC_CLOUDCOST, FC_CLOUDGPUH)
from .thermal import ThermalProxy


def node_busy_gpus(S, n_nodes: int, horizon_s: float, step_s: float = 60.0) -> np.ndarray:
    """Busy GPUs per owned node at the start of each step: array [steps, nodes]. Cloud nodes are excluded (no thermal model for them)."""
    T = int(np.ceil(horizon_s / step_s)) + 1
    delta = np.zeros((T + 1, n_nodes), dtype=np.float32)
    n = int(S.sc[SC_NEV])
    typ, t, j, node = S.ev_type[:n], S.ev_t[:n], S.ev_job[:n], S.ev_node[:n]
    sel = ((typ == EV_START) | (typ == EV_FINISH) | (typ == EV_PREEMPT) | (typ == EV_NODEEVICT)) & (j >= 0) & (node >= 0)
    sel &= S.node_cloud[np.clip(node, 0, None)] == 0
    sign = np.where(typ[sel] == EV_START, 1.0, -1.0).astype(np.float32)
    g = (S.req[j[sel]] / UNIT).astype(np.float32)
    k = np.clip(np.floor(np.maximum(t[sel], 0.0) / step_s).astype(int), 0, T)
    np.add.at(delta, (k, node[sel]), sign * g)
    return np.cumsum(delta, axis=0)[:T]


def thermal_outcomes(S, cluster, thermal: ThermalProxy, horizon_s: float, cooling_fault: dict | None = None, step_s: float = 60.0) -> dict:
    own = ~cluster.cloud_mask()
    ngpu = cluster.node_ngpu[own].astype(np.float32)
    busy = node_busy_gpus(S, len(cluster.node_ngpu), horizon_s, step_s)[:, own]
    util = 100.0 * busy / np.maximum(ngpu, 1.0)
    steps = util.shape[0]
    times = np.arange(steps) * step_s

    def delta_at(t):
        if not cooling_fault:
            return 0.0
        a = float(cooling_fault["at_h"]) * 3600.0
        b = a + float(cooling_fault["duration_h"]) * 3600.0 if cooling_fault.get("duration_h") is not None else np.inf
        return float(cooling_fault.get("delta_c", 35.0)) if a <= t < b else 0.0

    a = 1.0 - np.exp(-step_s / thermal.tau_s)
    tgt = np.interp(util, [0, 10, 30, 50, 70, 90, 100], np.concatenate([[thermal.t50[0]], thermal.t50, [thermal.t50[-1]]])).astype(np.float32)
    T = np.empty_like(tgt)
    T[0] = tgt[0] + delta_at(0.0)
    for k in range(1, steps):
        T[k] = T[k - 1] + (tgt[k - 1] + delta_at(times[k]) - T[k - 1]) * a
    hot = T >= thermal.threshold_c
    return {"violation_node_hours": float(hot.sum() * step_s / 3600.0), "nodes_ever_hot": int(hot.any(axis=0).sum()), "peak_c": float(T.max()),
            "mean_c": float(T.mean()), "threshold_c": thermal.threshold_c, "nodes": int(own.sum()),
            "evidence": "proxy (measured H100 profile); threshold is an assumption"}


def cost_outcomes(S, w, pool_ids: list[str], price_multiplier: float = 1.0) -> dict:
    price = pool_prices(pool_ids, price_multiplier)
    wasted_gpu_h = S.wasted / 3600.0
    waste_usd = float((wasted_gpu_h * price[w.pool]).sum())
    return {"wasted_gpu_hours": float(wasted_gpu_h.sum()), "wasted_compute_usd": waste_usd, "cloud_jobs": int(S.job_cloud.sum()), "cloud_gpu_hours": float(S.fc[FC_CLOUDGPUH]),
            "cloud_usd": float(S.fc[FC_CLOUDCOST]), "total_extra_usd": waste_usd + float(S.fc[FC_CLOUDCOST]),
            "evidence": "prices are tier assumptions anchored to the pricing data; no Alibaba GPU has an exact price match (scheduler/cloud.py)"}
