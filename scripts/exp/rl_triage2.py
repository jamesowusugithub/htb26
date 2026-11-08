"""Which part of the in-env rule loses vs the full-queue sjf_hint? Variants on 6 held-out windows."""
import sys; from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler.run_baselines import setup
from scheduler.duration_model import load_or_fit
from scheduler.whatif import Scenario
from scheduler.env import SchedulingEnv
from scheduler.heuristics import hp_then_min_hint
pools, jobs, base, cl = setup(0.85); h = load_or_fit(jobs, 40)
def pure_min(o, mk, K=16, P=6):
    b = P+6; best=None; bv=9e9
    for k in range(K):
        if mk[k] and o[b+8*k+5] < bv: bv=o[b+8*k+5]; best=k
    return best if best is not None else K
def play(env, sc, ch):
    obs,_ = env.reset(options={"scenario": sc}); done=False
    while not done:
        obs,r,te,tr,info = env.step(int(ch(obs, env.action_masks()))); done = te or tr
    return info["qint_ratio_vs_priority_fifo"]
days=[133,142,151,160,169,178]
for name,K,ch in (("hp_then_min K16",16,lambda o,m:hp_then_min_hint(o,m,16,6)),("pure_min_hint K16",16,pure_min),("hp_then_min K32",32,lambda o,m:hp_then_min_hint(o,m,32,6))):
    env=SchedulingEnv(jobs, cl, h, K=K)
    v=[play(env, Scenario(start_day=float(d),days=3.0,seed=0), ch) for d in days]
    print(name, np.round(v,3), round(float(np.mean(v)),3), flush=True)
