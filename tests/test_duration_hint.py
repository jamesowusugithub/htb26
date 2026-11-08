import numpy as np
import pytest
from scheduler import data
from scheduler.duration_model import feature_table, HIST, NEW


@pytest.fixture(scope="module")
def jobs():
    return data.load_jobs(data.load_pool_config())


def test_history_features_never_see_the_future(jobs):
    """Features for the first N jobs must be identical whether or not later jobs exist in the table."""
    n = 40000
    full = feature_table(jobs)[HIST + NEW].to_numpy()[:n]
    part = feature_table(jobs.iloc[:n].reset_index(drop=True))[HIST + NEW].to_numpy()
    assert np.array_equal(np.nan_to_num(full, nan=-1), np.nan_to_num(part, nan=-1))


def test_history_uses_only_jobs_finished_before_submit(jobs):
    ft = feature_table(jobs)
    sub = jobs.submit_relative_s.to_numpy(float); fin = sub + jobs.duration_s.to_numpy(float)
    for i in (5000, 123456, 400000):
        n_finished_before = int((fin <= sub[i]).sum())
        assert ft["org_n"].iloc[i] <= n_finished_before                     # cannot count more jobs than had finished
    assert np.isnan(ft["key_last"].iloc[0])                                 # first job in the trace has no history
