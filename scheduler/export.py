"""Export a simulation run as NDJSON for the frontend (schema in scheduler/schema/events.schema.json)."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from .data import UNIT, Cluster, Workload, load_assumptions
from .sim import State, EV_ARRIVE, EV_START, EV_FINISH, EV_PREEMPT, SC_NEV, SC_NSNAP, SC_ERR

SCHEMA_VERSION = "0.1.0"


def _slots(mask: int) -> list[int]:
    return [k for k in range(8) if (mask >> k) & 1]


def export_ndjson(path, S: State, w: Workload, cluster: Cluster, *, policy_name: str, realistic: bool,
                  preempt: bool, resume: bool, window_len_s: float | None = None, extra_meta: dict | None = None) -> int:
    assert S.sc[SC_NEV] > 0, "simulate(..., log_events=True) required"
    pool_ids = [p["id"] for p in cluster.pools]
    pool_start = S.pool_start
    meta = {
        "type": "meta", "schema_version": SCHEMA_VERSION, "time_unit": "seconds_since_window_start",
        "window": {"start_trace_s": float(w.t0), "length_s": window_len_s, "jobs": int(len(w)),
                   "carryover_jobs": int((~w.eval_mask).sum())},
        "policy": {"name": policy_name, "realistic": realistic, "preempt": preempt,
                   "preempted_work": "resume" if resume else "restart_from_scratch"},
        "pools": [{"id": p["id"], "label": p["label"], "gpu_model_identifier": p["gpu_model_identifier"],
                   "identity": p["identity"], "capacity_gpus": float(cluster.capacity_gpus()[i]),
                   "node_count": int(cluster.node_counts()[i]),
                   "nodes": [int(g) for g in cluster.node_ngpu[pool_start[i]:pool_start[i + 1]]],
                   "scale_vs_observed": float(cluster.scale[i])} for i, p in enumerate(cluster.pools)],
        "assumptions": load_assumptions()["items"],
        "evidence_labels": {"observed": "from the Alibaba trace", "calculated": "derived arithmetic",
                            "assumption": "modelling choice, not data"},
        "notes": ["Waits, starts, evictions and node placement are simulated, not observed.",
                  "job.duration_s on arrive is the service time simulated (observed duration; remaining time for carry-over jobs)."],
        "error_flags": int(S.sc[SC_ERR])}
    if extra_meta:
        meta.update(extra_meta)

    n_ev = int(S.sc[SC_NEV])
    n_snap = int(S.sc[SC_NSNAP])
    tmax = float(window_len_s) if window_len_s is not None else float('inf')
    items = []  # (t, order, kind, index)
    for i in range(n_ev):
        if S.ev_t[i] <= tmax:
            items.append((float(S.ev_t[i]), 1, 0, i))
    for i in range(n_snap):
        if S.snap_t[i] <= tmax and i < n_snap - 1:     # final (end-of-sim) snapshot is dropped
            items.append((float(S.snap_t[i]), 0, 1, i))
    items.sort(key=lambda x: (x[0], x[1], x[3] if x[2] == 0 else -1))

    last_start = {}
    attempts = {}
    first_start = {}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = 0
    with open(path, "w") as f:
        f.write(json.dumps(meta) + "\n")
        lines += 1
        for t, _, kind, i in items:
            if kind == 1:
                rec = {"type": "snapshot", "t": round(t, 3), "pools": {}}
                for p, pid in enumerate(pool_ids):
                    rec["pools"][pid] = {
                        "busy_gpus": round(float(S.snap_busy[i, p]) / UNIT, 2),
                        "capacity_gpus": float(S.pool_cap[p]) / UNIT,
                        "queue_hp": int(S.snap_qhp[i, p]), "queue_spot": int(S.snap_qsp[i, p]),
                        "running_jobs": int(S.snap_run[i, p]), "max_free_gpus_on_one_node": int(S.snap_maxfull[i, p])}
                f.write(json.dumps(rec) + "\n")
                lines += 1
                continue
            typ, j = int(S.ev_type[i]), int(S.ev_job[i])
            pid = pool_ids[int(S.pool[j])]
            local_node = int(S.ev_node[i] - pool_start[S.pool[j]]) if S.ev_node[i] >= 0 else None
            base = {"t": round(t, 3), "job": str(w.job_id[j]), "pool": pid}
            if typ == EV_ARRIVE:
                rec = {"type": "arrive", **base, "gpus": float(S.req[j]) / UNIT,
                       "priority": "hp" if S.prio[j] == 0 else "spot", "duration_s": float(S.dur[j]),
                       "carryover": bool(not w.eval_mask[j]), "evidence": "observed"}
            elif typ == EV_START:
                last_start[j] = t
                first_start.setdefault(j, t)
                attempts[j] = attempts.get(j, 0) + 1
                rec = {"type": "start", **base, "node": local_node, "gpu_slots": _slots(int(S.ev_mask[i])),
                       "attempt": attempts[j]}
            elif typ == EV_FINISH:
                rec = {"type": "finish", **base, "node": local_node,
                       "wait_s": round(first_start[j] - float(S.submit[j]), 3), "evidence": "calculated"}
            else:
                rec = {"type": "preempt", **base, "node": local_node, "gpu_slots": _slots(int(S.ev_mask[i])),
                       "work_lost_gpu_s": 0.0 if resume else round((t - last_start[j]) * float(S.req[j]) / UNIT, 3)}
            f.write(json.dumps(rec) + "\n")
            lines += 1
    return lines
