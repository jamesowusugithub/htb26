"""Numba decision interface for the RL scheduler.

The agent acts at *decision points*: after an event in pool p it may start any of K candidate jobs from
that pool's queue (or advance). Candidates: the 2 oldest in priority/FIFO order (slots 0-1, shown even if
blocked), then up to K-2 *fitting* jobs with the smallest runtime hint among the first D queue entries.
HP-over-spot preemption stays rule-based (identical to the baselines): a blocked HP queue head evicts spot jobs.

obs = [pool one-hot (P), free_frac, max_free_block_frac, log qHP, log qSpot, spot_running_frac, hp_in_queue_flag]
      + K x [valid, fits, is_hp, log gpus, log wait_h, log hint, is_oldest, log queue pos]
"""
from __future__ import annotations
import numpy as np
from numba import njit

from .data import UNIT
from .sim import (State, schedule, try_preempt, find_place, start_job, q_remove, release_job, heap_pop, advance,
                  apply_failure_event, SC_FAILIDX, SC_NFAIL,
                  log_event, SC_HEAP, SC_NEXT, SC_DONE, SC_ERR, SC_FOCUS, SC_POLICY, SC_PREEMPT, SC_NRUN,
                  FC_NOW, FC_QINT, RUNNING, DONE, QUEUED, EV_ARRIVE, EV_FINISH, ERR_STUCK, PRIO_FIFO)
from .sim import q_insert, overflow_pass, FC_OVFWAIT, FC_OFFMIN, FC_OVFBUDGET, find_cloud, start_on_cloud

HINT_SCALE = 8.0


@njit(cache=True)
def _pool_blocks(S, p):
    maxfull = 0
    maxfree = 0
    maxgpu = 1
    for n in range(S.pool_start[p], S.pool_start[p + 1]):
        if S.node_cloud[n] == 1:
            continue
        if S.node_full[n] > maxfull:
            maxfull = S.node_full[n]
        if S.node_maxfree[n] > maxfree:
            maxfree = S.node_maxfree[n]
        if S.node_ngpu[n] > maxgpu:
            maxgpu = S.node_ngpu[n]
    return maxfull, maxfree, maxgpu


