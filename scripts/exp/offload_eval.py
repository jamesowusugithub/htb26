"""Cost-aware offload policy (the agent itself decides when to rent SIMULATED cloud capacity) vs the same cloud rule everyone else uses.
HELD-OUT windows, 5 cloud nodes/pool. q_ratio is vs priority FIFO WITHOUT cloud. Cost is predicted-hint budgeted; spend = committed rental of started jobs."""
import sys; from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster, sim_kwargs
from scheduler.env import SchedulingEnv
from scheduler.sim import FC_QINT
from scheduler.outcomes import cost_outcomes
from scheduler.heuristics import hint_rule_with_offload
pools, jobs, base, cl = setup(0.85); hint = load_or_fit(jobs, 40); ids = [p["id"] for p in pools]
m5 = MaskablePPO.load("models/ppo_u7_offload_shuf/best", device="cpu"); m4 = MaskablePPO.load("models/ppo_u6_shuf_s12/best", device="cpu")
env_off = SchedulingEnv(jobs, cl, hint, K=16, offload=True, offload_min_wait_s=1800.0, cost_weight=0.5, shuffle_slots=True)
env_plain = SchedulingEnv(jobs, cl, hint, K=16, shuffle_slots=True)
rows = []
def play(env, sc, ch):
    obs, _ = env.reset(options={"scenario": sc}); done = False
    while not done:
        obs, r, te, tr, info = env.step(int(ch(obs, env.action_masks()))); done = te or tr
    return env.S, env.w, info["metrics"]
for d in (130.0, 133.0, 145.0, 151.0, 157.0, 169.0):
    sc0 = Scenario(start_day=d, days=3.0, seed=0); w0 = build_workload(jobs, sc0); c0 = build_cluster(cl, sc0)
    qref = float(run_policy(c0, w0, POLICIES["priority_fifo"], snapshot_dt=None).fc[FC_QINT])
    cloud_rule = {"nodes_per_pool": 5, "gpus_per_node": 8, "overflow_wait_s": 7200.0, "max_job_cost_usd": 30.0}
    cloud_agent = {"nodes_per_pool": 5, "gpus_per_node": 8, "overflow_wait_s": 0.0, "max_job_cost_usd": 30.0, "offload_min_wait_s": 1800.0}
    def rec(name, S, w, m):
        o = cost_outcomes(S, w, ids)
        rows.append(dict(day=d, policy=name, q_ratio=float(S.fc[FC_QINT]) / qref, hp_wait_h=m["hp"]["wait_mean_s"] / 3600, hp_p95_h=m["hp"]["wait_p95_s"] / 3600, cloud_jobs=o["cloud_jobs"], cloud_usd=o["cloud_usd"]))
    sc = Scenario(start_day=d, days=3.0, seed=0, cloud=cloud_rule)
    rec("RL + 2h overflow rule", *play(env_plain, sc, lambda o, mk: m4.predict(o, action_masks=mk, deterministic=True)[0]))
    sca = Scenario(start_day=d, days=3.0, seed=0, cloud=cloud_agent)
    rec("RL, agent decides offload", *play(env_off, sca, lambda o, mk: m5.predict(o, action_masks=mk, deterministic=True)[0]))
    rec("rule + offload rule (same action space)", *play(env_off, sca, lambda o, mk: hint_rule_with_offload(o, mk, 16, 6)))
    print("window", d, flush=True)
df = pd.DataFrame(rows); df.to_csv("analysis/rl/offload_eval.csv", index=False)
t = df.groupby("policy").agg(q_ratio=("q_ratio", "mean"), hp_wait_h=("hp_wait_h", "mean"), hp_p95_h=("hp_p95_h", "mean"), cloud_jobs=("cloud_jobs", "mean"), cloud_usd=("cloud_usd", "mean")).round(3)
t["cloud_usd_per_day"] = (t.cloud_usd / 3).round(0); print(t.to_string()); t.reset_index().to_json("analysis/rl/offload_eval.json", orient="records", indent=1)
