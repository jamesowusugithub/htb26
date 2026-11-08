import numpy as np
import pytest
from scheduler.data import UNIT, add_cloud
from scheduler.sim import simulate, FIFO, PRIO_FIFO, FC_CLOUDCOST, FC_CLOUDGPUH, FC_CLOUDJOBS, SC_ERR, DONE, EV_START, SC_NEV
from tests.test_sim import cluster, workload

PRICE = [3.0]


def run(c, jobs, policy=PRIO_FIFO, **kw):
    w = workload(jobs)
    S = simulate(c, w, policy, log_events=True, **kw)
    assert S.sc[SC_ERR] == 0
    return S, w


def test_cloud_nodes_do_not_count_as_capacity_and_normal_placement_never_uses_them():
    c = add_cloud(cluster(1), 1, 8)
    assert c.capacity_gpus()[0] == 1 and c.node_counts()[0] == 1 and c.cloud_capacity_gpus()[0] == 8
    # overflow OFF: the second job must wait for the single owned GPU even though 8 idle cloud GPUs exist
    S, _ = run(c, [(0, 100, 1, 0), (10, 50, 1, 0)], cloud_price=PRICE, overflow_wait_s=0.0)
    assert S.start_first[1] == 100.0 and S.job_cloud.sum() == 0 and S.fc[FC_CLOUDCOST] == 0.0


def test_overflow_offloads_after_the_wait_threshold_and_charges_exactly():
    c = add_cloud(cluster(1), 1, 8)
    # job1 waits from t=10; the next scheduling pass in this pool is job2's arrival at t=120 (110 s >= 100 s threshold)
    jobs = [(0, 1000, 1, 0), (10, 3600, 2, 0), (120, 5, 1, 0)]
    S, w = run(c, jobs, cloud_price=PRICE, overflow_wait_s=100.0)
    assert S.job_cloud[1] == 1 and S.start_first[1] == 120.0
    assert S.fc[FC_CLOUDJOBS] == 1 and S.fc[FC_CLOUDGPUH] == pytest.approx(2.0)          # 3600 s x 2 GPUs
    assert S.fc[FC_CLOUDCOST] == pytest.approx(2.0 * 3.0)                                 # x $3 per GPU-hour
    starts = [(float(S.ev_t[i]), int(S.ev_job[i]), int(S.ev_node[i])) for i in range(int(S.sc[SC_NEV])) if S.ev_type[i] == EV_START]
    assert [n for t, j, n in starts if j == 1] == [1]                                      # node 1 is the cloud node
    assert (S.status == DONE).all()


def test_jobs_that_have_not_waited_long_enough_stay_in_the_queue():
    c = add_cloud(cluster(1), 1, 8)
    S, _ = run(c, [(0, 100, 1, 0), (10, 50, 1, 0), (20, 5, 1, 0)], cloud_price=PRICE, overflow_wait_s=500.0)
    assert S.job_cloud.sum() == 0 and S.start_first[1] == 100.0


def test_cloud_capacity_is_limited_and_configurable():
    c = add_cloud(cluster(1), 1, 2)                                                       # only 2 cloud GPUs
    jobs = [(0, 5000, 1, 0)] + [(1 + i, 5000, 1, 0) for i in range(4)] + [(500, 1, 1, 0)]
    S, w = run(c, jobs, cloud_price=PRICE, overflow_wait_s=50.0)
    cj = np.flatnonzero(S.job_cloud)
    assert len(cj) >= 2
    ev = sorted([(S.start_first[j], +w.req[j] / UNIT) for j in cj] + [(S.finish[j], -w.req[j] / UNIT) for j in cj])
    use = np.cumsum([d for _, d in ev])
    assert use.max() <= 2.0 + 1e-9                                                        # never more than the 2 configured cloud GPUs at once


def test_spot_job_on_cloud_is_never_preempted_for_a_high_priority_job():
    c = add_cloud(cluster(1), 1, 8)
    jobs = [(0, 1000, 1, 0), (10, 3000, 1, 1), (200, 50, 1, 0), (300, 50, 1, 0)]          # spot waits, is offloaded at t=200, HP arrives later
    S, _ = run(c, jobs, cloud_price=PRICE, overflow_wait_s=100.0, preempt=True)
    assert S.job_cloud[1] == 1 and S.npre[1] == 0


def test_busy_time_conservation_counts_only_owned_capacity():
    rng = np.random.default_rng(5)
    n = 800
    c = add_cloud(cluster(*([8] * 3 + [1] * 4)), 2, 8)
    sub = np.sort(rng.uniform(0, 8000, n)); dur = np.exp(rng.normal(5, 1.0, n)).round() + 1
    jobs = list(zip(sub, dur, rng.choice([0.5, 1, 2, 4], n), (rng.random(n) < 0.3).astype(int)))
    S, w = run(c, jobs, cloud_price=PRICE, overflow_wait_s=300.0, est=workload(jobs).dur)
    assert S.job_cloud.sum() > 0
    owned = ~S.job_cloud.astype(bool)
    executed_owned = (w.req[owned] / UNIT * w.dur[owned]).sum() + S.wasted.sum()
    assert S.util_int.sum() / UNIT == pytest.approx(executed_owned, rel=1e-9)             # util_int excludes cloud work


def test_scenario_with_cloud_trades_wait_for_cost_on_a_real_window():
    from scheduler import data
    from scheduler.run_baselines import setup
    from scheduler.whatif import Scenario, run_scenario
    pools, jobs, base, cl = setup(0.85)
    off = run_scenario(Scenario(start_day=130, days=1.0), jobs, cl, ["priority_fifo"])
    on = run_scenario(Scenario(start_day=130, days=1.0, cloud={"nodes_per_pool": 20, "gpus_per_node": 8, "overflow_wait_s": 3600.0}), jobs, cl, ["priority_fifo"])
    m0, m1 = off["policies"]["priority_fifo"]["metrics"], on["policies"]["priority_fifo"]["metrics"]
    assert m0["cloud"]["jobs"] == 0 and m0["cloud"]["cost_usd"] == 0.0
    assert m1["cloud"]["jobs"] > 0 and m1["cloud"]["cost_usd"] > 0
    assert m1["hp"]["wait_mean_s"] < m0["hp"]["wait_mean_s"]                              # the fallback shortens waits ...
    assert on["_cluster"].capacity_gpus().sum() == off["_cluster"].capacity_gpus().sum()  # ... without changing owned capacity
