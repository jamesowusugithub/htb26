"""Does the RL still match the rule when the cluster is far from what it trained on (training: node counts x0.85-1.15)? Held-out days, 4 windows."""
import sys; from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup
from scheduler.duration_model import load_or_fit
from scheduler.whatif import Scenario
from scheduler.env import SchedulingEnv
from scheduler.heuristics import hp_then_min_hint
pools, jobs, base, cl = setup(0.85); h = load_or_fit(jobs, 40); env = SchedulingEnv(jobs, cl, h, K=16)
m = MaskablePPO.load("models/ppo_u4_hpfirst_s11/best", device="cpu")
def play(sc, ch):
    obs,_ = env.reset(options={"scenario": sc}); done=False
    while not done:
        obs,r,te,tr,info = env.step(int(ch(obs, env.action_masks()))); done = te or tr
    return info["qint_ratio_vs_priority_fifo"]
rule = lambda o,mk: hp_then_min_hint(o,mk,16,6); rl = lambda o,mk: m.predict(o,action_masks=mk,deterministic=True)[0]
print("capacity x   RL    rule   RL-rule   (queue-time ratio vs priority FIFO at that capacity; lower is better)")
for cap in (0.5, 0.7, 1.0, 1.4, 2.0):
    a=[];b=[]
    for d in (133,148,160,172):
        sc = Scenario(start_day=float(d), days=3.0, seed=0, capacity=cap)
        a.append(play(sc, rl)); b.append(play(sc, rule))
    print(f"{cap:>8}  {np.mean(a):.3f}  {np.mean(b):.3f}  {np.mean(a)-np.mean(b):+.3f}", flush=True)
