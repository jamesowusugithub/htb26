import numpy as np
import pytest
from scheduler import data
from scheduler.env import SchedulingEnv
from scheduler.duration_model import load_or_fit
from scheduler.metrics import job_table
from scheduler.policies import POLICIES
from scheduler.run_baselines import run_policy
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler.sim import SC_ERR


@pytest.fixture(scope="module")
def parts():
    pools = data.load_pool_config()
    jobs = data.load_jobs(pools)
    cl = data.calibrate_cluster(data.observed_cluster(data.load_nodes(pools), pools), jobs, 0.85)
    return jobs, cl, load_or_fit(jobs, 40)


def rollout(env, policy):
    obs, _ = env.reset()
    total, done = 0.0, False
    while not done:
        a = policy(env, obs)
        obs, r, term, trunc, info = env.step(a)
        total += r
        done = term or trunc
    return total, info


def head_only(env, obs):
    m = env.action_masks()
    return 0 if m[0] else env.K            # start the queue head if it fits, else advance (= priority FIFO)


def greedy_hint(env, obs):
    m = env.action_masks()
    S = env.S
    best, be = None, np.inf
    for k in range(env.K):
        if m[k] and S.est[S.cand_job[k]] < be:
            be, best = S.est[S.cand_job[k]], k
    return best if best is not None else env.K


FIXED = dict(start_day=90, days=1.5, arrival_mult=1.0, capacity=1.0, seed=3)


def test_head_only_agent_reproduces_priority_fifo_exactly(parts):
    jobs, cl, hint = parts
    env = SchedulingEnv(jobs, cl, hint, fixed=FIXED)
    total, info = rollout(env, head_only)
    sc = Scenario(**FIXED)
    w = build_workload(jobs, sc)
    ref = run_policy(build_cluster(cl, sc), w, POLICIES["priority_fifo"], snapshot_dt=None)
    jt_env, jt_ref = job_table(env.S, env.w, env.cluster), job_table(ref, w, build_cluster(cl, sc))
    assert np.allclose(jt_env.wait_s.to_numpy(), jt_ref.wait_s.to_numpy())
    assert total == pytest.approx(-env.base_qint / env.q_ref, rel=1e-6)   # identical queue integral to the baseline
    assert env.S.sc[SC_ERR] == 0


def test_masks_never_allow_invalid_actions_and_episode_terminates(parts):
    jobs, cl, hint = parts
    env = SchedulingEnv(jobs, cl, hint, fixed=FIXED)
    obs, _ = env.reset()
    rng = np.random.default_rng(0)
    done, n = False, 0
    while not done:
        m = env.action_masks()
        assert m.any()
        a = int(rng.choice(np.flatnonzero(m)))
        obs, r, term, trunc, info = env.step(a)
        assert np.isfinite(r) and np.isfinite(obs).all()
        done = term or trunc
        n += 1
    assert term and env.S.sc[SC_ERR] == 0
    assert (env.S.start_first >= 0).all()                           # every job started


def test_hint_greedy_beats_priority_fifo_on_a_loaded_window(parts):
    jobs, cl, hint = parts
    env = SchedulingEnv(jobs, cl, hint, fixed=dict(start_day=130, days=3, arrival_mult=1.0, capacity=1.0, seed=1))
    total, _ = rollout(env, greedy_hint)
    assert total > -env.base_qint / env.q_ref                       # less queue time than priority FIFO


def test_training_sampler_varies_and_is_seeded(parts):
    jobs, cl, hint = parts
    a = SchedulingEnv(jobs, cl, hint, seed=5); b = SchedulingEnv(jobs, cl, hint, seed=5)
    a.reset(); b.reset(); a.reset(); b.reset()
    assert a.sc.scenario_id == b.sc.scenario_id
    c = SchedulingEnv(jobs, cl, hint, seed=6); c.reset()
    assert 45 <= a.sc.start_day <= 125 and c.sc.scenario_id != SchedulingEnv(jobs, cl, hint, seed=5).reset()[1]["scenario_id"]


def test_no_eviction_livelock_when_agent_prefers_spot_jobs(parts):
    """Regression: an agent that always picks the *last* valid slot (often a spot job) must still finish."""
    jobs, cl, hint = parts
    env = SchedulingEnv(jobs, cl, hint, fixed=dict(start_day=118, days=1.5, arrival_mult=1.0, capacity=1.0, seed=0))

    def last_slot(env, obs):
        m = env.action_masks()
        idx = np.flatnonzero(m[: env.K])
        return int(idx[-1]) if len(idx) else env.K

    obs, _ = env.reset()
    done, steps = False, 0
    while not done and steps < 60000:
        obs, r, term, trunc, info = env.step(last_slot(env, obs))
        done = term or trunc
        steps += 1
    assert term and not trunc and steps < 60000
    assert (env.S.start_first >= 0).all()


def test_shuffled_slots_are_an_exact_permutation_of_the_real_candidates(parts):
    """shuffle_slots: slot k of the observation/mask is real candidate perm[k], and an action on slot k starts that real candidate."""
    jobs, cl, hint = parts
    K = 16
    env = SchedulingEnv(jobs, cl, hint, K=K, shuffle_slots=True, fixed=dict(start_day=133.0, days=1.0, arrival_mult=1.0, capacity=1.0, seed=0))
    base = cl.n_pools + 6
    obs, _ = env.reset()
    checked = 0
    rng = np.random.default_rng(0)
    done = False
    while not done and checked < 60:
        S, perm = env.S, env._perm.copy()
        m = env.action_masks()
        for k in range(K):
            assert m[k] == bool(S.amask[perm[k]])
            assert np.array_equal(obs[base + 8 * k: base + 8 * k + 8], S.obs[base + 8 * perm[k]: base + 8 * perm[k] + 8])
        valid = np.flatnonzero(m[:K])
        if len(valid) == 0:
            a = K
        else:
            a = int(rng.choice(valid))
            job = int(S.cand_job[perm[a]])                       # the real job behind the chosen shuffled slot
            running_before = int(S.sc[__import__("scheduler.sim", fromlist=["SC_NRUN"]).SC_NRUN])
        obs, r, te, tr, info = env.step(a)
        done = te or tr
        if len(valid):
            assert S.start_first[job] >= 0                       # that exact job was started
        checked += 1
    assert checked > 20
    assert set(np.unique(env._perm)) == set(range(K))
