import numpy as np
import pytest
from scheduler import data
from scheduler.env import SchedulingEnv
from scheduler.duration_model import load_or_fit
from scheduler.whatif import Scenario
from scheduler.sim import SC_ERR, FC_CLOUDCOST, FC_CLOUDJOBS

CLOUD = {"nodes_per_pool": 5, "gpus_per_node": 8, "overflow_wait_s": 0.0, "max_job_cost_usd": 30.0, "offload_min_wait_s": 1800.0}
SC = Scenario(start_day=130, days=1.0, cloud=CLOUD)


@pytest.fixture(scope="module")
def parts():
    pools = data.load_pool_config()
    jobs = data.load_jobs(pools)
    cl = data.calibrate_cluster(data.observed_cluster(data.load_nodes(pools), pools), jobs, 0.85)
    return jobs, cl, load_or_fit(jobs, 40)


def test_dimensions_and_default_behaviour_are_unchanged_without_the_flag(parts):
    jobs, cl, hint = parts
    a, b = SchedulingEnv(jobs, cl, hint, K=8), SchedulingEnv(jobs, cl, hint, K=8, offload=True)
    assert b.action_space.n == a.action_space.n + 1 and b.observation_space.shape[0] == a.observation_space.shape[0] + 2
    obs, _ = a.reset(options={"scenario": Scenario(start_day=130, days=1.0)})
    assert obs.shape[0] == a.observation_space.shape[0] and len(a.action_masks()) == a.action_space.n


def test_offload_action_is_masked_until_the_head_has_waited_and_then_charges_cost(parts):
    jobs, cl, hint = parts
    env = SchedulingEnv(jobs, cl, hint, K=8, offload=True, cost_weight=0.5)
    obs, _ = env.reset(options={"scenario": SC})
    K = env.K
    seen_valid = seen_invalid = 0
    done, total_r, steps = False, 0.0, 0
    while not done and steps < 60000:
        m = env.action_masks()
        S = env.S
        p = int(S.sc[15]); head = int(S.queue[p, 0]) if p >= 0 and S.qc[p] > 0 else -1
        if m[K + 1]:
            seen_valid += 1
            assert head >= 0 and env.S.fc[0] - S.submit[head] >= 1800.0 - 1e-6          # only after the minimum wait
            before = float(S.fc[FC_CLOUDCOST]); jobs_before = float(S.fc[FC_CLOUDJOBS])
            obs, r, te, tr, info = env.step(K + 1)                                       # take the offload
            assert S.job_cloud[head] == 1 and float(S.fc[FC_CLOUDJOBS]) == jobs_before + 1
            assert float(S.fc[FC_CLOUDCOST]) > before                                    # cost charged
            assert r < 0                                                                 # the cost term is part of the reward
            break
        else:
            seen_invalid += 1
            valid = np.flatnonzero(m[:K])
            obs, r, te, tr, info = env.step(int(valid[0]) if len(valid) else K)
        done = te or tr
        steps += 1
    assert seen_valid >= 1, "the offload action never became valid in a loaded window"


def test_random_masked_agent_with_offload_finishes_cleanly(parts):
    jobs, cl, hint = parts
    env = SchedulingEnv(jobs, cl, hint, K=8, offload=True)
    obs, _ = env.reset(options={"scenario": SC})
    rng = np.random.default_rng(0)
    done, n = False, 0
    while not done and n < 120000:
        m = env.action_masks()
        obs, r, te, tr, info = env.step(int(rng.choice(np.flatnonzero(m))))
        assert np.isfinite(r) and np.isfinite(obs).all()
        done = te or tr
        n += 1
    assert te and env.S.sc[SC_ERR] == 0 and (env.S.start_first >= 0).all()


def test_cost_weight_changes_the_reward_not_the_schedule(parts):
    jobs, cl, hint = parts
    def run(w):
        env = SchedulingEnv(jobs, cl, hint, K=8, offload=True, cost_weight=w)
        env.reset(options={"scenario": SC})
        tot, done = 0.0, False
        while not done:
            m = env.action_masks()
            a = env.K + 1 if m[env.K + 1] else int(np.flatnonzero(m[:env.K])[0]) if m[:env.K].any() else env.K
            _, r, te, tr, _ = env.step(a); tot += r; done = te or tr
        return tot, float(env.S.fc[FC_CLOUDCOST])
    (r0, c0), (r1, c1) = run(0.0), run(1.0)
    assert c0 == pytest.approx(c1) and c0 > 0                                            # same decisions, same spend
    assert r1 < r0                                                                       # but a heavier cost weight lowers the return
