"""Does the RL LEARN anything? Held-out TEST (days 130-178, 17 windows), candidate slots randomly permuted so slot index carries no information.
Controls: random-weights network (same architecture), uniformly random valid choice, the hint rule; trained seeds. Nothing here was used for selection."""
import sys, json; from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup, run_policy
from scheduler.duration_model import load_or_fit
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler.env import SchedulingEnv
from scheduler.heuristics import hp_then_min_hint
from scheduler.sim import FC_QINT
pools, jobs, base, cl = setup(0.85); h = load_or_fit(jobs, 40); K = 16
seeds = [s for s in (11, 12, 13) if Path(f"models/ppo_u6_shuf_s{s}/best.zip").exists()]
env = SchedulingEnv(jobs, cl, h, K=K, shuffle_slots=True)
M = {f"RL trained (seed {s})": MaskablePPO.load(f"models/ppo_u6_shuf_s{s}/best", device="cpu") for s in seeds}
rnd_net = MaskablePPO("MlpPolicy", env, policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])), seed=0, device="cpu")
rng = np.random.default_rng(0)
def play(sc, ch):
    obs,_ = env.reset(options={"scenario": sc}); done=False
    while not done:
        obs,r,te,tr,info = env.step(int(ch(obs, env.action_masks()))); done = te or tr
    return info["qint_ratio_vs_priority_fifo"], info["metrics"]
def uniform(o, mk):
    v = np.flatnonzero(mk[:K]); return int(rng.choice(v)) if len(v) else K
rows = []
for d in range(130, 181, 3):
    sc = Scenario(start_day=float(d), days=3.0, seed=0); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
    qref = float(run_policy(c, w, POLICIES["priority_fifo"], snapshot_dt=None).fc[FC_QINT])
    est = h.predict_seconds(w.job_id); est = np.where(np.isfinite(est), est, np.nanmedian(est))
    r = {"day": d, "full-queue sjf_hint": float(run_policy(c, w, POLICIES["sjf_hint"], est=est, snapshot_dt=None).fc[FC_QINT]) / qref}
    r["hint rule (16 candidates)"], mr = play(sc, lambda o, m: hp_then_min_hint(o, m, K, 6)); r["hint rule spot_wait_h"] = mr["spot"]["wait_mean_s"] / 3600; r["hint rule hp_p95_h"] = mr["hp"]["wait_p95_s"] / 3600
    r["random valid choice"], _ = play(sc, uniform)
    r["random-weights network"], _ = play(sc, lambda o, mk: rnd_net.predict(o, action_masks=mk, deterministic=True)[0])
    for n, m in M.items():
        r[n], mm = play(sc, lambda o, mk, m=m: m.predict(o, action_masks=mk, deterministic=True)[0]); r[n + " spot_wait_h"] = mm["spot"]["wait_mean_s"] / 3600; r[n + " hp_p95_h"] = mm["hp"]["wait_p95_s"] / 3600
    rows.append(r); print(d, flush=True)
df = pd.DataFrame(rows); df.to_csv("analysis/rl/rl_shuffle_eval.csv", index=False)
t = df.drop(columns="day").mean().round(3); print(t.to_string()); Path("analysis/rl/rl_shuffle_eval.json").write_text(t.to_json(indent=1))
rule = df["hint rule (16 candidates)"]
print("windows where each seed beats the rule:", {n: int((df[n] < rule).sum()) for n in M})
