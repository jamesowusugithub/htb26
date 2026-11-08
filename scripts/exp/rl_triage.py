"""RL triage on the 17 HELD-OUT observed windows (days 130-178). Which of three suspicions is real?
 S1 hint-version mismatch: ppo_combined was trained on hint v2 but is served with v3.
 S2 cloning loss: the in-environment shortest-predicted rule (same 16 candidates) vs the trained agent vs the full-queue rule.
 Queue-time ratio vs priority FIFO (same metric as everywhere else)."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd, joblib
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler.env import SchedulingEnv
from scheduler.heuristics import hp_then_min_hint
from scheduler.sim import FC_QINT
pools, jobs, base, cl = setup(0.85)
h3 = load_or_fit(jobs, 40)
h2 = joblib.load("models/duration_hint_v2.joblib")
M = {"ppo_combined": MaskablePPO.load("models/ppo_combined/best", device="cpu"), "ppo_u1": MaskablePPO.load("models/ppo_u1_v3hint/best", device="cpu")}
def play(env, sc, chooser):
    obs, _ = env.reset(options={"scenario": sc}); done = False
    while not done:
        a = chooser(obs, env.action_masks()); obs, r, te, tr, info = env.step(int(a)); done = te or tr
    return info["qint_ratio_vs_priority_fifo"]
pred = lambda m: (lambda o, mk: m.predict(o, action_masks=mk, deterministic=True)[0])
rule = lambda o, mk: hp_then_min_hint(o, mk, 16, 6)
envs = {3: SchedulingEnv(jobs, cl, h3, K=16), 2: SchedulingEnv(jobs, cl, h2, K=16)}
rows = []
for d in range(130, 181, 3):
    sc = Scenario(start_day=float(d), days=3.0, seed=0); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
    qref = float(run_policy(c, w, POLICIES["priority_fifo"], snapshot_dt=None).fc[FC_QINT])
    r = {"day": d}
    for hv, h in ((2, h2), (3, h3)):
        est = h.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est))
        r[f"full_queue_rule_hint{hv}"] = float(run_policy(c, w, POLICIES["sjf_hint"], est=est, snapshot_dt=None).fc[FC_QINT]) / qref
        r[f"in_env_rule_16cand_hint{hv}"] = play(envs[hv], sc, rule)
        for name, m in M.items(): r[f"{name}_under_hint{hv}"] = play(envs[hv], sc, pred(m))
    rows.append(r); print("window", d, flush=True)
df = pd.DataFrame(rows); df.to_csv("analysis/rl/rl_triage.csv", index=False)
t = df.drop(columns="day").mean().round(3); print(t.to_string()); Path("analysis/rl/rl_triage.json").write_text(t.to_json(indent=1))
