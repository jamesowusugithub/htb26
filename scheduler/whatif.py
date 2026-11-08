"""What-if scenarios: steerable perturbations of a real trace window.

A scenario = parameters + seed, so any result is reproducible and the frontend can re-run it under
every policy on the *same* workload. Perturbations apply to jobs *arriving in the window*; the
carry-over (jobs already running when the window opens) is left as observed.

    python -m scheduler.whatif --preset growth_30 --start-day 90
"""
from __future__ import annotations
import argparse, hashlib, json
from dataclasses import dataclass, field, asdict
import numpy as np
import pandas as pd
from . import data
from .data import UNIT, Workload
from .policies import POLICIES
from .metrics import summarize
from .display import Display, DEFAULT_PODS


@dataclass
class Scenario:
    name: str = "baseline"
    seed: int = 0
    start_day: float = 90.0
    days: float = 5.0
    arrival_mult: float = 1.0                  # >1 duplicates (jittered) jobs, <1 thins them
    spot_share: float | None = None            # target fraction of window jobs that are spot
    burst: dict | None = None                  # {"start_h": 24, "duration_h": 6, "mult": 3.0}
    duration_mult: float = 1.0                 # scale every window job's runtime
    capacity: dict | float = 1.0               # node-count factor: one number or {pool_id: factor}
    load_target: float = 0.85                  # capacity calibration the factors are relative to
    resume_preempted: bool = False
    # --- live what-if controls used by the 3D room (all times in hours since window start) ---
    failures: list = field(default_factory=list)          # [{"board": 7, "at_h": 6.0, "repair_after_h": 4.0 | None}]
    cooling_fault: dict | None = None                     # {"at_h": 6.0, "delta_c": 35.0, "duration_h": 6.0 | None}
    injected_jobs: list = field(default_factory=list)     # [{"at_h": 3.0, "pool": "a10", "gpus": 1, "priority": "hp", "duration_s": 900}]
    display_pools: list = field(default_factory=lambda: list(DEFAULT_PODS))   # pods 1..4 in the room
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def scenario_id(self) -> str:
        d = self.to_dict()
        d.pop("note", None)
        return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:10]

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


PRESETS: dict[str, Scenario] = {s.name: s for s in [
    Scenario("baseline", note="Trace window as observed"),
    Scenario("growth_30", arrival_mult=1.3, note="Demand grows 30%"),
    Scenario("demand_halves", arrival_mult=0.5, note="Demand falls to 50%: a quiet period"),
    Scenario("burst_3x", burst={"start_h": 24, "duration_h": 8, "mult": 3.0}, note="3x arrival burst for 8 hours on day 2"),
    Scenario("spot_heavy", spot_share=0.40, note="40% of jobs become spot (observed: ~11%)"),
    Scenario("longer_jobs", duration_mult=1.5, note="Jobs run 50% longer"),
    Scenario("lose_a10_capacity", capacity={"a10": 0.8}, note="A10 pool loses 20% of its nodes"),
    Scenario("capacity_plus_20", capacity=1.2, note="All pools gain 20% nodes"),
    Scenario("live_demo", start_day=90.0, days=1.0, note="Busy day: one-day window used by the 3D room"),
    Scenario("heldout_demo", start_day=130.0, days=1.0, note="Busy day from the held-out period (never used to train or select the RL policy)"),
    Scenario("node_failure", start_day=90.0, days=1.0, failures=[{"board": 7, "at_h": 6.0, "repair_after_h": 4.0}],
             note="Board 8 (A10 pod) loses its nodes at hour 6 and recovers at hour 10"),
    Scenario("cooling_fault", start_day=90.0, days=1.0, cooling_fault={"at_h": 6.0, "delta_c": 35.0, "duration_h": 6.0},
             note="Cooling fault: +35 C on every board from hour 6 to 12 (assumed fault size)"),
    Scenario("spike_and_failure", start_day=90.0, days=1.0, burst={"start_h": 6.0, "duration_h": 4.0, "mult": 4.0},
             failures=[{"board": 1, "at_h": 7.0, "repair_after_h": None}],
             note="4x arrival spike from hour 6 and a permanent board failure at hour 7"),
]}


