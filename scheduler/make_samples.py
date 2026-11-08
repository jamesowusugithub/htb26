"""Write sample runs for the frontend: same busy window under several policies.

    python -m scheduler.make_samples --start-day 90 --hours 6
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from . import data
from .policies import POLICIES
from .run_baselines import setup, run_policy
from .export import export_ndjson
from .metrics import summarize


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-day", type=float, default=90)
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--load", type=float, default=0.85)
    ap.add_argument("--out", default="samples")
    ap.add_argument("--policies", default="fifo,priority_fifo,sjf_oracle")
    ap.add_argument("--snapshot-s", type=float, default=60)
    a = ap.parse_args()
    pools, jobs, base, cluster = setup(a.load)
    s, e = a.start_day * 86400, a.start_day * 86400 + a.hours * 3600
    w = data.make_workload(jobs, s, e)
    out = Path(a.out)
    summary = {}
    for name in a.policies.split(","):
        spec = POLICIES[name]
        S = run_policy(cluster, w, spec, log_events=True, snapshot_dt=a.snapshot_s)
        n = export_ndjson(out / f"run_{name}.ndjson", S, w, cluster, policy_name=name, realistic=spec.realistic,
                          preempt=spec.preempt, resume=False, window_len_s=e - s)
        m = summarize(S, w, cluster, util_hi=e - s)
        summary[name] = {"lines": n, "hp_wait_mean_s": m["hp"]["wait_mean_s"], "hp_wait_p95_s": m["hp"]["wait_p95_s"],
                         "spot_wait_mean_s": m["spot"]["wait_mean_s"], "utilisation": m["utilisation_overall"]}
        print(name, summary[name])
    (out / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
