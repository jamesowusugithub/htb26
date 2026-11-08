import numpy as np
import pytest
from scheduler.data import UNIT
from scheduler.sim import (simulate, FIFO, PRIO_FIFO, BACKFILL, SJF, EV_FAIL, EV_REPAIR, EV_NODEEVICT, EV_START,
                           EV_FINISH, EV_PREEMPT, SC_ERR, SC_FAILEV, SC_NEV, SC_DONE, DONE)
from tests.test_sim import cluster, workload

FAIL, REPAIR = 1, 2


def run(c, jobs, policy, failures, **kw):
    w = workload(jobs)
    S = simulate(c, w, policy, log_events=True, failures=failures, **kw)
    return S, w


def events(S, typ):
    return [(float(S.ev_t[i]), int(S.ev_job[i]), int(S.ev_node[i])) for i in range(int(S.sc[SC_NEV])) if S.ev_type[i] == typ]


def test_failure_evicts_running_job_and_it_restarts_elsewhere():
    # two 1-GPU nodes; job0 runs on node A until node A fails at t=30; node B is free so it restarts at once
    c = cluster(1, 1)
    S, _ = run(c, [(0, 100, 1, 0)], FIFO, [(30.0, 0, FAIL)])
    assert S.sc[SC_FAILEV] == 1 and S.npre[0] == 1
    assert S.finish[0] == 130.0                       # restart from scratch at t=30 on the other node
    assert S.wasted[0] == pytest.approx(30.0)
    assert [e[0] for e in events(S, EV_FAIL)] == [30.0]
    assert events(S, EV_NODEEVICT) and not events(S, EV_PREEMPT)


def test_failed_node_offers_no_capacity_until_repair():
    c = cluster(1)                                    # a single node
    S, _ = run(c, [(0, 100, 1, 0), (10, 20, 1, 0)], FIFO, [(20.0, 0, FAIL), (60.0, 0, REPAIR)])
    # job0 evicted at 20, nothing can run until repair at 60; FIFO restarts job0 first then job1
    assert S.start_first[0] == 0 and S.finish[0] == 160.0
    assert S.start_first[1] == 160.0
    assert [e[0] for e in events(S, EV_REPAIR)] == [60.0]


def test_failure_is_idempotent_and_repair_of_healthy_node_is_ignored():
    c = cluster(1, 1)
    S, _ = run(c, [(0, 50, 1, 0)], FIFO, [(10.0, 1, REPAIR), (20.0, 1, FAIL), (25.0, 1, FAIL), (40.0, 1, REPAIR)])
    assert len(events(S, EV_FAIL)) == 1 and len(events(S, EV_REPAIR)) == 1
    assert S.sc[SC_ERR] == 0 and S.status[0] == DONE


def test_resume_mode_keeps_progress_after_failure():
    c = cluster(1, 1)
    S, _ = run(c, [(0, 100, 1, 0)], FIFO, [(30.0, 0, FAIL)], resume=True)
    assert S.finish[0] == 100.0 and S.wasted[0] == 0


@pytest.mark.parametrize("policy", [FIFO, PRIO_FIFO, BACKFILL, SJF])
def test_random_failures_keep_invariants(policy):
    rng = np.random.default_rng(7)
    n = 1500
    c = cluster(*([8] * 4 + [4] * 3 + [1] * 8))
    sub = np.sort(rng.uniform(0, 20000, n))
    dur = np.exp(rng.normal(5, 1.2, n)).round() + 1
    g = rng.choice([0.5, 1, 1, 2, 4, 8], n)
    pr = (rng.random(n) < 0.3).astype(int)
    jobs = list(zip(sub, dur, g, pr))
    fails = []
    for node in rng.choice(len(c.node_ngpu), 6, replace=False):
        t = float(rng.uniform(1000, 15000))
        fails += [(t, int(node), FAIL), (t + float(rng.uniform(500, 4000)), int(node), REPAIR)]
    S, w = run(c, jobs, policy, fails, est=workload(jobs).dur)
    assert S.sc[SC_ERR] == 0 and (S.status == DONE).all()
    # replay the log: no GPU over-committed, nothing runs on a failed node
    use = np.zeros((len(c.node_ngpu), 8), dtype=np.int64)
    down = set()
    running = {}
    for i in range(int(S.sc[SC_NEV])):
        t, typ, j, node, mask = S.ev_t[i], S.ev_type[i], int(S.ev_job[i]), int(S.ev_node[i]), int(S.ev_mask[i])
        if typ == EV_FAIL:
            down.add(node)
        elif typ == EV_REPAIR:
            down.discard(node)
        elif typ == EV_START:
            assert node not in down, "job started on a failed node"
            u = min(S.req[j], UNIT)
            running[j] = (node, mask)
            for k in range(8):
                if (mask >> k) & 1:
                    use[node, k] += u
                    assert use[node, k] <= UNIT
        elif typ in (EV_FINISH, EV_PREEMPT, EV_NODEEVICT):
            node, mask = running.pop(j)
            u = min(S.req[j], UNIT)
            for k in range(8):
                if (mask >> k) & 1:
                    use[node, k] -= u
    assert not running and (use == 0).all()
    executed = (w.req / UNIT * w.dur).sum() + S.wasted.sum()
    assert S.util_int.sum() / UNIT == pytest.approx(executed, rel=1e-9)   # busy time conserved incl. work lost to failures
    assert S.sc[SC_FAILEV] > 0
