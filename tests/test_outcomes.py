import numpy as np
import pytest
from scheduler.outcomes import thermal_outcomes, cost_outcomes, node_busy_gpus
from scheduler.thermal import ThermalProxy
from scheduler.sim import simulate, PRIO_FIFO
from tests.test_sim import cluster, workload


def run(c, jobs, **kw):
    w = workload(jobs)
    return simulate(c, w, PRIO_FIFO, log_events=True, **kw), w


def test_busy_series_matches_the_schedule():
    c = cluster(8, 8)
    S, w = run(c, [(0, 600, 4, 0), (0, 600, 2, 0)])
    busy = node_busy_gpus(S, 2, 1200, 60.0)
    assert busy[:10].sum(axis=1).tolist() == [6.0] * 10          # 4 + 2 GPUs busy for the first ten minutes
    assert busy[11].sum() == 0.0                                  # all finished


def test_no_thermal_violation_in_normal_ambient_but_violation_under_a_cooling_fault():
    th = ThermalProxy.load()
    c = cluster(8)
    S, w = run(c, [(0, 20000, 8, 0)])                             # one node fully busy for 5.5 hours
    normal = thermal_outcomes(S, c, th, 20000)
    fault = thermal_outcomes(S, c, th, 20000, {"at_h": 1.0, "delta_c": 35.0, "duration_h": 4.0})
    assert normal["violation_node_hours"] == 0.0 and normal["peak_c"] < th.threshold_c        # proxy peaks near 50 C
    assert fault["violation_node_hours"] > 2.0 and fault["peak_c"] >= th.threshold_c
    assert fault["nodes_ever_hot"] == 1


def test_idle_node_is_cooler_than_busy_node_under_the_same_fault():
    th = ThermalProxy.load()
    c = cluster(8, 8)
    S, w = run(c, [(0, 20000, 8, 0)])                             # only one of two nodes is used
    f = thermal_outcomes(S, c, th, 20000, {"at_h": 0.0, "delta_c": 35.0, "duration_h": 6.0})
    assert f["nodes_ever_hot"] == 1                               # the idle node stays below the threshold (idle ~39 C + 35 C = 74 C)


def test_cost_counts_eviction_waste_priced_by_tier_and_cloud_separately():
    c = cluster(1)
    S, w = run(c, [(0, 100, 1, 1), (40, 10, 1, 0)], preempt=True)   # spot job evicted at t=40: 40 GPU-seconds wasted
    out = cost_outcomes(S, w, ["x"] if False else ["a100"])
    assert out["wasted_gpu_hours"] == pytest.approx(40 / 3600)
    assert out["cloud_usd"] == 0.0 and out["wasted_compute_usd"] > 0


def test_proxy_implies_a_derating_cap_only_when_the_fault_is_big_enough():
    th = ThermalProxy.load()
    assert th.util_cap_for_fault(0.0) == 1.0 and th.util_cap_for_fault(20.0) == 1.0      # proxy peaks ~50 C: +20 C never reaches 80 C
    cap = th.util_cap_for_fault(35.0)
    assert 0.5 < cap < 1.0                                                               # derived from the measured profile, not typed
    assert th.target(cap * 100)[0] + 35.0 < th.threshold_c <= th.target(min(cap * 100 + 5, 100))[0] + 35.0 + 1e-9
    assert th.util_cap_for_fault(60.0) == 0.0                                            # even an idle node would overheat


def test_derating_caps_node_utilisation_only_inside_the_fault_window():
    from scheduler.sim import FIFO
    c = cluster(8)
    jobs = [(0, 1000, 4, 0), (0, 1000, 4, 0), (3000, 1000, 4, 0), (3000, 1000, 4, 0)]
    w = workload(jobs)
    S = simulate(c, w, FIFO, cloud_price=None, util_cap=0.5, derate_from_s=0.0, derate_to_s=2000.0)
    assert S.start_first[0] == 0.0 and S.start_first[1] == 1000.0                        # inside the window: 4 of 8 GPUs max, so one at a time
    assert S.start_first[2] == 3000.0 and S.start_first[3] == 3000.0                     # after the window: full node again


def test_scenario_derating_setting_is_honoured_even_when_empty():
    """Regression: thermal_derating={} (enabled, defaults) must switch derating on; only None means off."""
    from scheduler.whatif import Scenario, sim_kwargs
    from scheduler import data
    pools = data.load_pool_config()
    cl = data.observed_cluster(data.load_nodes(pools), pools)
    fault = {"at_h": 1.0, "delta_c": 35.0, "duration_h": 2.0}
    assert "util_cap" not in sim_kwargs(Scenario(cooling_fault=fault), cl)
    kw = sim_kwargs(Scenario(cooling_fault=fault, thermal_derating={}), cl)
    assert kw["util_cap"] < 1.0 and kw["derate_from_s"] == 3600.0 and kw["derate_to_s"] == 3 * 3600.0
    assert "util_cap" not in sim_kwargs(Scenario(cooling_fault={**fault, "delta_c": 10.0}, thermal_derating={}), cl) or sim_kwargs(Scenario(cooling_fault={**fault, "delta_c": 10.0}, thermal_derating={}), cl)["util_cap"] == 1.0
