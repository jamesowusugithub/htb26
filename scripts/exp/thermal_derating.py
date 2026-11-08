"""Can thermal information change a decision usefully? Cooling fault +35 C for hours 12-36 on HELD-OUT windows (proxy temperatures; 80 C threshold is an assumption).
A = no derating | B = derating (cap node utilisation where the proxy says it would overheat) | C = derating + priced cloud overflow (10 nodes/pool, >=2 h wait, <= $30 predicted).
Reference for q_ratio: priority FIFO, no fault, no cloud, same workload."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster, sim_kwargs
from scheduler.sim import FC_QINT
from scheduler.metrics import summarize
from scheduler.outcomes import cost_outcomes, thermal_outcomes
from scheduler.thermal import ThermalProxy
pools, jobs, base, cl = setup(0.85); hint = load_or_fit(jobs, 40); ids = [p["id"] for p in pools]; th = ThermalProxy.load()
FAULT = {"at_h": 12.0, "delta_c": 35.0, "duration_h": 24.0}
CLOUD = {"nodes_per_pool": 10, "gpus_per_node": 8, "overflow_wait_s": 7200.0, "max_job_cost_usd": 30.0}
CFG = {"A no derating": {}, "B derating": {"thermal_derating": {}}, "C derating + cloud": {"thermal_derating": {}, "cloud": CLOUD}}
rows = []
print("derating cap implied by the proxy for +35 C:", round(th.util_cap_for_fault(35.0), 3))
for d in (130.0, 133.0, 145.0, 151.0, 157.0, 169.0):
    s0 = Scenario(start_day=d, days=3.0, seed=0); w0 = build_workload(jobs, s0); c0 = build_cluster(cl, s0)
    qref = float(run_policy(c0, w0, POLICIES["priority_fifo"], snapshot_dt=None).fc[FC_QINT])
    for name, extra in CFG.items():
        sc = Scenario(start_day=d, days=3.0, seed=0, cooling_fault=FAULT, **extra); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
        est = hint.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est)); kw = sim_kwargs(sc, c)
        if sc.cloud: kw["overflow_est"] = est
        for pol in ("priority_fifo", "sjf_hint"):
            S = run_policy(c, w, POLICIES[pol], est=est if pol == "sjf_hint" else None, snapshot_dt=None, log_events=True, **kw)
            f = thermal_outcomes(S, c, th, 3 * 86400.0, FAULT); o = cost_outcomes(S, w, ids); m = summarize(S, w, c, util_hi=3 * 86400)
            rows.append(dict(day=d, config=name, policy=pol, q_ratio=float(S.fc[FC_QINT]) / qref, hp_p95_h=m["hp"]["wait_p95_s"] / 3600, violation_node_h=f["violation_node_hours"], hot_nodes=f["nodes_ever_hot"],
                             peak_c=f["peak_c"], cloud_usd=o["cloud_usd"], waste_usd=o["wasted_compute_usd"]))
    print("window", d, flush=True)
df = pd.DataFrame(rows); df.to_csv("analysis/rl/thermal_derating.csv", index=False)
t = df.groupby(["config", "policy"]).agg(q_ratio=("q_ratio", "mean"), hp_p95_h=("hp_p95_h", "mean"), violation_node_h=("violation_node_h", "mean"), hot_nodes=("hot_nodes", "mean"),
        peak_c=("peak_c", "max"), cloud_usd=("cloud_usd", "mean"), waste_usd=("waste_usd", "mean")).round(2)
print(t.to_string()); Path("analysis/rl/thermal_derating.json").write_text(t.reset_index().to_json(orient="records", indent=1))
