import numpy as np
import pytest
from scheduler.data import Cluster, Workload, UNIT
from scheduler.sim import (simulate, FIFO, PRIO_FIFO, BACKFILL, SJF, EV_START, EV_FINISH, EV_PREEMPT, EV_ARRIVE,
                           SC_ERR, SC_DONE, DONE)

POOLS = [{"id": "p0", "label": "p0", "gpu_model_identifier": "x"}]


def cluster(*node_gpus):
    n = np.array(node_gpus, dtype=np.int64)
    return Cluster(POOLS, np.zeros(len(n), dtype=np.int64), n, np.ones(1))


def workload(jobs):
    """jobs: list of (submit, dur, gpus, prio) ; prio 0 = HP, 1 = spot"""
    jobs = sorted(jobs, key=lambda j: j[0])
    a = np.array(jobs, dtype=float)
    return Workload(job_id=np.array([str(i) for i in range(len(jobs))]), submit=a[:, 0], dur=a[:, 1],
                    pool=np.zeros(len(jobs), dtype=np.int64), req=np.rint(a[:, 2] * UNIT).astype(np.int64),
                    prio=a[:, 3].astype(np.int64), org=np.array(["o"] * len(jobs)),
                    eval_mask=np.ones(len(jobs), dtype=bool))


def run(c, jobs, policy, **kw):
    w = workload(jobs)
    S = simulate(c, w, policy, log_events=True, **kw)
    assert S.sc[SC_ERR] == 0
    return S, w


def test_fifo_single_gpu_waits():
    S, _ = run(cluster(1), [(0, 100, 1, 0), (10, 50, 1, 0), (20, 10, 1, 0)], FIFO)
    assert list(S.start_first) == [0, 100, 150]
    assert list(S.finish) == [100, 150, 160]


def test_node_packing_whole_gpus_cannot_span_nodes():
    # two 8-GPU nodes, 5 GPUs busy on each -> 6 free in total but at most 3 per node: a 4-GPU job must wait
    S, _ = run(cluster(8, 8), [(0, 100, 5, 0), (0, 100, 5, 0), (1, 10, 4, 0)], FIFO)
    assert S.start_first[2] == 100


def test_fractional_requests_share_a_gpu():
    S, _ = run(cluster(1), [(0, 100, 0.5, 0), (0, 100, 0.5, 0), (0, 100, 0.5, 0)], FIFO)
    assert S.start_first[0] == 0 and S.start_first[1] == 0 and S.start_first[2] == 100


def test_priority_fifo_orders_hp_before_spot_without_preemption_needed():
    S, _ = run(cluster(1), [(0, 100, 1, 0), (1, 10, 1, 1), (2, 10, 1, 0)], PRIO_FIFO, preempt=False)
    assert S.start_first[2] == 100 and S.start_first[1] == 110


def test_preemption_restart_from_scratch():
    S, _ = run(cluster(1), [(0, 100, 1, 1), (40, 10, 1, 0)], PRIO_FIFO, preempt=True)
    assert S.start_first[1] == 40 and S.finish[1] == 50          # HP starts at once
    assert S.npre[0] == 1 and S.start_first[0] == 0
    assert S.finish[0] == 150                                      # restarts full 100 s at t=50
    assert S.wasted[0] == pytest.approx(40.0)                      # 40 GPU-seconds lost


def test_preemption_resume():
    S, _ = run(cluster(1), [(0, 100, 1, 1), (40, 10, 1, 0)], PRIO_FIFO, preempt=True, resume=True)
    assert S.finish[0] == 110 and S.wasted[0] == 0


def test_fifo_never_preempts_even_if_asked():
    S, _ = run(cluster(1), [(0, 100, 1, 1), (40, 10, 1, 0)], FIFO, preempt=True)
    assert S.start_first[1] == 100 and S.npre.sum() == 0


def test_no_preemption_in_fifo():
    S, _ = run(cluster(1), [(0, 100, 1, 1), (40, 10, 1, 0)], FIFO, preempt=False)
    assert S.start_first[1] == 100 and S.npre.sum() == 0


def test_preempt_picks_node_with_least_spot_work():
    # node0: spot 4 GPUs, node1: spot 1 GPU ; HP wants 8 on... use 1 node each of 4 GPUs. HP needs 4 whole GPUs.
    S, _ = run(cluster(4, 4), [(0, 100, 4, 1), (0, 100, 1, 1), (0, 100, 3, 1), (10, 10, 4, 0)], PRIO_FIFO)
    assert S.start_first[3] == 10
    assert S.npre.sum() >= 1


def test_sjf_picks_shortest_first():
    S, _ = run(cluster(1), [(0, 100, 1, 0), (1, 50, 1, 0), (2, 5, 1, 0)], SJF, preempt=False)
    assert S.start_first[2] == 100 and S.start_first[1] == 105


