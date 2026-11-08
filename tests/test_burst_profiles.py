import numpy as np
import pytest
from scheduler import burst_profiles as bp, data
from scheduler.whatif import Scenario, build_workload, PRESETS


def test_profiles_are_real_shapes_with_mean_one_and_a_cap():
    for s in bp.TRAIN_SERIES + bp.TEST_SERIES:
        p = np.array(bp.window_profile(s, 100, 72))
        assert p.mean() == pytest.approx(1.0, abs=0.01) and p.max() <= bp.CAP * 1.35 and p.min() >= 0
    assert max(bp.window_profile("burstgpt_3", a, 72) for a, _ in bp.burstiest("burstgpt_3", 72, 1))[0] is not None


def test_train_and_test_shapes_never_share_a_series():
    rng = np.random.default_rng(0)
    seen = {bp.sample(rng)[1].split()[0] for _ in range(200)}
    assert seen <= set(bp.TRAIN_SERIES) and not (seen & set(bp.TEST_SERIES))
    assert "burstgpt_3" in PRESETS["llm_traffic_spike"].arrival_profile_source


def test_profile_reshapes_arrivals_per_hour_and_is_deterministic():
    jobs = data.load_jobs(data.load_pool_config())
    base = build_workload(jobs, Scenario(start_day=60, days=2, seed=3))
    prof = [0.0] * 12 + [2.0] * 12                       # no arrivals in hours 0-11, double in hours 12-23 (repeats daily)
    a = build_workload(jobs, Scenario(start_day=60, days=2, seed=3, arrival_profile=prof))
    b = build_workload(jobs, Scenario(start_day=60, days=2, seed=3, arrival_profile=prof))
    assert (a.submit == b.submit).all() and (a.job_id == b.job_id).all()
    hr = (a.submit[a.eval_mask] // 3600) % 24
    assert (hr < 12).mean() < 0.12                       # morning arrivals removed (jitter can leak a few across the boundary)
    hb = (base.submit[base.eval_mask] // 3600) % 24
    assert (hr >= 12).sum() == pytest.approx(2 * (hb >= 12).sum(), rel=0.1)


def test_scalar_multiplier_behaviour_is_unchanged():
    jobs = data.load_jobs(data.load_pool_config())
    w = build_workload(jobs, Scenario(start_day=60, days=3, arrival_mult=1.3))
    b = build_workload(jobs, Scenario(start_day=60, days=3))
    assert w.eval_mask.sum() == pytest.approx(1.3 * b.eval_mask.sum(), rel=0.05)
