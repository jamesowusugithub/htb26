"""Do the policy rankings survive changes to our modelling assumptions? And how much capacity does a better scheduler save?"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler import data
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler.metrics import summarize
from scheduler.sim import FC_QINT
DAYS = [130., 133., 145., 151., 157., 169.]
def run(cl, jobs, hint, pol, resume=False, cap=1.0):
    qs, hp, p95 = [], [], []
    for d in DAYS:
        sc = Scenario(start_day=d, days=3.0, capacity=cap, seed=0); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
        est = None
        if POLICIES[pol].est_mode == "hint":
            est = hint.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est))
        S = run_policy(c, w, POLICIES[pol], resume=resume, est=est, snapshot_dt=None)
        m = summarize(S, w, c, util_hi=3 * 86400); qs.append(float(S.fc[FC_QINT])); hp.append(m["hp"]["wait_mean_s"] / 3600); p95.append(m["hp"]["wait_p95_s"] / 3600)
    return np.array(qs), np.array(hp), np.array(p95)
res = {"settings": [], "capacity_equivalence": {}}
pools, jobs, base, cl85 = setup(0.85); hint = load_or_fit(jobs, 40)
print(f"{'offered load':>12} {'evicted work':>12} | {'priority_fifo':>13} {'backfill':>9} {'sjf_hint v2':>11} {'oracle':>7}   (HP mean wait h; ratio of queue-time vs priority_fifo in brackets)")
for load in (0.70, 0.85, 1.00):
    _, _, _, cl = setup(load)
    for resume in (False, True):
        row = {"load": load, "resume": resume}; qb = None
        for pol in ("priority_fifo", "backfill_median", "sjf_hint", "sjf_oracle"):
            q, hp, p95 = run(cl, jobs, hint, pol, resume)
            if pol == "priority_fifo": qb = q
            row[pol] = {"hp_wait_h": round(float(hp.mean()), 2), "hp_p95_h": round(float(p95.mean()), 1), "q_ratio": round(float(np.mean(q / np.maximum(qb, 1e-9))), 3)}
        res["settings"].append(row)
        f = lambda k: f"{row[k]['hp_wait_h']:5.2f} ({row[k]['q_ratio']:.2f})"
        print(f"{load:>12} {'resume' if resume else 'restart':>12} | {f('priority_fifo'):>13} {f('backfill_median'):>9} {f('sjf_hint'):>11} {f('sjf_oracle'):>7}")
# capacity equivalence at 0.85 load: how many MORE GPUs does priority-FIFO need to match the hint-based scheduler at today's capacity?
_, hp_hint, p95_hint = run(cl85, jobs, hint, "sjf_hint")
target = float(hp_hint.mean()); curve = []
for cap in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 2.0):
    _, hp, p95 = run(cl85, jobs, hint, "priority_fifo", cap=cap); curve.append((cap, round(float(hp.mean()), 2), round(float(p95.mean()), 1)))
print("\npriority-FIFO HP wait vs extra capacity (target = hint scheduler at 1.0x: %.2f h):" % target); [print(f"  capacity x{c:<4} HP wait {w:6.2f} h   p95 {p:5.1f} h") for c, w, p in curve]
eq = next((c for c, w, _ in curve if w <= target), None)
res["capacity_equivalence"] = {"hint_scheduler_hp_wait_h": round(target, 2), "fifo_curve": curve, "fifo_capacity_needed_to_match": eq,
                               "total_gpus_at_1x": float(cl85.capacity_gpus().sum())}
print("FIFO needs capacity x%s to match the hint scheduler at x1.0" % eq, "=> about", None if eq is None else round((eq - 1) * float(cl85.capacity_gpus().sum())), "extra GPUs of", round(float(cl85.capacity_gpus().sum())))
Path("analysis/proof/sensitivity.json").write_text(json.dumps(res, indent=1))
