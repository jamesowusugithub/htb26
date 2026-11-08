"""Operating outcomes per policy on HELD-OUT windows (no cloud): queue-time ratio, eviction-waste cost and thermal exposure.
Thermal = node-hours at/above the ASSUMED 80 C alert threshold under the thermal PROXY, in normal ambient and under a +35 C cooling fault (hours 12-36)."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler.env import SchedulingEnv
from scheduler.sim import FC_QINT
from scheduler.outcomes import cost_outcomes, thermal_outcomes
from scheduler.thermal import ThermalProxy
model_path, K, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
pools, jobs, base, cl = setup(0.85); hint = load_or_fit(jobs, 40); ids = [p["id"] for p in pools]; th = ThermalProxy.load()
model = MaskablePPO.load(model_path, device="cpu"); env = SchedulingEnv(jobs, cl, hint, K=K, log_events=True, snapshot_dt=None)
FAULT = {"at_h": 12.0, "delta_c": 35.0, "duration_h": 24.0}
rows = []
for d in (130.0, 133.0, 145.0, 151.0, 157.0, 169.0):
    sc = Scenario(start_day=d, days=3.0, seed=0); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
    est = hint.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est))
    runs = {}
    for pol in ("priority_fifo", "backfill_median", "sjf_hint"):
        runs[pol] = (run_policy(c, w, POLICIES[pol], est=est if pol == "sjf_hint" else None, snapshot_dt=None, log_events=True), w, c)
    obs, _ = env.reset(options={"scenario": sc}); done = False
    while not done:
        obs, r, te, tr, info = env.step(int(model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0])); done = te or tr
    runs["rl_ppo"] = (env.S, env.w, env.cluster)
    qref = float(runs["priority_fifo"][0].fc[FC_QINT])
    for pol, (S, ww, cc) in runs.items():
        o = cost_outcomes(S, ww, ids); n = thermal_outcomes(S, cc, th, 3 * 86400.0); f = thermal_outcomes(S, cc, th, 3 * 86400.0, FAULT)
        rows.append(dict(day=d, policy=pol, q_ratio=float(S.fc[FC_QINT]) / qref, wasted_gpu_h=o["wasted_gpu_hours"], waste_usd=o["wasted_compute_usd"],
                         viol_normal_node_h=n["violation_node_hours"], peak_normal_c=n["peak_c"], viol_fault_node_h=f["violation_node_hours"], hot_nodes_fault=f["nodes_ever_hot"], peak_fault_c=f["peak_c"]))
    print("window", d, flush=True)
df = pd.DataFrame(rows); df.to_csv(out + ".csv", index=False)
t = df.groupby("policy").agg(q_ratio=("q_ratio", "mean"), wasted_gpu_h=("wasted_gpu_h", "mean"), waste_usd=("waste_usd", "mean"), viol_normal=("viol_normal_node_h", "mean"), peak_normal_c=("peak_normal_c", "max"),
        viol_fault=("viol_fault_node_h", "mean"), hot_nodes_fault=("hot_nodes_fault", "mean"), peak_fault_c=("peak_fault_c", "max")).round(2)
print(t.loc[["priority_fifo", "backfill_median", "sjf_hint", "rl_ppo"]].to_string()); Path(out + ".json").write_text(t.reset_index().to_json(orient="records", indent=1))
