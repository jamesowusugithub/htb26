"""Held-out TEST (days 130-178, 17 windows): corrected HP-first candidates. Rule vs retrained agents (2 seeds). Nothing here was used for selection."""
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
pools, jobs, base, cl = setup(0.85); h = load_or_fit(jobs, 40); env = SchedulingEnv(jobs, cl, h, K=16)
M = {n: MaskablePPO.load(f"models/{n}/best", device="cpu") for n in ("ppo_u4_hpfirst_s11", "ppo_u4_hpfirst_s12", "ppo_u4_hpfirst_s13")}
def play(sc, ch):
    obs,_ = env.reset(options={"scenario": sc}); done=False
    while not done:
        obs,r,te,tr,info = env.step(int(ch(obs, env.action_masks()))); done = te or tr
    return info["qint_ratio_vs_priority_fifo"], info
rows=[]
for d in range(130,181,3):
    sc=Scenario(start_day=float(d),days=3.0,seed=0); w=build_workload(jobs,sc); c=build_cluster(cl,sc)
    qref=float(run_policy(c,w,POLICIES["priority_fifo"],snapshot_dt=None).fc[FC_QINT])
    est=h.predict_seconds(w.job_id); est=np.where(np.isfinite(est),est,np.nanmedian(est))
    r={"day":d,"full_queue_sjf_hint":float(run_policy(c,w,POLICIES["sjf_hint"],est=est,snapshot_dt=None).fc[FC_QINT])/qref,
       "in_env_rule":play(sc,lambda o,m:hp_then_min_hint(o,m,16,6))[0]}
    for n,m in M.items(): r[n]=play(sc,lambda o,mk,m=m:m.predict(o,action_masks=mk,deterministic=True)[0])[0]
    rows.append(r); print(d,flush=True)
df=pd.DataFrame(rows); df.to_csv("analysis/rl/rl_triage_hpfirst.csv",index=False)
t=df.drop(columns="day"); print(t.mean().round(3).to_string()); print("agent wins vs rule (windows):", {n:int((t[n]<t.in_env_rule).sum()) for n in M})
Path("analysis/rl/rl_triage_hpfirst.json").write_text(t.mean().round(4).to_json(indent=1))
