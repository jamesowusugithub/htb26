"""Write sample runs (schema 0.2.0) so the frontend can be developed and tested without a running backend.

    python -m scheduler.make_samples            # samples/run_*.ndjson
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .run_baselines import setup
from .whatif import PRESETS, Scenario, run_scenario
from .duration_model import load_or_fit
from .forecast import SurvivalCurves
from .display import Display
from .thermal import ThermalProxy
from .export import export_ndjson
from .policies import POLICIES

SAMPLES = {
    "run_priority_fifo": ("live_demo", "priority_fifo", {"days": 0.25}),
    "run_node_failure_cooling_fault": ("node_failure", "priority_fifo",
                                       {"days": 0.5, "cooling_fault": {"at_h": 3.0, "delta_c": 35.0, "duration_h": 2.0},
                                        "failures": [{"board": 7, "at_h": 2.0, "repair_after_h": 2.0}],
                                        "burst": {"start_h": 1.0, "duration_h": 1.0, "mult": 3.0}}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="samples")
    a = ap.parse_args()
    pools, jobs, base, cluster = setup(0.85)
    hint, thermal = load_or_fit(jobs, 40), ThermalProxy.load()
    summary = {}
    for name, (preset, policy, patch) in SAMPLES.items():
        sc = Scenario.from_dict({**PRESETS[preset].to_dict(), **patch})
        res = run_scenario(sc, jobs, cluster, [policy], log_events=True, snapshot_dt=60.0)
        w, c = res["_workload"], res["_cluster"]
        n = export_ndjson(Path(a.out) / f"{name}.ndjson", res["_states"][policy], w, c, policy_name=policy,
                          realistic=POLICIES[policy].realistic, preempt=POLICIES[policy].preempt, resume=False,
                          window_len_s=sc.days * 86400, display=Display(tuple(sc.display_pools)), thermal=thermal,
                          hint_est=hint.predict_seconds(w.job_id), scenario=sc.to_dict(),
                          survival=SurvivalCurves.fit(jobs, sc.start_day * 86400.0, c.n_pools),
                          extra_meta={"scenario": sc.to_dict(), "scenario_id": sc.scenario_id})
        summary[name] = {"lines": n, "scenario": sc.to_dict()}
        print(name, n, "lines")
    (Path(a.out) / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
