"""Node-level event-driven GPU cluster simulator (numba).

State is a namedtuple of numpy arrays so the same core can be driven by built-in policies
(`run_sim`) and, later, by an RL environment stepping through decisions.

Capacity unit: hundredths of a GPU (UNIT = 100). A request >= UNIT needs that many *whole, free*
GPUs on a single node. A request < UNIT shares one GPU with other fractional jobs.
"""
from __future__ import annotations
from collections import namedtuple
import numpy as np
from numba import njit

from .data import UNIT, MAX_GPUS_PER_NODE, Cluster, Workload

# policies
FIFO, PRIO_FIFO, BACKFILL, SJF = 0, 1, 2, 3
POLICY_NAMES = {FIFO: "fifo", PRIO_FIFO: "priority_fifo", BACKFILL: "backfill", SJF: "sjf_oracle"}

# job status
NOT_ARRIVED, QUEUED, RUNNING, DONE = 0, 1, 2, 3
# event types in the log
EV_ARRIVE, EV_START, EV_FINISH, EV_PREEMPT, EV_FAIL, EV_REPAIR, EV_NODEEVICT = 0, 1, 2, 3, 4, 5, 6
EV_NAMES = ["arrive", "start", "finish", "preempt", "fail", "repair", "evict_failure"]

# scalar slots (int64 array `sc`)
SC_NRUN, SC_HEAP, SC_NEXT, SC_NEV, SC_NSNAP, SC_ERR, SC_PREEMPT, SC_RESUME, SC_POLICY, SC_DONE, \
    SC_LOG, SC_SNAP, SC_DEPTH, SC_NPREEMPT, SC_EARLY, SC_FOCUS, SC_FAILIDX, SC_NFAIL, SC_FAILEV = range(19)
# float slots (`fc`)
FC_NOW, FC_SNAPDT, FC_NEXTSNAP, FC_QINT, FC_CLOUDCOST, FC_CLOUDGPUH, FC_CLOUDJOBS, FC_OVFWAIT, FC_OVFBUDGET, FC_UTILCAP, FC_FAULT_A, FC_FAULT_B, FC_OFFMIN = range(13)

ERR_HEAP, ERR_STUCK, ERR_EVLOG = 1, 2, 4

FIELDS = [
    # jobs
    "submit", "dur", "pool", "req", "prio", "est", "key",
    "start_first", "finish", "remaining", "run_start", "token", "npre", "job_node", "job_mask",
    "status", "wasted",
    # nodes
    "node_pool", "node_ngpu", "gfree", "node_full", "node_maxfree", "pool_start",
    # pools
    "pool_busy", "pool_cap", "util_int", "qc", "queue", "qprio", "rl", "rlc", "rpos", "spotrun", "pver",
    "res_head", "res_ver", "res_node", "res_time",
    # heap
    "ht", "hj", "htok",
    # scratch
    "spot_use", "scr_flag", "scr_nodes", "scr_g",
    # event log
    "ev_t", "ev_type", "ev_job", "ev_node", "ev_mask",
    # snapshots
    "snap_t", "snap_busy", "snap_qhp", "snap_qsp", "snap_run", "snap_maxfull",
    # scalars
    # simulated cloud overflow (takeaway): node flags, per-job flag, USD per GPU-hour per pool
    "node_cloud", "job_cloud", "price_pool", "ovf_est",
    # node failures (scheduled by the scenario) and queue heads for the frontend feed
    "node_down", "fail_t", "fail_node", "fail_kind", "snap_qhead",
    # RL decision interface
    "cand_job", "cand_pos", "obs", "amask",
    "sc", "fc",
]
State = namedtuple("State", FIELDS)


# ----------------------------------------------------------------------------- helpers
@njit(cache=True)
def popcount(m):
    c = 0
    while m:
        c += m & 1
        m >>= 1
    return c


@njit(cache=True)
def unit_of(req):
    return UNIT if req >= UNIT else req


@njit(cache=True)
def recompute_node(S, n):
    full = 0
    mx = 0
    for k in range(S.node_ngpu[n]):
        f = S.gfree[n, k]
        if f == UNIT:
            full += 1
        if f > mx:
            mx = f
    S.node_full[n] = full
    S.node_maxfree[n] = mx


# ----------------------------------------------------------------------------- heap
@njit(cache=True)
def heap_push(S, t, j, tok):
    i = S.sc[SC_HEAP]
    if i >= S.ht.shape[0]:
        S.sc[SC_ERR] |= ERR_HEAP
        return
    S.sc[SC_HEAP] = i + 1
    while i > 0:
        par = (i - 1) // 2
        if S.ht[par] <= t:
            break
        S.ht[i] = S.ht[par]
        S.hj[i] = S.hj[par]
        S.htok[i] = S.htok[par]
        i = par
    S.ht[i] = t
    S.hj[i] = j
    S.htok[i] = tok


