"""Run all baseline policies on a window of the trace and print a comparison table.

    python -m scheduler.run_baselines --start-day 60 --days 7 --load 0.85
"""
from __future__ import annotations
import argparse, time, json
import numpy as np
import pandas as pd
from . import data
from .policies import POLICIES
from .sim import simulate, estimate_array
from .metrics import summarize


def setup(target_load: float = 0.85, min_nodes: int = 8):
    pools = data.load_pool_config()
    jobs = data.load_jobs(pools)
    nodes = data.load_nodes(pools)
    base = data.observed_cluster(nodes, pools)
    cluster = data.calibrate_cluster(base, jobs, target_load, min_nodes)
    return pools, jobs, base, cluster


def run_policy(cluster, w, spec, resume=False, est_sigma=1.0, **kw):
    est = kw.pop("est", None)
    if est is None and spec.est_mode in ("oracle", "noisy", "median"):
        est = estimate_array(w, spec.est_mode, sigma=est_sigma)
    kw.setdefault("early_stop", True)
    return simulate(cluster, w, spec.policy, preempt=spec.preempt, resume=resume, est=est, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-day", type=float, default=60)
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--load", type=float, default=0.85)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--policies", default=",".join(POLICIES))
    a = ap.parse_args()

    pools, jobs, base, cluster = setup(a.load)
    print("pool            observed_nodes  sim_nodes  observed_gpus  sim_gpus  offered_load(observed)")
    rho = data.offered_load(base, jobs)
    for i, p in enumerate(pools):
        print(f"{p['id']:<14}{base.node_counts()[i]:>12}{cluster.node_counts()[i]:>11}{base.capacity_gpus()[i]:>14.0f}"
              f"{cluster.capacity_gpus()[i]:>10.0f}{rho[i]:>16.2f}")
    s, e = a.start_day * 86400, (a.start_day + a.days) * 86400
    w = data.make_workload(jobs, s, e)
    print(f"\nwindow: day {a.start_day}..{a.start_day + a.days}  jobs simulated {len(w)}  evaluated {int(w.eval_mask.sum())}")
    rows = []
    for name in a.policies.split(","):
        spec = POLICIES[name]
        t0 = time.time()
        S = run_policy(cluster, w, spec, resume=a.resume)
        m = summarize(S, w, cluster, util_hi=e - s)
        rows.append({"policy": name, "realistic": spec.realistic, "sec": round(time.time() - t0, 1),
                     "util": round(m["utilisation_overall"], 3),
                     "hp_wait_mean_h": m["hp"]["wait_mean_s"] / 3600, "hp_wait_p95_h": m["hp"]["wait_p95_s"] / 3600,
                     "spot_wait_mean_h": m["spot"]["wait_mean_s"] / 3600, "spot_wait_p95_h": m["spot"]["wait_p95_s"] / 3600,
                     "hp_bsld_mean": m["hp"]["bsld_mean"], "preempt": m["total_preemption_events"],
                     "wasted_gpu_h": m["overall"]["wasted_gpu_h"], "err": m["error_flags"]})
    pd.set_option("display.width", 220)
    print(pd.DataFrame(rows).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
