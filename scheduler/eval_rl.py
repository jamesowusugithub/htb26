"""Evaluate a trained policy against the baselines on identical windows/scenarios."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .env import SchedulingEnv
from .policies import POLICIES
from .run_baselines import run_policy
from .whatif import Scenario, build_workload, build_cluster, sim_kwargs
from .metrics import summarize

BASELINES = ["fifo", "priority_fifo", "backfill_median", "sjf_hint", "sjf_oracle"]


def _row(name, m, extra=None):
    r = {"policy": name, "hp_wait_mean_h": m["hp"]["wait_mean_s"] / 3600, "hp_wait_p95_h": m["hp"]["wait_p95_s"] / 3600,
         "spot_wait_mean_h": m["spot"]["wait_mean_s"] / 3600, "util": m["utilisation_overall"],
         "preemptions": m["total_preemption_events"], "wasted_gpu_h": m["overall"]["wasted_gpu_h"]}
    r.update(extra or {})
    return r


def run_agent(env: SchedulingEnv, predict, scenario: Scenario):
    """predict(obs, mask) -> action. Returns (metrics, qint_ratio, steps)."""
    obs, _ = env.reset(options={"scenario": scenario})
    done, n, info = False, 0, {}
    while not done:
        obs, r, term, trunc, info = env.step(int(predict(obs, env.action_masks())))
        done = term or trunc
        n += 1
    return info["metrics"], info["qint_ratio_vs_priority_fifo"], n


def evaluate(jobs, cluster, hint, scenarios: list[Scenario], agents: dict, baselines=BASELINES, K=8, shuffle=False) -> pd.DataFrame:
    """agents: {name: predict(obs, mask)}. One row per (scenario, policy)."""
    env = SchedulingEnv(jobs, cluster, hint, K=K, shuffle_slots=shuffle)
    rows = []
    for sc in scenarios:
        w = build_workload(jobs, sc)
        c = build_cluster(cluster, sc)
        est = hint.predict_seconds(w.job_id)
        est = np.where(np.isfinite(est), est, np.nanmedian(est))
        qb = None
        for b in sorted(baselines, key=lambda x: x != "priority_fifo"):   # priority_fifo first: it is the reference for q_ratio
            kw = sim_kwargs(sc, c)
            if sc.cloud:
                kw["overflow_est"] = est          # the cloud rule prices jobs with the HINT for every policy, never the true duration
            S = run_policy(c, w, POLICIES[b], est=est if b == "sjf_hint" else None, snapshot_dt=None, **kw)
            m = summarize(S, w, c, util_hi=sc.days * 86400)
            from .sim import FC_QINT
            q = float(S.fc[FC_QINT])
            if b == "priority_fifo":
                qb = max(q, 1e-9)
            rows.append(_row(b, m, {"scenario": sc.name, "start_day": sc.start_day, "q_ratio": q / qb}))
        for name, pred in agents.items():
            m, ratio, _ = run_agent(env, pred, sc)
            rows.append(_row(name, m, {"scenario": sc.name, "start_day": sc.start_day, "q_ratio": ratio}))
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, busy_min_q: float = 2000.0) -> pd.DataFrame:
    """Per policy: mean HP wait, mean ratio of weighted queue-time vs priority-FIFO, and win count vs backfill/sjf_hint."""
    base = df[df.policy == "priority_fifo"].set_index(["scenario", "start_day"])
    out = []
    for pol, g in df.groupby("policy", sort=False):
        out.append({"policy": pol, "windows": len(g), "hp_wait_mean_h": g.hp_wait_mean_h.mean(),
                    "hp_wait_p95_h": g.hp_wait_p95_h.mean(), "spot_wait_mean_h": g.spot_wait_mean_h.mean(),
                    "q_ratio_mean": g.q_ratio.mean(), "util": g.util.mean(), "preemptions": g.preemptions.mean()})
    return pd.DataFrame(out)