@njit(cache=True)
def heap_pop(S):
    n = S.sc[SC_HEAP] - 1
    S.sc[SC_HEAP] = n
    t = S.ht[n]
    j = S.hj[n]
    tok = S.htok[n]
    i = 0
    while True:
        c = 2 * i + 1
        if c >= n:
            break
        if c + 1 < n and S.ht[c + 1] < S.ht[c]:
            c += 1
        if S.ht[c] >= t:
            break
        S.ht[i] = S.ht[c]
        S.hj[i] = S.hj[c]
        S.htok[i] = S.htok[c]
        i = c
    if n > 0:
        S.ht[i] = t
        S.hj[i] = j
        S.htok[i] = tok


# ----------------------------------------------------------------------------- queue
@njit(cache=True)
def q_insert(S, p, j):
    qc = S.qc[p]
    key = S.key[j]
    lo = 0
    hi = qc
    while lo < hi:
        mid = (lo + hi) // 2
        if S.key[S.queue[p, mid]] <= key:
            lo = mid + 1
        else:
            hi = mid
    for i in range(qc, lo, -1):
        S.queue[p, i] = S.queue[p, i - 1]
    S.queue[p, lo] = j
    S.qc[p] = qc + 1
    S.qprio[p, S.prio[j]] += 1


@njit(cache=True)
def q_remove(S, p, i):
    j = S.queue[p, i]
    qc = S.qc[p]
    for k in range(i, qc - 1):
        S.queue[p, k] = S.queue[p, k + 1]
    S.qc[p] = qc - 1
    S.qprio[p, S.prio[j]] -= 1


# ----------------------------------------------------------------------------- log
@njit(cache=True)
def log_event(S, t, typ, j, node, mask):
    if S.sc[SC_LOG] == 0:
        return
    i = S.sc[SC_NEV]
    if i >= S.ev_t.shape[0]:
        S.sc[SC_ERR] |= ERR_EVLOG
        S.sc[SC_LOG] = 0
        return
    S.ev_t[i] = t
    S.ev_type[i] = typ
    S.ev_job[i] = j
    S.ev_node[i] = node
    S.ev_mask[i] = mask
    S.sc[SC_NEV] = i + 1


# ----------------------------------------------------------------------------- placement
@njit(cache=True)
def cap_now(S):
    """Thermal derating: while the scenario's cooling fault is active, a node may not be pushed past UTILCAP of its GPUs."""
    c = S.fc[FC_UTILCAP]
    if c < 1.0:
        t = S.fc[FC_NOW]
        if t >= S.fc[FC_FAULT_A] and t < S.fc[FC_FAULT_B]:
            return c
    return 1.0


@njit(cache=True)
def over_cap(S, n, req, cap):
    busy = 0
    for k in range(S.node_ngpu[n]):
        busy += UNIT - S.gfree[n, k]
    return busy + req > cap * S.node_ngpu[n] * UNIT


@njit(cache=True)
def find_place(S, p, req, excl):
    """Best-fit placement in pool p, skipping node `excl`. Returns (node, gpu_mask) or (-1, 0)."""
    n0 = S.pool_start[p]
    n1 = S.pool_start[p + 1]
    best = -1
    bestscore = 1 << 60
    cap = cap_now(S)
    if req >= UNIT:
        g = req // UNIT
        for n in range(n0, n1):
            if n == excl or S.node_cloud[n] == 1:
                continue
            if cap < 1.0 and over_cap(S, n, req, cap):
                continue
            f = S.node_full[n]
            if f >= g and f < bestscore:
                bestscore = f
                best = n
                if f == g:
                    break
        if best < 0:
            return -1, 0
        mask = 0
        c = 0
        for k in range(S.node_ngpu[best]):
            if S.gfree[best, k] == UNIT and c < g:
                mask |= 1 << k
                c += 1
        return best, mask
    bestk = -1
    for n in range(n0, n1):
        if n == excl or S.node_cloud[n] == 1 or S.node_maxfree[n] < req:
            continue
        if cap < 1.0 and over_cap(S, n, req, cap):
            continue
        for k in range(S.node_ngpu[n]):
            gf = S.gfree[n, k]
            if gf >= req and gf - req < bestscore:
                bestscore = gf - req
                best = n
                bestk = k
        if bestscore == 0:
            break
    if best < 0:
        return -1, 0
    return best, 1 << bestk