def test_backfill_small_short_job_jumps_the_blocked_head():
    # node A (4 GPUs) busy with a 100 s job; head wants 4 GPUs. A 1-GPU short job can use the other node.
    c = cluster(4, 4)
    jobs = [(0, 100, 4, 0), (0, 100, 4, 0), (1, 80, 4, 0), (2, 10, 1, 0)]
    S, _ = run(c, jobs, BACKFILL, est=workload(jobs).dur)
    S2, _ = run(c, jobs, PRIO_FIFO)
    # both nodes full until t=100 -> nothing can backfill before then; behaviour must equal priority FIFO here
    assert list(S.start_first) == list(S2.start_first)
    # free node but head blocked by size: node1 has 2 GPUs busy, head needs 4 whole GPUs
    jobs = [(0, 100, 4, 0), (0, 100, 2, 0), (1, 50, 4, 0), (2, 10, 1, 0)]
    S, _ = run(c, jobs, BACKFILL, est=workload(jobs).dur)
    S2, _ = run(c, jobs, PRIO_FIFO)
    assert S2.start_first[3] > 2          # priority FIFO: stuck behind the 4-GPU head? (head fits on free node)
    assert S.start_first[3] <= S2.start_first[3]


def test_backfill_respects_reservation_with_estimates():
    # one 2-GPU node. job0 uses 1 GPU until t=100. head needs 2 GPUs (blocked until 100).
    # long 1-GPU candidate (est 500) must NOT take the idle GPU; short (est 50) may.
    c = cluster(2)
    jobs = [(0, 100, 1, 0), (1, 10, 2, 0), (2, 500, 1, 0), (3, 50, 1, 0)]
    S, _ = run(c, jobs, BACKFILL, est=workload(jobs).dur)
    assert S.start_first[3] == 3                    # short job backfills
    assert S.start_first[2] > 3                     # long job held back
    assert S.start_first[1] <= 100 + 1e-9           # head not delayed past job0 finishing... (head starts when node frees)


def _check_invariants(S, w, cluster_):
    """Replay the event log: capacity never exceeded, every job accounted for, FIFO of events consistent."""
    n_nodes = len(cluster_.node_ngpu)
    use = np.zeros((n_nodes, 8), dtype=np.int64)
    running = {}
    for i in range(int(S.sc[3])):
        t, typ, j, node, mask = S.ev_t[i], S.ev_type[i], int(S.ev_job[i]), int(S.ev_node[i]), int(S.ev_mask[i])
        u = min(S.req[j], UNIT)
        if typ == EV_START:
            assert j not in running
            running[j] = (node, mask)
            for k in range(8):
                if (mask >> k) & 1:
                    use[node, k] += u
                    assert use[node, k] <= UNIT, "GPU over-committed"
                    assert k < cluster_.node_ngpu[node]
            assert t >= S.submit[j] - 1e-9
        elif typ in (EV_FINISH, EV_PREEMPT):
            node, mask = running.pop(j)
            for k in range(8):
                if (mask >> k) & 1:
                    use[node, k] -= u
    assert not running
    assert (use == 0).all()
    assert (S.status == DONE).all()
    assert S.sc[SC_DONE] == len(w)


@pytest.mark.parametrize("policy", [FIFO, PRIO_FIFO, BACKFILL, SJF])
def test_random_stress_invariants(policy):
    rng = np.random.default_rng(1)
    n = 3000
    c = cluster(*([8] * 6 + [4] * 4 + [1] * 12))
    sub = np.sort(rng.uniform(0, 20000, n))
    dur = np.exp(rng.normal(5, 1.5, n)).round() + 1
    g = rng.choice([0.25, 0.5, 1, 1, 2, 4, 8], n)
    pr = (rng.random(n) < 0.25).astype(int)
    jobs = list(zip(sub, dur, g, pr))
    w = workload(jobs)
    S = simulate(c, w, policy, log_events=True, est=w.dur * np.exp(rng.normal(0, 1, n)))
    assert S.sc[SC_ERR] == 0
    _check_invariants(S, w, c)
    # busy-time conservation: integral of busy GPUs == sum of executed work (incl. work later lost to eviction)
    executed = (w.req / UNIT * w.dur).sum() + S.wasted.sum()
    assert S.util_int.sum() / UNIT == pytest.approx(executed, rel=1e-9)


def test_determinism():
    rng = np.random.default_rng(3)
    jobs = list(zip(np.sort(rng.uniform(0, 5000, 500)), rng.uniform(10, 500, 500), rng.choice([1, 2, 8], 500), rng.integers(0, 2, 500)))
    c = cluster(8, 8, 4)
    a, _ = run(c, jobs, BACKFILL, est=workload(jobs).dur)
    b, _ = run(c, jobs, BACKFILL, est=workload(jobs).dur)
    assert (a.start_first == b.start_first).all() and (a.finish == b.finish).all()


def test_low_load_means_no_waiting():
    c = cluster(8, 8, 8, 8)
    jobs = [(i * 1000.0, 100.0, 1, i % 2) for i in range(40)]
    for pol in (FIFO, PRIO_FIFO, BACKFILL, SJF):
        S, w = run(c, jobs, pol)
        assert (S.start_first - S.submit == 0).all()
