"""Queue-time ratio vs cloud spend on HELD-OUT windows. Reference = priority FIFO WITHOUT cloud on the same workload (same metric as before).
A lower ratio bought with cloud capacity is reported together with its dollar cost, so it cannot hide a worse bill.
Cloud rule: jobs waiting >= 2 h are offloaded if their HINT-predicted rental cost <= $30 (never the true duration)."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster, sim_kwargs
from scheduler.env import SchedulingEnv
from scheduler.sim import FC_QINT
from scheduler.metrics import summarize
from scheduler.outcomes import cost_outcomes
model_path = sys.argv[1]; K = int(sys.argv[2]); out = sys.argv[3]
pools, jobs, base, cl = setup(0.85); hint = load_or_fit(jobs, 40); ids = [p["id"] for p in pools]
model = MaskablePPO.load(model_path, device="cpu"); env = SchedulingEnv(jobs, cl, hint, K=K)
DAYS = [130.0, 133.0, 145.0, 151.0, 157.0, 169.0]
rows = []
for d in DAYS:
    sc0 = Scenario(start_day=d, days=3.0, seed=0); w0 = build_workload(jobs, sc0); c0 = build_cluster(cl, sc0)
    est0 = hint.predict_seconds(w0.job_id); est0 = np.where(np.isfinite(est0), est0, np.nanmedian(est0))
    qref = float(run_policy(c0, w0, POLICIES["priority_fifo"], snapshot_dt=None).fc[FC_QINT])
    for nodes in (0, 5, 10, 20):
        sc = Scenario(start_day=d, days=3.0, seed=0, cloud=({"nodes_per_pool": nodes, "gpus_per_node": 8, "overflow_wait_s": 7200.0, "max_job_cost_usd": 30.0} if nodes else None))
        w = build_workload(jobs, sc); c = build_cluster(cl, sc); est = hint.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est))
        kw = sim_kwargs(sc, c)
        if nodes: kw["overflow_est"] = est
        for pol in ("priority_fifo", "backfill_median", "sjf_hint"):
            S = run_policy(c, w, POLICIES[pol], est=est if pol == "sjf_hint" else None, snapshot_dt=None, **kw)
            m = summarize(S, w, c, util_hi=3 * 86400); o = cost_outcomes(S, w, ids)
            rows.append(dict(day=d, cloud_nodes_per_pool=nodes, policy=pol, q_ratio=float(S.fc[FC_QINT]) / qref, hp_wait_h=m["hp"]["wait_mean_s"] / 3600, hp_p95_h=m["hp"]["wait_p95_s"] / 3600, **{k: o[k] for k in ("cloud_jobs", "cloud_usd", "wasted_compute_usd", "total_extra_usd")}))
        obs, _ = env.reset(options={"scenario": sc}); done = False
        while not done:
            a = int(model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0]); obs, r, te, tr, info = env.step(a); done = te or tr
        S = env.S; m = info["metrics"]; o = cost_outcomes(S, env.w, ids)
        rows.append(dict(day=d, cloud_nodes_per_pool=nodes, policy="rl_ppo", q_ratio=float(S.fc[FC_QINT]) / qref, hp_wait_h=m["hp"]["wait_mean_s"] / 3600, hp_p95_h=m["hp"]["wait_p95_s"] / 3600, **{k: o[k] for k in ("cloud_jobs", "cloud_usd", "wasted_compute_usd", "total_extra_usd")}))
    print("window", d, "done", flush=True)
df = pd.DataFrame(rows); df.to_csv(out + ".csv", index=False)
t = df.groupby(["cloud_nodes_per_pool", "policy"]).agg(q_ratio=("q_ratio", "mean"), hp_wait_h=("hp_wait_h", "mean"), hp_p95_h=("hp_p95_h", "mean"), cloud_jobs=("cloud_jobs", "mean"),
        cloud_usd_per_window=("cloud_usd", "mean"), waste_usd=("wasted_compute_usd", "mean")).round(3)
t["cloud_usd_per_day"] = (t.cloud_usd_per_window / 3).round(0)
print(t.to_string()); Path(out + ".json").write_text(t.reset_index().to_json(orient="records", indent=1))