@njit(cache=True)
def find_cloud(S, p, req):
    """Best-fit placement on the SIMULATED cloud nodes of pool p. Returns (node, gpu_mask) or (-1, 0)."""
    best = -1
    bestscore = 1 << 60
    bestk = -1
    for n in range(S.pool_start[p], S.pool_start[p + 1]):
        if S.node_cloud[n] == 0:
            continue
        if req >= UNIT:
            g = req // UNIT
            f = S.node_full[n]
            if f >= g and f < bestscore:
                bestscore = f
                best = n
        else:
            if S.node_maxfree[n] < req:
                continue
            for k in range(S.node_ngpu[n]):
                gf = S.gfree[n, k]
                if gf >= req and gf - req < bestscore:
                    bestscore = gf - req
                    best = n
                    bestk = k
    if best < 0:
        return -1, 0
    if req >= UNIT:
        g = req // UNIT
        mask = 0
        c = 0
        for k in range(S.node_ngpu[best]):
            if S.gfree[best, k] == UNIT and c < g:
                mask |= 1 << k
                c += 1
        return best, mask
    return best, 1 << bestk


@njit(cache=True)
def start_on_cloud(S, j, n, mask, t):
    """Run job j on a simulated cloud node and charge its cost (service time x GPUs x pool price)."""
    start_job(S, j, n, mask, t)
    S.job_cloud[j] = 1
    gpuh = S.remaining[j] / 3600.0 * (S.req[j] / UNIT)
    S.fc[FC_CLOUDGPUH] += gpuh
    S.fc[FC_CLOUDCOST] += gpuh * S.price_pool[S.pool[j]]
    S.fc[FC_CLOUDJOBS] += 1.0


@njit(cache=True)
def overflow_pass(S, p, t):
    """Rule-based overflow: queued jobs that have waited >= the configured threshold are offloaded to the simulated cloud
    while it has capacity. A fallback, not a measured behaviour; it does not use the policy's runtime hint."""
    thr = S.fc[FC_OVFWAIT]
    depth = S.sc[SC_DEPTH]
    i = 0
    while i < S.qc[p] and i < depth * 4:
        j = S.queue[p, i]
        if S.submit[j] < 0.0 or t - S.submit[j] >= thr:
            budget = S.fc[FC_OVFBUDGET]
            if budget > 0.0 and S.ovf_est[j] / 3600.0 * (S.req[j] / UNIT) * S.price_pool[p] > budget:
                i += 1                      # predicted rental cost exceeds the per-job budget: keep waiting for owned capacity
                continue
            n, mask = find_cloud(S, p, S.req[j])
            if n >= 0:
                q_remove(S, p, i)
                start_on_cloud(S, j, n, mask, t)
                continue
        i += 1


@njit(cache=True)
def place_on_node(S, n, req):
    """Placement restricted to a single node."""
    cap = cap_now(S)
    if cap < 1.0 and over_cap(S, n, req, cap):
        return 0
    if req >= UNIT:
        g = req // UNIT
        if S.node_full[n] < g:
            return 0
        mask = 0
        c = 0
        for k in range(S.node_ngpu[n]):
            if S.gfree[n, k] == UNIT and c < g:
                mask |= 1 << k
                c += 1
        return mask
    bestk = -1
    bestleft = 1 << 60
    for k in range(S.node_ngpu[n]):
        gf = S.gfree[n, k]
        if gf >= req and gf - req < bestleft:
            bestleft = gf - req
            bestk = k
    if bestk < 0:
        return 0
    return 1 << bestk


@njit(cache=True)
def start_job(S, j, n, mask, t):
    p = S.pool[j]
    req = S.req[j]
    u = unit_of(req)
    for k in range(MAX_GPUS_PER_NODE):
        if (mask >> k) & 1:
            S.gfree[n, k] -= u
    recompute_node(S, n)
    if S.node_cloud[n] == 0:
        S.pool_busy[p] += req
    S.job_node[j] = n
    S.job_mask[j] = mask
    S.status[j] = RUNNING
    S.run_start[j] = t
    S.token[j] += 1
    if S.start_first[j] < 0:
        S.start_first[j] = t
    # running list
    S.rl[p, S.rlc[p]] = j
    S.rpos[j] = S.rlc[p]
    S.rlc[p] += 1
    S.sc[SC_NRUN] += 1
    if S.prio[j] == 1:
        S.spotrun[p] += 1
    S.pver[p] += 1
    heap_push(S, t + S.remaining[j], j, S.token[j])
    log_event(S, t, EV_START, j, n, mask)


