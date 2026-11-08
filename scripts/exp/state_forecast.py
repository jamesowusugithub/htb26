"""Utilisation + queue-length forecast vs persistence. Train windows end before day 100 (priority_fifo + sjf_hint runs), test = windows starting >= day 130."""
import sys, json; from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler.metrics import timeline
from scheduler.demand_forecast import arrival_bins, BIN_S
from scheduler.state_forecast import build_rows, StateForecaster
pools, jobs, base, cl = setup(0.85); h = load_or_fit(jobs, 40); ids = [p["id"] for p in pools]; P = len(ids)
g, _, _ = arrival_bins(jobs, P); H, DT = (float(sys.argv[1]) if len(sys.argv) > 1 else 1800.0), 600.0
def rows_for(day, pol):
    sc = Scenario(start_day=float(day), days=3.0, seed=0); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
    est = None
    if pol == "sjf_hint":
        est = h.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est))
    S = run_policy(c, w, POLICIES[pol], est=est, snapshot_dt=DT, early_stop=False)
    tl = timeline(S, c); tl = tl[(tl.t <= 3 * 86400) & (tl.t >= 3 * 3600)]          # skip the warm-start hours
    r = build_rows(tl, g, day * 86400.0, ids, DT, H); r["policy"] = pol; r["day"] = day; return r
def gather(days, pols):
    out = []
    for d in days:
        for pol in pols: out.append(rows_for(d, pol))
    return pd.concat(out, ignore_index=True)
tr = gather(range(5, 98, 3), ["priority_fifo", "sjf_hint"]); print("train rows", len(tr), flush=True)
te = gather(range(130, 181, 3), ["priority_fifo", "sjf_hint"]).dropna(subset=["y_busy"]); print("test rows", len(te), flush=True)
f = StateForecaster(H).fit(tr)
pb, pq = f.predict(te)
res = {}
for label, m in [("ALL policies", np.ones(len(te), bool))] + [(p, (te.policy == p).to_numpy()) for p in ("priority_fifo", "sjf_hint")]:
    d = te[m]; r = {}
    for scope, mm in [("ALL pools", np.ones(m.sum(), bool))] + [(ids[p], (d.pool == p).to_numpy()) for p in range(P)]:
        dd = d[mm]; b = pb[m][mm]; q = pq[m][mm]; yq = np.expm1(dd.y_logq.to_numpy())
        r[scope] = {"util_MAE_pp_model": 100 * float(np.abs(b - dd.y_busy).mean()), "util_MAE_pp_persistence": 100 * float(np.abs(dd.busy - dd.y_busy).mean()),
                    "queue_MAE_model": float(np.abs(q - yq).mean()), "queue_MAE_persistence": float(np.abs(dd.q - yq).mean()), "mean_queue": float(yq.mean()), "n": int(mm.sum())}
        sk = lambda a, b: (1 - a / b) if b > 1e-9 else float("nan"); r[scope]["util_skill"] = sk(r[scope]["util_MAE_pp_model"], r[scope]["util_MAE_pp_persistence"]); r[scope]["queue_skill"] = sk(r[scope]["queue_MAE_model"], r[scope]["queue_MAE_persistence"])
    res[label] = r
    print(f"\n== {label} (horizon {H/3600:g} h)")
    for k, v in (r.items() if label == "ALL policies" else []): print(f"  {k:9s} util MAE {v['util_MAE_pp_model']:5.2f} pp vs persist {v['util_MAE_pp_persistence']:5.2f} (skill {v['util_skill']:+.2f}) | queue MAE {v['queue_MAE_model']:8.1f} vs {v['queue_MAE_persistence']:8.1f} (skill {v['queue_skill']:+.2f}) mean q {v['mean_queue']:.0f}")
Path(f"analysis/rl/state_forecast_{int(H/60)}min.json").write_text(json.dumps(res, indent=1))