def failure_events(sc: "Scenario", cluster: data.Cluster) -> list:
    """Scenario failures -> [(t_s, global_node, kind)] with kind 1=fail, 2=repair. A board failure fails its node slice."""
    if not sc.failures:
        return []
    disp = Display(tuple(sc.display_pools))
    out = []
    for f in sc.failures:
        b = int(f["board"])
        if not 0 <= b < disp.n_boards:
            raise ValueError(f"failure board {b} out of range 0..{disp.n_boards - 1}")
        t0 = float(f["at_h"]) * 3600.0
        if t0 < 0:
            raise ValueError("failure at_h must be >= 0")
        nodes = disp.nodes_of_board(cluster, b)
        ra = f.get("repair_after_h")
        for n in nodes:
            out.append((t0, int(n), 1))
            if ra is not None:
                out.append((t0 + float(ra) * 3600.0, int(n), 2))
    return out


def _inject_jobs(sc: "Scenario", out: Workload) -> Workload:
    if not sc.injected_jobs:
        return out
    ids = [p["id"] for p in data.load_pool_config()]
    T = sc.days * 86400
    rows = []
    for k, j in enumerate(sc.injected_jobs):
        if j["pool"] not in ids:
            raise ValueError(f"unknown pool {j['pool']!r}")
        if j.get("priority", "hp") not in ("hp", "spot"):
            raise ValueError("priority must be 'hp' or 'spot'")
        t = float(j["at_h"]) * 3600.0
        if not 0 <= t < T:
            raise ValueError("injected job outside the window")
        rows.append((f"INJ-{k + 1:03d}", t, float(j.get("duration_s", 900.0)), ids.index(j["pool"]),
                     int(round(float(j.get("gpus", 1)) * UNIT)), 0 if j.get("priority", "hp") == "hp" else 1))
    ids_a = np.concatenate([out.job_id.astype(object), np.array([r[0] for r in rows], dtype=object)])
    sub = np.concatenate([out.submit, [r[1] for r in rows]])
    order = np.argsort(sub, kind="stable")
    cat = lambda a, b, dt=None: np.concatenate([a, np.array(b, dtype=dt)])[order]
    return Workload(job_id=ids_a[order], submit=sub[order], dur=cat(out.dur, [r[2] for r in rows], float),
                    pool=cat(out.pool, [r[3] for r in rows], np.int64), req=cat(out.req, [r[4] for r in rows], np.int64),
                    prio=cat(out.prio, [r[5] for r in rows], np.int64),
                    org=cat(out.org.astype(object), ["injected"] * len(rows), object),
                    eval_mask=cat(out.eval_mask, [True] * len(rows), bool), t0=out.t0,
                    elapsed0=cat(out.elapsed0 if out.elapsed0 is not None else np.zeros(len(out)), [0.0] * len(rows), float))



def _capacity_factors(cluster: data.Cluster, cap) -> np.ndarray:
    if isinstance(cap, dict):
        ids = [p["id"] for p in cluster.pools]
        unknown = set(cap) - set(ids)
        if unknown:
            raise ValueError(f"unknown pool(s): {sorted(unknown)}")
        return np.array([float(cap.get(i, 1.0)) for i in ids])
    return np.full(cluster.n_pools, float(cap))