@njit(cache=True)
def release_job(S, j):
    p = S.pool[j]
    n = S.job_node[j]
    mask = S.job_mask[j]
    u = unit_of(S.req[j])
    for k in range(MAX_GPUS_PER_NODE):
        if (mask >> k) & 1:
            S.gfree[n, k] += u
    recompute_node(S, n)
    if S.node_cloud[n] == 0:
        S.pool_busy[p] -= S.req[j]
    pos = S.rpos[j]
    last = S.rl[p, S.rlc[p] - 1]
    S.rl[p, pos] = last
    S.rpos[last] = pos
    S.rlc[p] -= 1
    S.sc[SC_NRUN] -= 1
    if S.prio[j] == 1:
        S.spotrun[p] -= 1
    S.pver[p] += 1


@njit(cache=True)
def evict_job(S, j, t, cause):
    elapsed = t - S.run_start[j]
    S.token[j] += 1  # invalidates the pending finish event
    release_job(S, j)
    if S.sc[SC_RESUME] == 1:
        S.remaining[j] = max(S.remaining[j] - elapsed, 1.0)
    else:
        S.wasted[j] += elapsed * S.req[j] / UNIT
        S.remaining[j] = S.dur[j]
    S.npre[j] += 1
    if cause == 1:
        S.sc[SC_FAILEV] += 1
    else:
        S.sc[SC_NPREEMPT] += 1
    S.status[j] = QUEUED
    log_event(S, t, EV_NODEEVICT if cause == 1 else EV_PREEMPT, j, S.job_node[j], S.job_mask[j])
    q_insert(S, S.pool[j], j)


# ----------------------------------------------------------------------------- preemption
@njit(cache=True)
def try_preempt(S, p, j, t):
    """Evict running spot jobs on one node so HP job j fits. Returns True if anything was evicted."""
    req = S.req[j]
    cnt = 0
    for idx in range(S.rlc[p]):
        jj = S.rl[p, idx]
        if S.prio[jj] == 1 and S.node_cloud[S.job_node[jj]] == 0:
            n = S.job_node[jj]
            u = unit_of(S.req[jj])
            for k in range(MAX_GPUS_PER_NODE):
                if (S.job_mask[jj] >> k) & 1:
                    S.spot_use[n, k] += u
            if S.scr_flag[n] == 0:
                S.scr_flag[n] = 1
                S.scr_nodes[cnt] = n
                cnt += 1
    if cnt == 0:
        return False
    best = -1
    bestcost = 1 << 60
    bestk = -1
    g = req // UNIT
    for ci in range(cnt):
        n = S.scr_nodes[ci]
        if req >= UNIT:
            vals = np.empty(MAX_GPUS_PER_NODE, dtype=np.int64)
            c = 0
            for k in range(S.node_ngpu[n]):
                if S.gfree[n, k] + S.spot_use[n, k] == UNIT:  # no HP load on this GPU
                    vals[c] = S.spot_use[n, k]
                    c += 1
            if c < g:
                continue
            v = np.sort(vals[:c])
            cost = 0
            for q in range(g):
                cost += v[q]
            if cost < bestcost:
                bestcost = cost
                best = n
        else:
            for k in range(S.node_ngpu[n]):
                if S.gfree[n, k] + S.spot_use[n, k] >= req:
                    cost = max(req - S.gfree[n, k], 0)
                    if cost < bestcost:
                        bestcost = cost
                        best = n
                        bestk = k
    ok = False
    if best >= 0:
        victims = np.empty(S.rlc[p], dtype=np.int64)
        nv = 0
        if req >= UNIT:
            # choose the g clearable GPUs with least spot load
            chosen = 0
            used = np.zeros(MAX_GPUS_PER_NODE, dtype=np.bool_)
            for _ in range(g):
                bk = -1
                bv = 1 << 60
                for k in range(S.node_ngpu[best]):
                    if (not used[k]) and S.gfree[best, k] + S.spot_use[best, k] == UNIT and S.spot_use[best, k] < bv:
                        bv = S.spot_use[best, k]
                        bk = k
                used[bk] = True
                chosen |= 1 << bk
            for idx in range(S.rlc[p]):
                jj = S.rl[p, idx]
                if S.job_node[jj] == best and S.prio[jj] == 1 and (S.job_mask[jj] & chosen) != 0:
                    victims[nv] = jj
                    nv += 1
        else:
            cand = np.empty(S.rlc[p], dtype=np.int64)
            nc = 0
            for idx in range(S.rlc[p]):
                jj = S.rl[p, idx]
                if S.job_node[jj] == best and S.prio[jj] == 1 and ((S.job_mask[jj] >> bestk) & 1):
                    cand[nc] = jj
                    nc += 1
            free = S.gfree[best, bestk]
            while free < req and nc > 0:
                yi = 0  # youngest first: least work lost
                for q in range(nc):
                    if S.run_start[cand[q]] > S.run_start[cand[yi]]:
                        yi = q
                jj = cand[yi]
                free += S.req[jj]
                victims[nv] = jj
                nv += 1
                cand[yi] = cand[nc - 1]
                nc -= 1
        for q in range(nv):
            evict_job(S, victims[q], t, 0)
        ok = nv > 0
    # cleanup scratch
    for ci in range(cnt):
        n = S.scr_nodes[ci]
        S.scr_flag[n] = 0
        for k in range(MAX_GPUS_PER_NODE):
            S.spot_use[n, k] = 0
    return ok


