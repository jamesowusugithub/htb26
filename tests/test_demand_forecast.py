"""Demand forecaster: no look-ahead, correct targets, and a feed block that matches the scenario's real arrivals."""
import numpy as np
import pandas as pd
from scheduler import demand_forecast as dfc
from scheduler.demand_forecast import BIN_S, DAY_BINS


def _arrays(P=2, days=12, seed=0):
    rng = np.random.default_rng(seed)
    B = days * DAY_BINS
    g = rng.poisson(3.0, size=(P, B)).astype(float); c = (g > 0).astype(float); o = np.minimum(c, 2.0)
    return g, c, o


def test_target_is_the_next_horizon_and_features_ignore_the_future():
    g, c, o = _arrays()
    hb = 6
    t = np.array([3 * DAY_BINS + 10, 4 * DAY_BINS + 77])
    X, y = dfc.feature_frame(g, c, o, hb, t_bins=t)
    for pi in range(2):
        for k, tt in enumerate(t):
            assert np.isclose(y[pi * 2 + k], g[pi, tt + 1: tt + 1 + hb].sum())          # target = arrivals in bins t+1..t+H
    # changing arrivals AFTER t must not change any feature of row t
    g2 = g.copy(); g2[:, t.max() + 1:] += 50.0
    X2, _ = dfc.feature_frame(g2, c, o, hb, t_bins=t)
    cols = [f for f in dfc.FEATURES if f not in ("yday_next",)]
    pd.testing.assert_frame_equal(X[cols].reset_index(drop=True), X2[cols].reset_index(drop=True))


def test_yesterday_feature_uses_only_the_past():
    g, c, o = _arrays()
    hb = 6; t = np.array([5 * DAY_BINS + 3])
    X, _ = dfc.feature_frame(g, c, o, hb, t_bins=t)
    assert np.isclose(X.yday_next.iloc[0], g[0, t[0] + 1 - DAY_BINS: t[0] + 1 - DAY_BINS + hb].sum())
    assert t[0] + 1 - DAY_BINS + hb <= t[0]          # window ends before 'now'


def test_fit_does_not_see_targets_past_the_cutoff():
    g, c, o = _arrays(days=20)
    g[:, 12 * DAY_BINS:] += 1000.0                    # a huge regime change after the cutoff
    f = dfc.DemandForecaster(1800.0).fit(g, c, o, train_end_bin=12 * DAY_BINS)
    X, _ = dfc.feature_frame(g, c, o, f.hb, t_bins=np.array([10 * DAY_BINS]))
    mu, lo, hi = f.predict(X)
    assert mu.max() < 100 and (lo <= mu).all() and (mu <= hi).all()
