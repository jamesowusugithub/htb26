"""Held-out evaluation of a trained policy (test windows start at day >= 130; never seen in training/validation).

    python -m scheduler.run_eval --model models/ppo_a/best --out analysis/rl/ppo_a
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from sb3_contrib import MaskablePPO

from .run_baselines import setup
from .duration_model import load_or_fit
from .eval_rl import evaluate, BASELINES
from .whatif import Scenario

BUSY_Q = 3e4   # weighted job-hours of priority-FIFO queue time that makes a window "busy"


def test_scenarios():
    plain = [Scenario(name="observed", start_day=float(d), days=3.0, seed=0) for d in range(130, 181, 3)]
    stress = []
    for d in (130.0, 133.0, 157.0, 169.0):
        stress += [Scenario(name="growth_30", start_day=d, days=3.0, arrival_mult=1.3, seed=1),
                   Scenario(name="burst_3x", start_day=d, days=3.0, burst={"start_h": 20, "duration_h": 8, "mult": 3.0}, seed=1),
                   Scenario(name="spot_heavy", start_day=d, days=3.0, spot_share=0.4, seed=1),
                   Scenario(name="lose_a10_20pct", start_day=d, days=3.0, capacity={"a10": 0.8}, seed=1)]
    # combined layer: arrival shapes of the most bursty windows of HELD-OUT BurstGPT trace 3 (never used in training)
    from . import burst_profiles as bp
    llm = []
    for k, (a, ratio) in enumerate(bp.burstiest("burstgpt_3", 72, 4)):
        for d in (130.0, 157.0):
            llm.append(Scenario(name="llm_burst_heldout", start_day=d, days=3.0, seed=2, arrival_profile=bp.window_profile("burstgpt_3", a, 72),
                                arrival_profile_source=f"burstgpt_3 hours {a}-{a + 72} (peak/mean {ratio:.1f}x)"))
    return plain, stress, llm


def paired(df: pd.DataFrame, a: str, b: str):
    """Win rate and mean change of policy a vs policy b on identical (scenario, window) pairs, queue-time metric."""
    x = df[df.policy == a].set_index(["scenario", "start_day"]).q_ratio
    y = df[df.policy == b].set_index(["scenario", "start_day"]).q_ratio
    d = (x - y).dropna()
    return {"a": a, "b": b, "pairs": int(len(d)), "a_better": int((d < -1e-6).sum()), "b_better": int((d > 1e-6).sum()),
            "mean_q_ratio_a": float(x.loc[d.index].mean()), "mean_q_ratio_b": float(y.loc[d.index].mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--K", type=int, default=8)
    ap.add_argument("--skip-stress", action="store_true", help="skip the 16 what-if stress scenarios (faster)")
    a = ap.parse_args()
    pools, jobs, base, cl = setup(0.85)
    hint = load_or_fit(jobs, 40)
    model = MaskablePPO.load(a.model, device="cpu")
    pred = lambda obs, mask: model.predict(obs, action_masks=mask, deterministic=True)[0]
    plain, stress, llm = test_scenarios()
    if a.skip_stress:
        stress = []
    df = evaluate(jobs, cl, hint, plain + stress + llm, {"rl_ppo": pred}, K=a.K)
    df["kind"] = np.where(df.scenario == "observed", "observed", np.where(df.scenario == "llm_burst_heldout", "burstgpt-shape", "what-if"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "results.csv", index=False)
    pd.set_option("display.width", 220)
    order = ["fifo", "priority_fifo", "backfill_median", "sjf_hint", "rl_ppo", "sjf_oracle"]
    report = {}
    pf = df[df.policy == "priority_fifo"].set_index(["scenario", "start_day"])
    # queue-time of priority-FIFO per window (absolute) decides which windows are busy
    # q_ratio is relative; recover busy flag from HP wait of the baseline instead
    busy_keys = set(pf[(pf.hp_wait_mean_h > 0.5)].index)
    df["busy"] = [(s, d) in busy_keys for s, d in zip(df.scenario, df.start_day)]
    for label, sub in [("observed windows (all)", df[df.kind == "observed"]),
                       ("observed windows (busy only)", df[(df.kind == "observed") & df.busy]),
                       ("what-if scenarios on busy windows", df[df.kind == "what-if"]),
                       ("held-out BurstGPT (trace 3) arrival shapes", df[df.kind == "burstgpt-shape"])]:
        if sub.empty:
            continue
        t = sub.groupby("policy").agg(windows=("q_ratio", "size"), hp_wait_mean_h=("hp_wait_mean_h", "mean"),
                                      hp_wait_p95_h=("hp_wait_p95_h", "mean"), spot_wait_mean_h=("spot_wait_mean_h", "mean"),
                                      q_ratio=("q_ratio", "mean"), util=("util", "mean"), preemptions=("preemptions", "mean"),
                                      wasted_gpu_h=("wasted_gpu_h", "mean")).loc[order].round(3)
        print(f"\n=== {label}: {t.windows.iloc[0]} windows ==="); print(t.drop(columns="windows").to_string())
        report[label] = {"table": t.reset_index().to_dict(orient="records"),
                         "rl_vs_sjf_hint": paired(sub, "rl_ppo", "sjf_hint"), "rl_vs_priority_fifo": paired(sub, "rl_ppo", "priority_fifo"),
                         "rl_vs_backfill": paired(sub, "rl_ppo", "backfill_median"), "rl_vs_fifo": paired(sub, "rl_ppo", "fifo")}
        for other in ("fifo", "backfill", "sjf_hint"):
            r = report[label]["rl_vs_" + other]
            print(f"  RL vs {other:9s}: RL has less queue time in {r['a_better']} of {r['pairs']} paired windows (worse in {r['b_better']})")
    (out / "report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