# ----------------------------------------------------------------------------- backfill reservation
@njit(cache=True)
def compute_reservation(S, p, head, t):
    """EASY-style reservation for the blocked head job using runtime *estimates*.
    Returns (node, shadow_time); (-1, inf) when no node is ever estimated to free enough."""
    if S.res_head[p] == head and S.res_ver[p] == S.pver[p]:
        return S.res_node[p], S.res_time[p]
    n0 = S.pool_start[p]
    n1 = S.pool_start[p + 1]
    for n in range(n0, n1):
        for k in range(MAX_GPUS_PER_NODE):
            S.scr_g[n, k] = S.gfree[n, k]
    nr = S.rlc[p]
    ee = np.empty(nr, dtype=np.float64)
    ids = np.empty(nr, dtype=np.int64)
    for idx in range(nr):
        jj = S.rl[p, idx]
        ids[idx] = jj
        el = t - S.run_start[jj]
        est_rem = S.est[jj] - (S.dur[jj] - S.remaining[jj]) - el
        ee[idx] = t + max(est_rem, 1.0)
    order = np.argsort(ee)
    req = S.req[head]
    g = req // UNIT
    rnode = -1
    rtime = np.inf
    for oi in range(nr):
        jj = ids[order[oi]]
        n = S.job_node[jj]
        if S.node_cloud[n] == 1:
            continue
        u = unit_of(S.req[jj])
        for k in range(MAX_GPUS_PER_NODE):
            if (S.job_mask[jj] >> k) & 1:
                S.scr_g[n, k] += u
        ok = False
        if req >= UNIT:
            c = 0
            for k in range(S.node_ngpu[n]):
                if S.scr_g[n, k] == UNIT:
                    c += 1
            ok = c >= g
        else:
            for k in range(S.node_ngpu[n]):
                if S.scr_g[n, k] >= req:
                    ok = True
                    break
        if ok:
            rnode = n
            rtime = ee[order[oi]]
            break
    S.res_head[p] = head
    S.res_ver[p] = S.pver[p]
    S.res_node[p] = rnode
    S.res_time[p] = rtime
    return rnode, rtime



# ----------------------------------------------------------------------------- node failures
@njit(cache=True)
def apply_failure_event(S, i, t):
    """Fail or repair one node (scheduled by the scenario). A failed node loses all running jobs, which restart
    from the queue (or resume, per SC_RESUME), and offers no capacity until repaired. Returns the node's pool."""
    n = S.fail_node[i]
    p = S.node_pool[n]
    if S.fail_kind[i] == 1:
        if S.node_down[n] == 0:
            victims = np.empty(S.rlc[p], dtype=np.int64)
            nv = 0
            for idx in range(S.rlc[p]):
                jj = S.rl[p, idx]
                if S.job_node[jj] == n:
                    victims[nv] = jj
                    nv += 1
            for q in range(nv):
                evict_job(S, victims[q], t, 1)
            S.node_down[n] = 1
            for k in range(MAX_GPUS_PER_NODE):
                S.gfree[n, k] = 0
            S.node_full[n] = 0
            S.node_maxfree[n] = 0
            S.pver[p] += 1
            log_event(S, t, EV_FAIL, -1, n, 0)
    else:
        if S.node_down[n] == 1:
            S.node_down[n] = 0
            for k in range(S.node_ngpu[n]):
                S.gfree[n, k] = UNIT
            recompute_node(S, n)
            S.pver[p] += 1
            log_event(S, t, EV_REPAIR, -1, n, 0)
    return p

