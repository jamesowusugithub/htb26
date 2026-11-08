import numpy as np
import pandas as pd
import pytest
from scheduler import data
from scheduler.whatif import Scenario, build_workload, build_cluster, PRESETS


@pytest.fixture(scope="module")
def env():
    pools = data.load_pool_config()
    jobs = data.load_jobs(pools)
    nodes = data.load_nodes(pools)
    cluster = data.calibrate_cluster(data.observed_cluster(nodes, pools), jobs, 0.85)
    return jobs, cluster


def test_baseline_identity(env):
    jobs, _ = env
    sc = Scenario(start_day=60, days=2)
    w = build_workload(jobs, sc)
    ref = data.make_workload(jobs, 60 * 86400, 62 * 86400)
    assert len(w) == len(ref)
    assert np.allclose(np.sort(w.submit), np.sort(ref.submit))
    assert w.eval_mask.sum() == ref.eval_mask.sum()


def test_deterministic_and_seed_changes_result(env):
    jobs, _ = env
    a = build_workload(jobs, Scenario(start_day=60, days=2, arrival_mult=1.4, seed=1))
    b = build_workload(jobs, Scenario(start_day=60, days=2, arrival_mult=1.4, seed=1))
    c = build_workload(jobs, Scenario(start_day=60, days=2, arrival_mult=1.4, seed=2))
    assert (a.submit == b.submit).all() and (a.job_id == b.job_id).all()
    assert len(a) == len(b) and not np.array_equal(a.submit, c.submit)


@pytest.mark.parametrize("m", [0.5, 1.3, 2.0])
def test_arrival_multiplier_scales_job_count(env, m):
    jobs, _ = env
    base = build_workload(jobs, Scenario(start_day=60, days=3)).eval_mask.sum()
    w = build_workload(jobs, Scenario(start_day=60, days=3, arrival_mult=m))
    assert w.eval_mask.sum() == pytest.approx(base * m, rel=0.05)
    assert (np.diff(w.submit) >= 0).all()           # sorted for the simulator
    assert (w.submit[w.eval_mask] >= 0).all() and (w.submit < 3 * 86400).all()


def test_carryover_untouched_by_perturbations(env):
    jobs, _ = env
    base = build_workload(jobs, Scenario(start_day=60, days=2))
    w = build_workload(jobs, Scenario(start_day=60, days=2, arrival_mult=2.0, spot_share=0.5, duration_mult=3))
    assert (~w.eval_mask).sum() == (~base.eval_mask).sum()
    assert np.array_equal(w.dur[~w.eval_mask], base.dur[~base.eval_mask])


def test_spot_share_hits_target(env):
    jobs, _ = env
    w = build_workload(jobs, Scenario(start_day=60, days=3, spot_share=0.4))
    assert w.prio[w.eval_mask].mean() == pytest.approx(0.4, abs=0.01)


def test_burst_adds_jobs_inside_the_slot_only(env):
    jobs, _ = env
    base = build_workload(jobs, Scenario(start_day=60, days=3))
    w = build_workload(jobs, Scenario(start_day=60, days=3, burst={"start_h": 24, "duration_h": 6, "mult": 4.0}))
    ex = np.array(["#b" in str(i) for i in w.job_id])
    assert ex.sum() > 0
    assert (w.submit[ex] >= 24 * 3600).all() and (w.submit[ex] <= 30 * 3600).all()
    assert w.eval_mask.sum() == base.eval_mask.sum() + ex.sum()


def test_duration_mult(env):
    jobs, _ = env
    base = build_workload(jobs, Scenario(start_day=60, days=2))
    w = build_workload(jobs, Scenario(start_day=60, days=2, duration_mult=2.0))
    assert w.dur[w.eval_mask].mean() == pytest.approx(2 * base.dur[base.eval_mask].mean(), rel=0.01)


def test_capacity_factor_and_unknown_pool(env):
    jobs, cl = env
    c = build_cluster(cl, Scenario(capacity={"a10": 0.5}))
    i = [p["id"] for p in cl.pools].index("a10")
    assert c.node_counts()[i] == pytest.approx(cl.node_counts()[i] * 0.5, abs=1)
    assert (np.delete(c.node_counts(), i) == np.delete(cl.node_counts(), i)).all()
    with pytest.raises(ValueError):
        build_cluster(cl, Scenario(capacity={"nope": 0.5}))


def test_scenario_id_stable_and_roundtrip():
    a = Scenario(arrival_mult=1.3, seed=4)
    assert a.scenario_id == Scenario.from_dict(a.to_dict()).scenario_id
    assert a.scenario_id != Scenario(arrival_mult=1.3, seed=5).scenario_id
    assert len({p.scenario_id for p in PRESETS.values()}) == len(PRESETS)
