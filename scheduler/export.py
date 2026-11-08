"""Export a simulation run as NDJSON for the frontend (schema in scheduler/schema/events.schema.json, v0.2.0).

Everything the 3D room shows comes from here. The frontend must not compute scheduling decisions or measurements:
  - events (arrive/start/finish/preempt/fail/repair) are the simulator's own log
  - board utilisation/status are rebuilt from that log
  - temperature/power are the thermal PROXY (scheduler/thermal.py), labelled as such
  - forecasts are projections from running jobs' *hinted* finish times and queued demand, with their own measured skill
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from .data import UNIT, Cluster, Workload, load_assumptions
from .display import Display
from .thermal import ThermalProxy, NO_POWER_POOLS
from .forecast import SurvivalCurves
from .sim import (State, EV_ARRIVE, EV_START, EV_FINISH, EV_PREEMPT, EV_FAIL, EV_REPAIR, EV_NODEEVICT,
                  SC_NEV, SC_NSNAP, SC_ERR, SC_FAILEV)

SCHEMA_VERSION = "0.2.0"
FORECAST_H = 1800.0
STATUS = ("idle", "running", "cooling", "failed")


def _slots(mask: int) -> list[int]:
    return [k for k in range(8) if (mask >> k) & 1]


def export_ndjson(path, S: State, w: Workload, cluster: Cluster, *, policy_name: str, realistic: bool,
                  preempt: bool, resume: bool, window_len_s: float | None = None, extra_meta: dict | None = None,
                  display: Display | None = None, thermal: ThermalProxy | None = None,
                  hint_est: np.ndarray | None = None, scenario: dict | None = None,
                  survival: SurvivalCurves | None = None) -> int:
    assert S.sc[SC_NEV] > 0, "simulate(..., log_events=True) required"
    display = display or Display()
    thermal = thermal or ThermalProxy.load()
    scenario = scenario or {}
    pool_ids = [p["id"] for p in cluster.pools]
    P = len(pool_ids)
    pool_start = S.pool_start
    N = len(w)
    nb = display.n_boards
    bon = display.board_of_nodes(cluster)                      # board per global node
    cap_b = np.bincount(bon[bon >= 0], weights=cluster.node_ngpu[bon >= 0], minlength=nb)
    nodes_b = np.bincount(bon[bon >= 0], minlength=nb)
    pool_of_board = np.array([pool_ids.index(display.pool_of_board(b)) for b in range(nb)])
    no_power = np.array([display.pool_of_board(b) in NO_POWER_POOLS for b in range(nb)])
    cap_pool = S.pool_cap.astype(float) / UNIT
    tmax = float(window_len_s) if window_len_s is not None else float("inf")

    g = S.req.astype(float) / UNIT
    elapsed0 = np.zeros(N) if w.elapsed0 is None else np.asarray(w.elapsed0, dtype=float)

    cf = scenario.get("cooling_fault") or None

    def delta_at(t: float) -> float:
        if not cf:
            return 0.0
        a = float(cf["at_h"]) * 3600.0
        b = a + float(cf["duration_h"]) * 3600.0 if cf.get("duration_h") is not None else np.inf
        return float(cf.get("delta_c", 35.0)) if a <= t < b else 0.0

    # ---- chronological merge of events and snapshots
    n_ev = int(S.sc[SC_NEV])
    n_snap = int(S.sc[SC_NSNAP])
    items = [(float(S.ev_t[i]), 1, 0, i) for i in range(n_ev) if S.ev_t[i] <= tmax]
    items += [(float(S.snap_t[i]), 0, 1, i) for i in range(n_snap - 1) if S.snap_t[i] <= tmax and S.snap_t[i] > 0]
    items.sort(key=lambda x: (x[0], x[1], x[3] if x[2] == 0 else -1))

    # ---- replay state
    running = np.zeros(N, bool)
    queued = np.zeros(N, bool)
    arr_t = np.full(N, -np.inf)                                # arrival time per job (for the recent-inflow term)
    start_t = np.zeros(N)
    jb = np.full(N, -1, dtype=np.int64)
    rem = S.dur.astype(float).copy()                          # remaining service per job
    attempts = np.zeros(N, dtype=np.int64)
    down = np.zeros(nb, dtype=np.int64)
    down_gpus = np.zeros(nb)                                   # GPUs on failed nodes, exact (node shapes differ)
    done_pool = np.zeros(P, dtype=np.int64)
    arr_pool = np.zeros(P, dtype=np.int64)
    temp = None
    prev_t = None
    prev_alert = np.zeros(nb, bool)
    snaps = []                                                 # (t, util_pct, pred_util_pct) for forecast skill
    out_lines: list[str] = []

    def board_state(t):
        r = np.flatnonzero(running)
        bj = jb[r]
        sel = bj >= 0
        busy = np.bincount(bj[sel], weights=g[r][sel], minlength=nb)
        nrun = np.bincount(bj[sel], minlength=nb)
        return r, busy, nrun

    for t, _, kind, i in items:
        if kind == 1:                                          # ---------------------------------- snapshot
            r, busy, nrun = board_state(t)
            util = np.where(cap_b > 0, 100.0 * busy / np.maximum(cap_b, 1e-9), 0.0)
            dt = (t - prev_t) if prev_t is not None else 0.0
            dlt = delta_at(t)
            tgt50, tgt95, pw = thermal.target(util)
            if temp is None:
                temp = tgt50 + dlt
            else:
                temp = temp + (tgt50 + dlt - temp) * (1.0 - np.exp(-dt / thermal.tau_s))
            failed = (down >= nodes_b) & (nodes_b > 0)
            alert = temp >= thermal.threshold_c
            # idle boards still above their own thermal target are 'cooling' (derived from the proxy, not a measurement)
            status = np.where(failed, 3, np.where(busy > 0, 1, np.where(temp > tgt50 + dlt + 3.0, 2, 0)))
            # forecast: expected survivors (Kaplan-Meier conditional survival) plus queued demand that can start
            if survival is not None:
                el = (t - start_t[r]) + np.where(attempts[r] == 1, elapsed0[r], 0.0)
                ps = survival.cond_survival(S.pool[r], el, FORECAST_H)
            else:
                ps = np.ones(len(r))                               # no history: assume running jobs persist
            sb = jb[r]
            ok = sb >= 0
            surv_b = np.bincount(sb[ok], weights=(g[r] * ps)[ok], minlength=nb)
            surv_p = np.bincount(S.pool[r], weights=g[r] * ps, minlength=P)
            qv = np.flatnonzero(queued)
            recent = np.flatnonzero((arr_t > t - FORECAST_H) & (arr_t <= t))
            inflow_p = np.bincount(S.pool[recent], weights=g[recent], minlength=P)   # GPU-demand that arrived in the last horizon
            q_p = np.bincount(S.pool[qv], weights=g[qv], minlength=P) + inflow_p
            live_cap_b = cap_b - down_gpus
            pred_b = surv_b.copy()
            for p in set(pool_of_board.tolist()):
                bs = np.flatnonzero(pool_of_board == p)
                extra = max(min(cap_pool[p] - surv_p[p], q_p[p]), 0.0)
                room = np.maximum(live_cap_b[bs] - surv_b[bs], 0.0)
                if room.sum() > 0:
                    pred_b[bs] += extra * room / room.sum()
            pred_b = np.minimum(pred_b, np.maximum(live_cap_b, 0.0))
            pred_util = np.where(cap_b > 0, 100.0 * pred_b / np.maximum(cap_b, 1e-9), 0.0)
            proj_util = pred_util                                   # survival projection: tested, NOT the displayed forecast
            pred_util = util.copy()                                 # displayed forecast: persistence (measured to be better)
            ptgt50, _, ppw = thermal.target(pred_util)
            pred_temp = temp + (ptgt50 + dlt - temp) * (1.0 - np.exp(-FORECAST_H / thermal.tau_s))
            snaps.append((t, util.copy(), proj_util.copy()))
            boards = []
            for b in range(nb):
                pw_b = None if no_power[b] else (0.0 if failed[b] else round(float(pw[b]), 0))
                fpw_b = None if no_power[b] else (0.0 if failed[b] else round(float(ppw[b]), 0))
                boards.append({"i": b, "util_pct": round(float(util[b]), 1), "temp_c": round(float(temp[b]), 1),
                               "power_w": pw_b, "running_jobs": int(nrun[b]), "nodes": int(nodes_b[b]),
                               "nodes_down": int(down[b]), "status": STATUS[int(status[b])], "alert": bool(alert[b]),
                               "forecast": {"util_pct": round(float(pred_util[b]), 1), "temp_c": round(float(pred_temp[b]), 1),
                                            "power_w": fpw_b, "projection_util_pct": round(float(proj_util[b]), 1)}})
            pools = {}
            for p, pid in enumerate(pool_ids):
                heads = []
                for h in range(S.snap_qhead.shape[2]):
                    jj = int(S.snap_qhead[i, p, h])
                    if jj >= 0:
                        heads.append({"job": str(w.job_id[jj]), "priority": "hp" if S.prio[jj] == 0 else "spot",
                                      "gpus": float(g[jj])})
                pools[pid] = {"busy_gpus": round(float(S.snap_busy[i, p]) / UNIT, 2), "capacity_gpus": float(cap_pool[p]),
                              "queue_hp": int(S.snap_qhp[i, p]), "queue_spot": int(S.snap_qsp[i, p]),
                              "running_jobs": int(S.snap_run[i, p]), "max_free_gpus_on_one_node": int(S.snap_maxfull[i, p]),
                              "queue_head": heads, "completed": int(done_pool[p]), "arrived": int(arr_pool[p])}
            out_lines.append(json.dumps({"type": "snapshot", "t": round(t, 3), "pools": pools, "boards": boards,
                                         "cooling_fault_delta_c": dlt}))
            new_alert = alert & ~prev_alert
            cleared = ~alert & prev_alert
            for b in np.flatnonzero(new_alert | cleared):
                out_lines.append(json.dumps({"type": "thermal_alert", "t": round(t, 3), "board": int(b),
                                             "pool": display.pool_of_board(int(b)), "state": "on" if alert[b] else "off",
                                             "temp_c": round(float(temp[b]), 1), "threshold_c": thermal.threshold_c,
                                             "evidence": "proxy"}))
            prev_alert = alert
            prev_t = t
            continue

        typ, j = int(S.ev_type[i]), int(S.ev_job[i])
        node = int(S.ev_node[i])
        board = int(bon[node]) if node >= 0 else -1
        pid = pool_ids[int(S.pool[j])] if j >= 0 else (pool_ids[int(cluster.node_pool[node])] if node >= 0 else None)
        local_node = int(node - pool_start[cluster.node_pool[node]]) if node >= 0 else None
        base = {"t": round(t, 3), "pool": pid}
        warm = bool(t <= 0.0)
        if typ == EV_ARRIVE:
            queued[j] = True
            arr_t[j] = t if t > 0 else -np.inf                  # warm-start arrivals are not 'recent demand'
            arr_pool[S.pool[j]] += 1
            rec = {"type": "arrive", **base, "job": str(w.job_id[j]), "gpus": float(g[j]),
                   "priority": "hp" if S.prio[j] == 0 else "spot", "duration_s": float(S.dur[j]),
                   "carryover": bool(not w.eval_mask[j]), "warm": warm, "evidence": "observed"}
        elif typ == EV_START:
            queued[j] = False
            running[j] = True
            start_t[j] = t
            jb[j] = board
            attempts[j] += 1
            on_cloud = bool(node >= 0 and cluster.cloud_mask()[node])
            rec = {"type": "start", **base, "job": str(w.job_id[j]), "node": local_node, "board": board if board >= 0 else None, "cloud": on_cloud,
                   "gpu_slots": _slots(int(S.ev_mask[i])), "attempt": int(attempts[j]), "service_s": float(rem[j]),
                   "gpus": float(g[j]), "priority": "hp" if S.prio[j] == 0 else "spot", "warm": warm}
        elif typ == EV_FINISH:
            running[j] = False
            done_pool[S.pool[j]] += 1
            rec = {"type": "finish", **base, "job": str(w.job_id[j]), "node": local_node,
                   "board": board if board >= 0 else None, "wait_s": None}
            rec["wait_s"] = round(float(S.start_first[j] - S.submit[j]), 3)
        elif typ in (EV_PREEMPT, EV_NODEEVICT):
            running[j] = False
            queued[j] = True
            lost = 0.0 if resume else (t - start_t[j]) * float(g[j])
            rem[j] = max(rem[j] - (t - start_t[j]), 1.0) if resume else float(S.dur[j])
            rec = {"type": "preempt", **base, "job": str(w.job_id[j]), "node": local_node,
                   "board": board if board >= 0 else None, "gpu_slots": _slots(int(S.ev_mask[i])),
                   "work_lost_gpu_s": round(lost, 3),
                   "cause": "node_failure" if typ == EV_NODEEVICT else "priority_preemption"}
        elif typ == EV_FAIL:
            if board >= 0:
                down[board] += 1
                down_gpus[board] += float(cluster.node_ngpu[node])
            rec = {"type": "fail", **base, "node": local_node, "board": board if board >= 0 else None,
                   "evidence": "scenario"}
        elif typ == EV_REPAIR:
            if board >= 0:
                down[board] -= 1
                down_gpus[board] -= float(cluster.node_ngpu[node])
            rec = {"type": "repair", **base, "node": local_node, "board": board if board >= 0 else None,
                   "evidence": "scenario"}
        else:
            continue
        out_lines.append(json.dumps(rec))

    # ---- forecast skill: predicted board utilisation vs what happened FORECAST_H later (and vs persistence)
    ts = np.array([s[0] for s in snaps])
    errs, pers = [], []
    for k, (t, u, pu) in enumerate(snaps):
        kk = int(np.searchsorted(ts, t + FORECAST_H))
        if kk < len(snaps) and abs(ts[kk] - (t + FORECAST_H)) <= max(FORECAST_H * 0.1, 120.0):
            actual = snaps[kk][1]
            errs.append(np.abs(pu - actual).mean())
            pers.append(np.abs(u - actual).mean())
    mae_proj = float(np.mean(errs)) if errs else None
    mae_pers = float(np.mean(pers)) if pers else None
    skill = {"horizon_s": FORECAST_H, "pairs": len(errs), "chosen": "persistence",
             "mae_util_pct_points": mae_pers, "persistence_mae_util_pct_points": mae_pers,
             "projection_mae_util_pct_points": mae_proj,
             "projection_beats_persistence": bool(mae_proj is not None and mae_pers is not None and mae_proj < mae_pers),
             "method": "utilisation: persistence (current value held). temperature/power: thermal-proxy lag toward that load, at the current cooling state. "
                       "A Kaplan-Meier survival projection of running jobs + queued/recent demand was also measured and is reported as projection_util_pct; "
                       "it did not beat persistence at this horizon.",
             "evidence": "calculated_projection"}

    meta = {
        "type": "meta", "schema_version": SCHEMA_VERSION, "time_unit": "seconds_since_window_start",
        "window": {"start_trace_s": float(w.t0), "length_s": window_len_s, "jobs": int(N),
                   "carryover_jobs": int((~w.eval_mask).sum())},
        "policy": {"name": policy_name, "realistic": realistic, "preempt": preempt,
                   "preempted_work": "resume" if resume else "restart_from_scratch"},
        "pools": [{"id": p["id"], "label": p["label"], "gpu_model_identifier": p["gpu_model_identifier"],
                   "identity": p["identity"], "capacity_gpus": float(cluster.capacity_gpus()[i]),
                   "node_count": int(cluster.node_counts()[i]),
                   "nodes": [int(x) for x, c in zip(cluster.node_ngpu[pool_start[i]:pool_start[i + 1]], cluster.cloud_mask()[pool_start[i]:pool_start[i + 1]]) if not c],
                   "cloud_nodes": int(cluster.cloud_mask()[pool_start[i]:pool_start[i + 1]].sum()),
                   "scale_vs_observed": float(cluster.scale[i])} for i, p in enumerate(cluster.pools)],
        "display": display.describe(cluster),
        "thermal": thermal.meta(),
        "forecast": skill,
        "assumptions": load_assumptions()["items"],
        "evidence_labels": {"observed": "from the Alibaba trace", "calculated": "derived arithmetic",
                            "assumption": "modelling choice, not data", "proxy": "stand-in from different measured hardware",
                            "scenario": "injected by the what-if scenario"},
        "notes": ["Waits, starts, evictions and node placement are simulated, not observed.",
                  "Temperature and power are a proxy from measured H100 profiles, not Alibaba measurements.",
                  "Queue order is the policy's ordering key; rl_ppo picks among candidates so its list is arrival order."],
        "failure_evictions": int(S.sc[SC_FAILEV]),
        "error_flags": int(S.sc[SC_ERR])}
    if extra_meta:
        meta.update(extra_meta)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(json.dumps(meta) + "\n")
        for line in out_lines:
            f.write(line + "\n")
    return len(out_lines) + 1