# ----------------------------------------------------------------------------- scheduling pass
@njit(cache=True)
def schedule(S, p, t):
    pol = S.sc[SC_POLICY]
    preempt = S.sc[SC_PREEMPT] == 1 and pol != FIFO   # FIFO ignores priority: evicted spot jobs would re-queue ahead of the HP job (livelock)
    depth = S.sc[SC_DEPTH]
    if pol == FIFO or pol == PRIO_FIFO or pol == BACKFILL:
        while S.qc[p] > 0:
            j = S.queue[p, 0]
            n, mask = find_place(S, p, S.req[j], -1)
            if n >= 0:
                q_remove(S, p, 0)
                start_job(S, j, n, mask, t)
                continue
            if preempt and S.prio[j] == 0 and S.spotrun[p] > 0:
                if try_preempt(S, p, j, t):
                    continue
            break
        if pol == BACKFILL and S.qc[p] > 1:
            j0 = S.queue[p, 0]
            rnode, rtime = compute_reservation(S, p, j0, t)
            i = 1
            while i < S.qc[p] and i < depth:
                j = S.queue[p, i]
                n, mask = find_place(S, p, S.req[j], rnode)
                if n < 0 and rnode >= 0 and t + S.est[j] <= rtime:
                    m2 = place_on_node(S, rnode, S.req[j])
                    if m2 != 0:
                        n = rnode
                        mask = m2
                if n >= 0:
                    q_remove(S, p, i)
                    start_job(S, j, n, mask, t)
                    continue
                i += 1
    elif pol == SJF:
        tried = False
        i = 0
        while i < S.qc[p] and i < depth:
            j = S.queue[p, i]
            n, mask = find_place(S, p, S.req[j], -1)
            if n >= 0:
                q_remove(S, p, i)
                start_job(S, j, n, mask, t)
                continue
            if preempt and (not tried) and S.prio[j] == 0 and S.spotrun[p] > 0:
                tried = True
                if try_preempt(S, p, j, t):
                    continue
            i += 1
    if S.fc[FC_OVFWAIT] > 0.0:
        overflow_pass(S, p, t)


# ----------------------------------------------------------------------------- time advance + main loop
@njit(cache=True)
def snapshot(S, ts):
    i = S.sc[SC_NSNAP]
    if i >= S.snap_t.shape[0]:
        return
    S.snap_t[i] = ts
    P = S.qc.shape[0]
    for p in range(P):
        S.snap_busy[i, p] = S.pool_busy[p]
        S.snap_qhp[i, p] = S.qprio[p, 0]
        S.snap_qsp[i, p] = S.qprio[p, 1]
        S.snap_run[i, p] = S.rlc[p]
        mf = 0
        for n in range(S.pool_start[p], S.pool_start[p + 1]):
            if S.node_cloud[n] == 0 and S.node_full[n] > mf:
                mf = S.node_full[n]
        S.snap_maxfull[i, p] = mf
        for h in range(S.snap_qhead.shape[2]):
            S.snap_qhead[i, p, h] = S.queue[p, h] if h < S.qc[p] else -1
    S.sc[SC_NSNAP] = i + 1


@njit(cache=True)
def advance(S, t):
    now = S.fc[FC_NOW]
    if S.sc[SC_SNAP] == 1:
        while S.fc[FC_NEXTSNAP] <= t:
            snapshot(S, S.fc[FC_NEXTSNAP])
            S.fc[FC_NEXTSNAP] += S.fc[FC_SNAPDT]
    dt = t - now
    if dt > 0:
        q = 0.0
        for p in range(S.pool_busy.shape[0]):
            S.util_int[p] += S.pool_busy[p] * dt
            q += S.qprio[p, 0] + 0.3 * S.qprio[p, 1]
        S.fc[FC_QINT] += q * dt / 3600.0
    S.fc[FC_NOW] = t