def build_workload(jobs: pd.DataFrame, sc: Scenario) -> Workload:
    rng = np.random.default_rng(sc.seed)
    s, e = sc.start_day * 86400, (sc.start_day + sc.days) * 86400
    base = data.make_workload(jobs, s, e)
    T = e - s
    win = np.flatnonzero(base.eval_mask)
    carry = np.flatnonzero(~base.eval_mask)

    sub, dur, pool, req, prio = (base.submit[win].copy(), base.dur[win].copy(), base.pool[win].copy(),
                                 base.req[win].copy(), base.prio[win].copy())
    ids, org = base.job_id[win].astype(object), base.org[win]
    n0 = len(win)

    # arrival multiplier: thin or duplicate with jitter
    m = float(sc.arrival_mult)
    if m != 1.0:
        copies = np.floor(m).astype(int) + (rng.random(n0) < (m - np.floor(m))).astype(int) if m >= 1 else \
            (rng.random(n0) < m).astype(int)
        keep = copies > 0
        extra_idx = np.repeat(np.arange(n0), np.maximum(copies - 1, 0))
        jitter = np.clip(sub[extra_idx] + rng.normal(0, 1800.0, len(extra_idx)), 0, T - 1)
        ids = np.concatenate([ids[keep], np.array([f"{i}#x{k}" for k, i in enumerate(ids[extra_idx])], dtype=object)])
        sub = np.concatenate([sub[keep], jitter])
        dur = np.concatenate([dur[keep], dur[extra_idx]])
        pool = np.concatenate([pool[keep], pool[extra_idx]])
        req = np.concatenate([req[keep], req[extra_idx]])
        prio = np.concatenate([prio[keep], prio[extra_idx]])
        org = np.concatenate([org[keep], org[extra_idx]])

    # burst: bootstrap extra jobs into a time slot
    if sc.burst and sc.burst.get("mult", 1.0) > 1.0:
        bs, bd, bm = sc.burst["start_h"] * 3600.0, sc.burst["duration_h"] * 3600.0, float(sc.burst["mult"])
        if bs < T and n0 > 0:
            bd = min(bd, T - bs)
            n_extra = int(round((bm - 1.0) * n0 * bd / T))
            pick = rng.integers(0, n0, n_extra)
            ids = np.concatenate([ids, np.array([f"{i}#b{k}" for k, i in enumerate(base.job_id[win][pick])], dtype=object)])
            sub = np.concatenate([sub, bs + rng.random(n_extra) * bd])
            dur = np.concatenate([dur, base.dur[win][pick]])
            pool = np.concatenate([pool, base.pool[win][pick]])
            req = np.concatenate([req, base.req[win][pick]])
            prio = np.concatenate([prio, base.prio[win][pick]])
            org = np.concatenate([org, base.org[win][pick]])

    if sc.duration_mult != 1.0:
        dur = np.maximum(np.rint(dur * sc.duration_mult), 1.0)

    if sc.spot_share is not None and len(prio):
        target = int(round(sc.spot_share * len(prio)))
        cur = int(prio.sum())
        if target > cur:
            cand = np.flatnonzero(prio == 0)
            prio[rng.choice(cand, min(target - cur, len(cand)), replace=False)] = 1
        elif target < cur:
            cand = np.flatnonzero(prio == 1)
            prio[rng.choice(cand, min(cur - target, len(cand)), replace=False)] = 0

    # assemble: carry-over first, window jobs sorted by submit (stable)
    order = np.argsort(sub, kind="stable")
    n = len(carry) + len(order)
    out = Workload(
        job_id=np.concatenate([base.job_id[carry].astype(object), ids[order]]),
        submit=np.concatenate([base.submit[carry], sub[order]]),
        dur=np.concatenate([base.dur[carry], dur[order]]),
        pool=np.concatenate([base.pool[carry], pool[order]]),
        req=np.concatenate([base.req[carry], req[order]]),
        prio=np.concatenate([base.prio[carry], prio[order]]),
        org=np.concatenate([base.org[carry], org[order]]),
        eval_mask=np.concatenate([np.zeros(len(carry), bool), np.ones(len(order), bool)]), t0=s,
        elapsed0=np.concatenate([base.elapsed0[carry], np.zeros(len(order))]))
    assert len(out) == n
    return _inject_jobs(sc, out)