@njit(cache=True)
def _fits(req, maxfull, maxfree):
    if req >= UNIT:
        return (req // UNIT) <= maxfull
    return req <= maxfree


@njit(cache=True)
def _events_pending(S):
    while S.sc[SC_HEAP] > 0 and (S.htok[0] != S.token[S.hj[0]] or S.status[S.hj[0]] != RUNNING):
        heap_pop(S)
    return S.sc[SC_HEAP] > 0 or S.sc[SC_NEXT] < S.submit.shape[0] or S.sc[SC_FAILIDX] < S.sc[SC_NFAIL]


# added to a spot job's hint when ranking candidates, so the K slots fill with HP jobs first (1e12 s >> any real runtime). Set to 0.0 for the old behaviour.
HP_FIRST_PENALTY = 1e12


@njit(cache=True)
def build_decision(S, p, D):
    """Fill cand/obs/amask for pool p. Returns the number of startable candidates (after rule-based preemption)."""
    now = S.fc[FC_NOW]
    if S.fc[FC_OVFWAIT] > 0.0:          # simulated takeaway: over-waiting jobs go to the cloud (a rule layered on the policy, not a learned action)
        overflow_pass(S, p, now)
    # rule-based preemption: blocked HP head evicts spot (same rule as priority_fifo)
    while S.qc[p] > 0 and S.sc[SC_PREEMPT] == 1 and S.spotrun[p] > 0:
        j = S.queue[p, 0]
        if S.prio[j] != 0:
            break
        mf, mx, mg = _pool_blocks(S, p)
        if _fits(S.req[j], mf, mx):
            break
        if not try_preempt(S, p, j, now):
            break
        # make room AND start the HP head atomically (otherwise the agent could refill the freed space with
        # another job, re-block the head, and trigger endless evictions)
        n, mask = find_place(S, p, S.req[j], -1)
        if n >= 0:
            q_remove(S, p, 0)
            start_job(S, j, n, mask, now)
    K = S.cand_job.shape[0]
    P = S.qc.shape[0]
    maxfull, maxfree, maxgpu = _pool_blocks(S, p)
    qc = S.qc[p]
    lim = min(qc, D)
    for k in range(K):
        S.cand_job[k] = -1
        S.cand_pos[k] = -1
        S.amask[k] = 0
    S.amask[K] = 1 if _events_pending(S) else 0
    if S.amask.shape[0] == K + 2:
        S.amask[K + 1] = 0
    # slots 0-1: oldest in queue order
    for k in range(min(2, qc)):
        S.cand_pos[k] = k
        S.cand_job[k] = S.queue[p, k]
    # slots 2..K-1: smallest hint among fitting jobs
    for k in range(2, K):
        best = -1
        bestest = np.inf
        for pos in range(2, lim):
            j = S.queue[p, pos]
            if not _fits(S.req[j], maxfull, maxfree):
                continue
            taken = False
            for q in range(2, k):
                if S.cand_pos[q] == pos:
                    taken = True
            if taken:
                continue
            key = S.est[j] + (0.0 if S.prio[j] == 0 else HP_FIRST_PENALTY)   # HP candidates are offered before spot ones
            if key < bestest:
                bestest = key
                best = pos
        if best < 0:
            break
        S.cand_pos[k] = best
        S.cand_job[k] = S.queue[p, best]
    nvalid = 0
    for k in range(K):
        j = S.cand_job[k]
        if j >= 0 and _fits(S.req[j], maxfull, maxfree):
            S.amask[k] = 1
            nvalid += 1
    cost_feat = 0.0
    cloud_free = 0.0
    if S.amask.shape[0] == K + 2:                    # explicit 'send the queue head to the SIMULATED cloud' action
        capu = 0
        freeu = 0
        for n in range(S.pool_start[p], S.pool_start[p + 1]):
            if S.node_cloud[n] == 1:
                capu += S.node_ngpu[n] * UNIT
                for k in range(S.node_ngpu[n]):
                    freeu += S.gfree[n, k]
        if capu > 0:
            cloud_free = freeu / capu
        if qc > 0 and capu > 0:
            hj = S.queue[p, 0]
            cost_pred = S.ovf_est[hj] / 3600.0 * (S.req[hj] / UNIT) * S.price_pool[p]
            cost_feat = np.log1p(cost_pred) / 6.0
            ok = (now - S.submit[hj] >= S.fc[FC_OFFMIN]) and (S.fc[FC_OVFBUDGET] <= 0.0 or cost_pred <= S.fc[FC_OVFBUDGET])
            if ok:
                n2, m2 = find_cloud(S, p, S.req[hj])
                if n2 >= 0:
                    S.amask[K + 1] = 1
                    nvalid += 1
    # observation
    o = S.obs
    o[:] = 0.0
    o[p] = 1.0
    cap = max(S.pool_cap[p], 1)
    o[P + 0] = 1.0 - S.pool_busy[p] / cap
    o[P + 1] = maxfull / maxgpu
    o[P + 2] = np.log1p(S.qprio[p, 0]) / 8.0
    o[P + 3] = np.log1p(S.qprio[p, 1]) / 8.0
    o[P + 4] = S.spotrun[p] / max(S.rlc[p], 1)
    o[P + 5] = 1.0 if S.qprio[p, 0] > 0 else 0.0
    base = P + 6
    for k in range(K):
        j = S.cand_job[k]
        if j < 0:
            continue
        b = base + 8 * k
        o[b + 0] = 1.0
        o[b + 1] = 1.0 if _fits(S.req[j], maxfull, maxfree) else 0.0
        o[b + 2] = 1.0 if S.prio[j] == 0 else 0.0
        o[b + 3] = np.log1p(S.req[j] / UNIT) / 2.2
        o[b + 4] = np.log1p(max(now - S.submit[j], 0.0) / 3600.0) / 4.0
        o[b + 5] = np.log1p(S.est[j] / 60.0) / HINT_SCALE
        o[b + 6] = 1.0 if S.cand_pos[k] < 2 else 0.0
        o[b + 7] = np.log1p(S.cand_pos[k]) / 7.0
    if S.amask.shape[0] == K + 2:
        o[o.shape[0] - 2] = cloud_free
        o[o.shape[0] - 1] = cost_feat
    return nvalid


@njit(cache=True)
def _process_next_event(S):
    """Apply the next arrival/finish. Returns the pool to focus on, -1 for none, -2 when no events remain."""
    N = S.submit.shape[0]
    if not _events_pending(S):
        return -2
    ta = np.inf
    if S.sc[SC_NEXT] < N:
        ta = S.submit[S.sc[SC_NEXT]]
    tf = np.inf
    if S.sc[SC_HEAP] > 0:
        tf = S.ht[0]
    tx = np.inf
    if S.sc[SC_FAILIDX] < S.sc[SC_NFAIL]:
        tx = S.fail_t[S.sc[SC_FAILIDX]]
    if tx < tf and tx <= ta:
        advance(S, tx)
        p = apply_failure_event(S, S.sc[SC_FAILIDX], tx)
        S.sc[SC_FAILIDX] += 1
        return p
    if tf <= ta:
        j = S.hj[0]
        heap_pop(S)
        advance(S, tf)
        p = S.pool[j]
        release_job(S, j)
        S.status[j] = DONE
        S.finish[j] = tf
        S.remaining[j] = 0.0
        S.sc[SC_DONE] += 1
        log_event(S, tf, EV_FINISH, j, S.job_node[j], S.job_mask[j])
        return p
    j = S.sc[SC_NEXT]
    S.sc[SC_NEXT] += 1
    advance(S, ta)
    S.status[j] = QUEUED
    log_event(S, ta, EV_ARRIVE, j, -1, 0)
    p = S.pool[j]
    q_insert(S, p, j)
    if ta <= 0.0:                       # warm start: carry-over placed by the fixed priority rule
        schedule(S, p, ta)
        return -1
    return p


@njit(cache=True)
def run_until_decision(S, D):
    """Advance until some pool has a startable candidate. Returns 0 = decision ready, 1 = episode over."""
    N = S.submit.shape[0]
    while True:
        p = S.sc[SC_FOCUS]
        if p >= 0:
            if build_decision(S, p, D) > 0:
                return 0
            S.sc[SC_FOCUS] = -1
        if S.sc[SC_NEXT] >= N:
            empty = True
            for q in range(S.qc.shape[0]):
                if S.qc[q] > 0:
                    empty = False
            if empty:
                return 1
        r = _process_next_event(S)
        if r == -2:
            for q in range(S.qc.shape[0]):
                if S.qc[q] > 0:
                    S.sc[SC_ERR] |= ERR_STUCK
            return 1
        S.sc[SC_FOCUS] = r


@njit(cache=True)
def apply_action(S, a):
    """a in [0,K): start that candidate; a == K: advance (hold). Returns 1 if an invalid action was given."""
    K = S.cand_job.shape[0]
    p = S.sc[SC_FOCUS]
    if a < 0 or a >= S.amask.shape[0] or S.amask[a] == 0 or p < 0:
        return 1
    if a == K:
        S.sc[SC_FOCUS] = -1
        return 0
    if a == K + 1:                                   # offload the queue head to the simulated cloud (cost is charged by start_on_cloud)
        hj = S.queue[p, 0]
        n2, m2 = find_cloud(S, p, S.req[hj])
        if n2 < 0:
            return 1
        q_remove(S, p, 0)
        start_on_cloud(S, hj, n2, m2, S.fc[FC_NOW])
        return 0
    j = S.cand_job[a]
    n, mask = find_place(S, p, S.req[j], -1)
    if n < 0:
        return 1
    q_remove(S, p, S.cand_pos[a])
    start_job(S, j, n, mask, S.fc[FC_NOW])
    return 0