@njit(cache=True)
def run_sim(S):
    N = S.submit.shape[0]
    while True:
        # drop stale finish events
        while S.sc[SC_HEAP] > 0 and (S.htok[0] != S.token[S.hj[0]] or S.status[S.hj[0]] != RUNNING):
            heap_pop(S)
        ta = np.inf
        if S.sc[SC_NEXT] < N:
            ta = S.submit[S.sc[SC_NEXT]]
        tf = np.inf
        if S.sc[SC_HEAP] > 0:
            tf = S.ht[0]
        tx = np.inf
        if S.sc[SC_FAILIDX] < S.sc[SC_NFAIL]:
            tx = S.fail_t[S.sc[SC_FAILIDX]]
        if ta == np.inf and tf == np.inf and tx == np.inf:
            break
        if tf <= ta and tf <= tx:
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
            schedule(S, p, tf)
        elif tx <= ta:
            advance(S, tx)
            p = apply_failure_event(S, S.sc[SC_FAILIDX], tx)
            S.sc[SC_FAILIDX] += 1
            schedule(S, p, tx)
        else:
            j = S.sc[SC_NEXT]
            S.sc[SC_NEXT] += 1
            advance(S, ta)
            S.status[j] = QUEUED
            log_event(S, ta, EV_ARRIVE, j, -1, 0)
            p = S.pool[j]
            q_insert(S, p, j)
            schedule(S, p, ta)
        if S.sc[SC_ERR] & ERR_HEAP:
            break
        if S.sc[SC_EARLY] == 1 and S.sc[SC_NEXT] >= N:
            empty = True
            for p in range(S.qc.shape[0]):
                if S.qc[p] > 0:
                    empty = False
            if empty:
                break   # every job has started; remaining finishes cannot change any wait
    for p in range(S.qc.shape[0]):
        if S.qc[p] > 0:
            S.sc[SC_ERR] |= ERR_STUCK
    if S.sc[SC_SNAP] == 1:
        snapshot(S, S.fc[FC_NOW])


# ----------------------------------------------------------------------------- python wrapper
def estimate_array(w: Workload, mode: str, sigma: float = 1.0, seed: int = 0,
                   train_end: float | None = None) -> np.ndarray:
    """Runtime estimates the *backfill* policy is allowed to use.
    oracle: true duration. noisy: true x lognormal(sigma). median: pool x priority median of earlier jobs."""
    if mode == "oracle":
        return w.dur.copy()
    if mode == "noisy":
        rng = np.random.default_rng(seed)
        return w.dur * np.exp(rng.normal(0.0, sigma, size=len(w)))
    if mode == "median":
        est = np.empty(len(w))
        ref = w.eval_mask.copy() if train_end is None else (w.eval_mask & (w.submit < train_end))
        for p in np.unique(w.pool):
            for pr in (0, 1):
                m = (w.pool == p) & (w.prio == pr)
                r = m & ref
                est[m] = np.median(w.dur[r]) if r.any() else np.median(w.dur[m]) if m.any() else 1.0
        return est
    raise ValueError(mode)