def build_cluster(base_cluster: data.Cluster, sc: Scenario) -> data.Cluster:
    f = _capacity_factors(base_cluster, sc.capacity)
    if np.allclose(f, 1.0):
        return base_cluster
    return data.scale_cluster(base_cluster, f)


def workload_stats(w: Workload, cluster: data.Cluster) -> dict:
    ev = w.eval_mask
    return {"jobs_total": int(len(w)), "jobs_arriving": int(ev.sum()), "carryover_jobs": int((~ev).sum()),
            "spot_share": float(w.prio[ev].mean()) if ev.any() else float("nan"),
            "gpu_hours_arriving": float((w.req[ev] / UNIT * w.dur[ev]).sum() / 3600),
            "nodes_per_pool": {p["id"]: int(c) for p, c in zip(cluster.pools, cluster.node_counts())},
            "gpus_per_pool": {p["id"]: float(c) for p, c in zip(cluster.pools, cluster.capacity_gpus())}}


def run_scenario(sc: Scenario, jobs: pd.DataFrame, calibrated: data.Cluster, policies: list[str] | None = None,
                 log_events: bool = False, **sim_kw) -> dict:
    """Run a scenario under each policy on the identical workload. Returns metrics (+ states if log_events)."""
    from .run_baselines import run_policy
    names = policies or list(POLICIES)
    w = build_workload(jobs, sc)
    cluster = build_cluster(calibrated, sc)
    out = {"scenario": sc.to_dict(), "scenario_id": sc.scenario_id, "workload": workload_stats(w, cluster),
           "policies": {}, "_states": {}, "_workload": w, "_cluster": cluster}
    hint = None
    for name in names:
        spec = POLICIES[name]
        est = None
        if spec.est_mode == "hint":        # realistic policies may only see the hint model's PREDICTED durations, never the true ones
            from .duration_model import load_or_fit
            hint = hint or load_or_fit(jobs, 40)
            est = hint.predict_seconds(w.job_id)
            est = np.where(np.isfinite(est), est, np.nanmedian(est))
        S = run_policy(cluster, w, spec, resume=sc.resume_preempted, log_events=log_events, est=est,
                       failures=failure_events(sc, cluster), **sim_kw)
        m = summarize(S, w, cluster, util_hi=sc.days * 86400)
        out["policies"][name] = {"realistic": spec.realistic, "metrics": m}
        out["_states"][name] = S
    return out


def compare_table(res: dict) -> pd.DataFrame:
    rows = []
    for name, r in res["policies"].items():
        m = r["metrics"]
        rows.append({"policy": name, "realistic": r["realistic"], "util": m["utilisation_overall"],
                     "hp_wait_mean_h": m["hp"]["wait_mean_s"] / 3600, "hp_wait_p95_h": m["hp"]["wait_p95_s"] / 3600,
                     "spot_wait_mean_h": m["spot"]["wait_mean_s"] / 3600, "hp_bsld": m["hp"]["bsld_mean"],
                     "preemptions": m["total_preemption_events"], "wasted_gpu_h": m["overall"]["wasted_gpu_h"]})
    return pd.DataFrame(rows)


def main():
    from .run_baselines import setup
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="baseline", choices=list(PRESETS))
    ap.add_argument("--start-day", type=float)
    ap.add_argument("--days", type=float)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--policies", default=",".join(POLICIES))
    a = ap.parse_args()
    sc = Scenario.from_dict(PRESETS[a.preset].to_dict())
    for k in ("start_day", "days", "seed"):
        if getattr(a, k) is not None:
            setattr(sc, k, getattr(a, k))
    pools, jobs, base, cluster = setup(sc.load_target)
    res = run_scenario(sc, jobs, cluster, a.policies.split(","))
    print(f"scenario {sc.name} [{sc.scenario_id}] {sc.note}\n", json.dumps(res["workload"], indent=1)[:900])
    pd.set_option("display.width", 200)
    print(compare_table(res).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
