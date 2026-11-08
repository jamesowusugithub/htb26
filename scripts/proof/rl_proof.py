"""Evidence that the RL scheduler is trained, is used, and behaves differently from untrained/simple policies.
    python scripts/proof/rl_proof.py        -> analysis/proof/rl-proof.json, rl-training-proof.png
"""
import hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sb3_contrib import MaskablePPO
from scheduler.run_baselines import setup
from scheduler.duration_model import load_or_fit
from scheduler.env import SchedulingEnv
from scheduler.eval_rl import evaluate
from scheduler.whatif import Scenario
from scheduler.heuristics import hp_then_min_hint

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "analysis/proof"; OUT.mkdir(parents=True, exist_ok=True)
MODEL = ROOT / "models/ppo_bc/best.zip"
pools, jobs, base, cl = setup(0.85)
hint = load_or_fit(jobs, 40)
K = 8

# ---- 1. model facts + training history
trained = MaskablePPO.load(MODEL, device="cpu")
hist = json.loads((ROOT / "models/ppo_bc/history.json").read_text())
hist_a = json.loads((ROOT / "models/ppo_a/history.json").read_text())
n_params = sum(p.numel() for p in trained.policy.parameters())
facts = {"file": str(MODEL.relative_to(ROOT)), "bytes": MODEL.stat().st_size, "sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest()[:16],
         "policy_parameters": int(n_params), "training": {k: hist["args"][k] for k in ("steps", "envs", "lr", "bc_episodes", "wide", "net", "seed")},
         "training_seconds": round(hist["seconds"]), "validation_checks": len(hist["val"])}

# ---- 2. control: untrained network of identical architecture vs trained vs baselines, on HELD-OUT windows (day >= 130)
env0 = SchedulingEnv(jobs, cl, hint)
untrained = MaskablePPO("MlpPolicy", env0, policy_kwargs=dict(net_arch=dict(pi=[128, 128], vf=[128, 128])), seed=0, device="cpu")
pred = lambda m: (lambda obs, mask: m.predict(obs, action_masks=mask, deterministic=True)[0])
test_days = [130.0, 133.0, 145.0, 151.0, 157.0, 169.0]
scen = [Scenario(name="observed", start_day=d, days=3.0, seed=0) for d in test_days]
df = evaluate(jobs, cl, hint, scen, {"rl_trained": pred(trained), "rl_untrained": pred(untrained)},
              baselines=["priority_fifo", "backfill_median", "sjf_hint", "sjf_oracle"])
tab = df.groupby("policy", sort=False).agg(hp_wait_mean_h=("hp_wait_mean_h", "mean"), hp_wait_p95_h=("hp_wait_p95_h", "mean"),
                                           spot_wait_mean_h=("spot_wait_mean_h", "mean"), q_ratio=("q_ratio", "mean")).round(3)
print("\nHELD-OUT WINDOWS (days 130-172, never used in training/validation)\n", tab.to_string())

# ---- 3. what does the trained agent actually decide?
def decisions(model, day):
    env = SchedulingEnv(jobs, cl, hint, fixed=dict(start_day=day, days=3.0, arrival_mult=1.0, capacity=1.0, seed=0))
    obs, _ = env.reset()
    n = real = vs_head = vs_heur = shorter_than_head = hp_over_spot = 0
    done = False
    while not done:
        mask = env.action_masks()
        a = int(model.predict(obs, action_masks=mask, deterministic=True)[0])
        valid = np.flatnonzero(mask[:K])
        if len(valid) >= 2:                      # a real choice between at least two startable jobs
            real += 1
            head = 0 if mask[0] else None
            heur = hp_then_min_hint(obs, mask, K, 6)
            vs_head += int(head is not None and a != head)
            vs_heur += int(a == heur)
            if head is not None and a != head:
                S = env.S
                shorter_than_head += int(S.est[S.cand_job[a]] < S.est[S.cand_job[head]])
        n += 1
        obs, r, te, tr, info = env.step(a)
        done = te or tr
    return {"window_day": day, "decisions": n, "real_choices": real,
            "pct_choices_where_rl_skips_the_queue_head": round(100 * vs_head / max(real, 1), 1),
            "pct_choices_identical_to_hint_rule": round(100 * vs_heur / max(real, 1), 1),
            "pct_skips_that_pick_a_shorter_predicted_job": round(100 * shorter_than_head / max(vs_head, 1), 1)}
dec = {"trained": decisions(trained, 130.0), "untrained": decisions(untrained, 130.0)}
print("\nDECISIONS (day-130 window)\n", json.dumps(dec, indent=1))

# ---- 4. validation baselines for the training curve
val = evaluate(jobs, cl, hint, [Scenario(name="val", start_day=d, days=3.0, seed=0) for d in (118.0, 121.0, 124.0)], {}, baselines=["priority_fifo", "sjf_hint"])
val_ratio = val.groupby("policy").q_ratio.mean().to_dict()

# ---- chart
fig, ax = plt.subplots(1, 2, figsize=(13, 4.6))
for h, label, c in ((hist_a, "PPO from scratch (3M steps)", "#c0794d"), (hist, "behaviour clone + PPO (2M steps)", "#1f6f5c")):
    v = pd.DataFrame(h["val"]); ax[0].plot(v.steps / 1e6, v.val_q_ratio, marker="o", color=c, label=label)
ax[0].axhline(1.0, color="#888", ls="--", lw=1); ax[0].text(0.02, 1.003, "priority FIFO = 1.0", color="#666", fontsize=8)
ax[0].axhline(val_ratio["sjf_hint"], color="#3b6fb6", ls=":", lw=1.4); ax[0].text(0.02, val_ratio["sjf_hint"] + .004, "shortest-predicted-job rule", color="#3b6fb6", fontsize=8)
ax[0].set_title("Validation queue-time vs training (days 118-124)\nlower is better"); ax[0].set_xlabel("training steps (millions)"); ax[0].set_ylabel("queue time / priority-FIFO"); ax[0].legend(fontsize=8, loc="center right")
order = ["priority_fifo", "backfill_median", "rl_untrained", "rl_trained", "sjf_hint", "sjf_oracle"]
cols = {"priority_fifo": "#999", "backfill_median": "#999", "rl_untrained": "#c0794d", "rl_trained": "#1f6f5c", "sjf_hint": "#3b6fb6", "sjf_oracle": "#bbb"}
vals = [tab.loc[o, "q_ratio"] for o in order]
bars = ax[1].bar(range(len(order)), vals, color=[cols[o] for o in order])
for b, v in zip(bars, vals): ax[1].text(b.get_x() + b.get_width() / 2, v + .02, f"{v:.2f}", ha="center", fontsize=9)
ax[1].set_xticks(range(len(order))); ax[1].set_xticklabels(["priority\nFIFO", "backfill", "RL\nuntrained", "RL\ntrained", "shortest\npredicted", "oracle\n(ceiling)"], fontsize=8)
ax[1].set_title("Held-out windows (days 130-172): queue time vs priority-FIFO\nlower is better"); ax[1].set_ylim(0, max(vals) * 1.15)
plt.tight_layout(); plt.savefig(OUT / "rl-training-proof.png", dpi=130)
(OUT / "rl-proof.json").write_text(json.dumps({"model": facts, "heldout_windows": test_days, "table": tab.reset_index().to_dict(orient="records"),
                                              "decisions": dec, "val_baselines_q_ratio": val_ratio, "val_curve_trained": hist["val"], "val_curve_scratch": hist_a["val"]}, indent=1))
print("\nmodel:", json.dumps(facts))