def build_state(cluster: Cluster, w: Workload, policy: int, *, preempt: bool = True, resume: bool = False,
                est: np.ndarray | None = None, depth: int = 128, log_events: bool = False, early_stop: bool = False,
                snapshot_dt: float | None = 3600.0, max_snapshots: int = 400000, rl_k: int = 8,
                failures: list | None = None, qhead: int = 5, cloud_price=None, overflow_wait_s: float = 0.0,
                max_job_cost_usd: float = 0.0, overflow_est=None, util_cap: float = 1.0, derate_from_s: float = 0.0,
                derate_to_s: float = float("inf"), rl_offload: bool = False, offload_min_wait_s: float = 0.0) -> State:
    N = len(w)
    P = cluster.n_pools
    M = len(cluster.node_pool)
    order = np.argsort(cluster.node_pool, kind="stable")
    assert (order == np.arange(M)).all(), "nodes must be sorted by pool"
    pool_start = np.zeros(P + 1, dtype=np.int64)
    pool_start[1:] = np.cumsum(np.bincount(cluster.node_pool, minlength=P))
    gfree = np.zeros((M, MAX_GPUS_PER_NODE), dtype=np.int64)
    for k in range(MAX_GPUS_PER_NODE):
        gfree[cluster.node_ngpu > k, k] = UNIT
    node_full = cluster.node_ngpu.astype(np.int64).copy()
    node_maxfree = np.full(M, UNIT, dtype=np.int64)
    own = ~cluster.cloud_mask()
    pool_cap = np.bincount(cluster.node_pool[own], weights=cluster.node_ngpu[own] * UNIT, minlength=P).astype(np.int64)   # own capacity only

    # queue ordering key (ascending). prio first for priority-aware policies.
    if policy == FIFO:
        key = w.submit.copy()
    elif policy == SJF:
        key = w.prio * 1e10 + (est if est is not None else w.dur)
    else:
        key = w.prio * 1e10 + w.submit
    if est is None:
        est = w.dur.copy()

    ev_cap = 8 * N + 1024 if log_events else 1
    snap_on = snapshot_dt is not None
    horizon = (w.submit.max() if N else 0.0) + (w.dur.max() if N else 0.0) * 1.0
    n_snap = int(min(max_snapshots, horizon / snapshot_dt + 4)) if snap_on else 1

    sc = np.zeros(24, dtype=np.int64)
    sc[SC_FOCUS] = -1
    fl = sorted(failures or [], key=lambda f: (f[0], f[2]))   # (t_s, global_node, kind 1=fail 2=repair)
    sc[SC_NFAIL] = len(fl)
    sc[SC_PREEMPT] = int(preempt and policy != FIFO)
    sc[SC_RESUME] = int(resume)
    sc[SC_POLICY] = policy
    sc[SC_LOG] = int(log_events)
    sc[SC_SNAP] = int(snap_on)
    sc[SC_DEPTH] = depth
    sc[SC_EARLY] = int(early_stop)
    fc = np.zeros(16)
    fc[FC_SNAPDT] = snapshot_dt if snap_on else 1.0
    fc[FC_NEXTSNAP] = 0.0
    fc[FC_OVFWAIT] = float(overflow_wait_s)
    fc[FC_OVFBUDGET] = float(max_job_cost_usd)
    fc[FC_UTILCAP], fc[FC_FAULT_A], fc[FC_FAULT_B] = float(util_cap), float(derate_from_s), float(derate_to_s)
    fc[FC_OFFMIN] = float(offload_min_wait_s)
    fc[FC_NOW] = float(w.submit.min()) if N else 0.0

    z = lambda shape, dt=np.int64: np.zeros(shape, dtype=dt)
    return State(
        submit=w.submit.astype(np.float64), dur=w.dur.astype(np.float64), pool=w.pool.astype(np.int64),
        req=w.req.astype(np.int64), prio=w.prio.astype(np.int64), est=est.astype(np.float64), key=key.astype(np.float64),
        start_first=np.full(N, -1.0), finish=np.full(N, -1.0), remaining=w.dur.astype(np.float64).copy(),
        run_start=z(N, np.float64), token=z(N), npre=z(N), job_node=np.full(N, -1, dtype=np.int64),
        job_mask=z(N), status=z(N), wasted=z(N, np.float64),
        node_pool=cluster.node_pool.astype(np.int64), node_ngpu=cluster.node_ngpu.astype(np.int64), gfree=gfree,
        node_full=node_full, node_maxfree=node_maxfree, pool_start=pool_start,
        pool_busy=z(P), pool_cap=pool_cap, util_int=z(P, np.float64), qc=z(P), queue=z((P, max(N, 1))),
        qprio=z((P, 2)), rl=z((P, max(N, 1))), rlc=z(P), rpos=z(N), spotrun=z(P), pver=z(P),
        res_head=np.full(P, -1, dtype=np.int64), res_ver=np.full(P, -1, dtype=np.int64),
        res_node=np.full(P, -1, dtype=np.int64), res_time=np.full(P, np.inf),
        ht=z(4 * N + 16, np.float64), hj=z(4 * N + 16), htok=z(4 * N + 16),
        spot_use=z((M, MAX_GPUS_PER_NODE)), scr_flag=z(M), scr_nodes=z(M), scr_g=z((M, MAX_GPUS_PER_NODE)),
        ev_t=z(ev_cap, np.float64), ev_type=z(ev_cap), ev_job=z(ev_cap), ev_node=z(ev_cap), ev_mask=z(ev_cap),
        snap_t=z(n_snap, np.float64), snap_busy=z((n_snap, P)), snap_qhp=z((n_snap, P)), snap_qsp=z((n_snap, P)),
        snap_run=z((n_snap, P)), snap_maxfull=z((n_snap, P)),
        node_cloud=cluster.cloud_mask().astype(np.int64), job_cloud=z(N), ovf_est=est.astype(np.float64) if overflow_est is None else np.asarray(overflow_est, dtype=np.float64),
        price_pool=np.zeros(P) if cloud_price is None else np.asarray(cloud_price, dtype=np.float64),
        node_down=z(M), fail_t=np.array([f[0] for f in fl] + [0.0], dtype=np.float64),
        fail_node=np.array([f[1] for f in fl] + [0], dtype=np.int64), fail_kind=np.array([f[2] for f in fl] + [0], dtype=np.int64),
        snap_qhead=np.full((n_snap, P, qhead), -1, dtype=np.int64),
        cand_job=np.full(rl_k, -1, dtype=np.int64), cand_pos=np.full(rl_k, -1, dtype=np.int64),
        obs=np.zeros(P + 6 + rl_k * 8 + (2 if rl_offload else 0), dtype=np.float32), amask=np.zeros(rl_k + (2 if rl_offload else 1), dtype=np.int64),
        sc=sc, fc=fc)


def simulate(cluster: Cluster, w: Workload, policy: int, **kw) -> State:
    S = build_state(cluster, w, policy, **kw)
    run_sim(S)
    return S
