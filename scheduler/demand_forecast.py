"""Short-horizon demand forecaster: GPUs requested per pool over the next H seconds, with a prediction interval.

Target (scheduler-independent, so the evaluation is clean): sum of requested GPUs of the jobs that ARRIVE in (t, t+H].
Features use only arrivals at or before t: recent arrival volume at several lags, same-time-yesterday / last-week volume,
time of day, and the number of distinct organisations active (a burst from one org looks different from broad load).
Gradient boosting on log1p(demand); quantile models give the P10/P90 band. Trained on days < train_end only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import json
from pathlib import Path
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor

BIN_S = 300.0                    # 5-minute bins
DAY_BINS = int(86400 / BIN_S)
FEATURES = ["pool", "tod_sin", "tod_cos", "dow", "g_1", "g_2", "g_6", "g_12", "g_48", "g_288", "n_6", "orgs_6", "orgs_48",
            "yday_next", "yday_now", "wk_next", "ratio_6_48", "max_1_6"]


def arrival_bins(jobs: pd.DataFrame, n_pools: int, horizon_s: float = 86400 * 185):
    """Per pool: GPUs requested, job count, distinct orgs per 5-minute bin (arrays [P, B])."""
    B = int(horizon_s // BIN_S) + 1
    gpus = np.zeros((n_pools, B)); cnt = np.zeros((n_pools, B)); orgs = np.zeros((n_pools, B))
    b = np.minimum((jobs.submit_relative_s.to_numpy(float) // BIN_S).astype(int), B - 1)
    p = jobs.pool.to_numpy(int); g = jobs.req.to_numpy(float) / 100.0
    np.add.at(gpus, (p, b), g); np.add.at(cnt, (p, b), 1.0)
    u = pd.DataFrame({"p": p, "b": b, "o": jobs.organisation_id.to_numpy()}).drop_duplicates()
    np.add.at(orgs, (u.p.to_numpy(), u.b.to_numpy()), 1.0)
    return gpus, cnt, orgs


def _csum(a):                         # prefix sums along time, with a leading zero
    return np.concatenate([np.zeros((a.shape[0], 1)), np.cumsum(a, axis=1)], axis=1)


def feature_frame(gpus, cnt, orgs, horizon_bins: int, t_bins=None) -> tuple[pd.DataFrame, np.ndarray]:
    """One row per (pool, bin t) with t >= 2 days (so every lag exists). Row means: information up to the END of bin t.
    Returns (X, y) where y = GPUs arriving in bins t+1..t+H (NaN where the future is not in the data)."""
    P, B = gpus.shape
    cg, cc, co = _csum(gpus), _csum(cnt), _csum(orgs)

    def win(c, t, k):                  # sum over bins t-k+1..t
        return c[:, t + 1] - c[:, np.maximum(t + 1 - k, 0)]

    t = np.arange(2 * DAY_BINS, B - horizon_bins) if t_bins is None else np.asarray(t_bins, dtype=int)
    feats = {}
    for k in (1, 2, 6, 12, 48, 288):
        feats[f"g_{k}"] = win(cg, t, k)
    feats["n_6"] = win(cc, t, 6)
    feats["orgs_6"] = win(co, t, 6); feats["orgs_48"] = win(co, t, 48)
    y_all = cg[:, t + 1 + horizon_bins] - cg[:, t + 1]
    # same time yesterday / last week: demand in the SAME future window one day / one week earlier (fully in the past)
    feats["yday_next"] = cg[:, t + 1 + horizon_bins - DAY_BINS] - cg[:, t + 1 - DAY_BINS]
    feats["yday_now"] = win(cg, t - DAY_BINS, horizon_bins)
    tw = np.maximum(t - 7 * DAY_BINS, 0)
    feats["wk_next"] = np.where(t >= 7 * DAY_BINS, cg[:, tw + 1 + horizon_bins] - cg[:, tw + 1], np.nan)
    feats["ratio_6_48"] = feats["g_6"] / (feats["g_48"] / 8.0 + 1.0)
    feats["max_1_6"] = np.stack([gpus[:, np.maximum(t - i, 0)] for i in range(6)]).max(axis=0)
    tod = (t % DAY_BINS) / DAY_BINS * 2 * np.pi
    rows = []
    for p in range(P):
        d = {k: v[p] for k, v in feats.items()}
        d["pool"] = np.full(len(t), p); d["tod_sin"] = np.sin(tod); d["tod_cos"] = np.cos(tod)
        d["dow"] = (t // DAY_BINS) % 7; d["t_bin"] = t; d["y"] = y_all[p]
        rows.append(pd.DataFrame(d))
    df = pd.concat(rows, ignore_index=True)
    return df[FEATURES + ["t_bin"]], df["y"].to_numpy()


class DemandForecaster:
    def __init__(self, horizon_s: float = 1800.0, seed: int = 0):
        self.hb = int(round(horizon_s / BIN_S)); self.horizon_s = horizon_s; self.seed = seed
        self.mean = None; self.lo = None; self.hi = None
        self.cqr = None            # per-pool conformal widening of the P10-P90 band (fitted on VALIDATION days only)

    def _fit_one(self, X, y, loss="squared_error", q=None):
        kw = dict(loss=loss, max_iter=300, learning_rate=0.05, max_leaf_nodes=24, min_samples_leaf=100, l2_regularization=1.0,
                  categorical_features=[0], random_state=self.seed)
        if q is not None:
            kw["quantile"] = q
        return HistGradientBoostingRegressor(**kw).fit(X, y)

    def fit(self, gpus, cnt, orgs, train_end_bin: int, calib_days=None):
        X, y = feature_frame(gpus, cnt, orgs, self.hb)
        m = (X.t_bin.to_numpy() + self.hb < train_end_bin)          # the target window must also close before the cutoff (no peeking)
        Xt, yt = X.loc[m, FEATURES], np.log1p(y[m])
        self.mean = self._fit_one(Xt, yt)
        self.lo = self._fit_one(Xt, yt, "quantile", 0.1); self.hi = self._fit_one(Xt, yt, "quantile", 0.9)
        if calib_days is not None:                                   # calibrate the band on validation days; never on the held-out test days
            a, b = calib_days; tb = X.t_bin.to_numpy() / DAY_BINS
            mv = (tb >= a) & (tb < b)
            self.calibrate(X.loc[mv, FEATURES + ["t_bin"]], y[mv])
        return self

    def _raw(self, X):
        mu = np.expm1(self.mean.predict(X[FEATURES])).clip(0)
        lo = np.expm1(self.lo.predict(X[FEATURES])).clip(0); hi = np.expm1(self.hi.predict(X[FEATURES])).clip(0)
        return mu, np.minimum(lo, mu), np.maximum(hi, mu)

    def calibrate(self, X: pd.DataFrame, y: np.ndarray, coverage: float = 0.8):
        """Conformalised quantile regression (Romano et al. 2019): per pool, shift both band edges by the `coverage` quantile of
        max(lo - y, y - hi) measured on held-aside validation rows, so the band covers ~`coverage` of outcomes (it can also narrow)."""
        mu, lo, hi = self._raw(X)
        score = np.maximum(lo - y, y - hi); pool = X.pool.to_numpy()
        self.cqr = {int(p): float(np.quantile(score[pool == p], min(1.0, coverage * (1 + 1.0 / max((pool == p).sum(), 1))))) for p in np.unique(pool)}
        return self

    def predict(self, X: pd.DataFrame):
        mu, lo, hi = self._raw(X)
        if self.cqr:
            q = np.array([self.cqr.get(int(p), 0.0) for p in X.pool.to_numpy()])
            lo, hi = np.maximum(lo - q, 0.0), hi + q
        return mu, np.minimum(lo, mu), np.maximum(hi, mu)


TRAIN_END_DAY = 100            # trained on days < 100 only; days 100-129 = validation, >= 130 = held-out test (the same split the RL uses)
_MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
_SKILL_JSON = Path(__file__).resolve().parents[1] / "analysis" / "rl" / "demand_forecast_30min.json"


def load_or_fit(jobs: pd.DataFrame, n_pools: int, horizon_s: float = 1800.0) -> DemandForecaster:
    path = _MODEL_DIR / f"demand_forecaster_v2_h{int(horizon_s)}.joblib"
    if path.exists():
        try:
            return joblib.load(path)
        except Exception:
            pass
    g, c, o = arrival_bins(jobs, n_pools)
    f = DemandForecaster(horizon_s).fit(g, c, o, train_end_bin=TRAIN_END_DAY * DAY_BINS, calib_days=(TRAIN_END_DAY, 130))
    try:
        joblib.dump(f, path)
    except OSError:
        pass
    return f


def heldout_skill() -> dict | None:
    """Measured skill on days >= 130 (written by scripts/exp/demand_forecast.py), shipped with the feed so the UI can show it."""
    try:
        t = json.loads(_SKILL_JSON.read_text())["splits"]["TEST days 130+"]
    except (OSError, KeyError, ValueError):
        return None
    return {"split": "held-out trace days >= 130", "per_pool": {k: {"mae_gpus": v["MAE model"], "persistence_mae_gpus": v["MAE persistence (last 30 min)"],
            "skill_vs_persistence": v["skill vs persistence"], "p10_p90_coverage": v["P10-P90 coverage"]} for k, v in t.items()}}


def combined_bins(jobs: pd.DataFrame, w, n_pools: int, t0_s: float, span_s: float):
    """Arrival arrays: real trace arrivals before t0, the scenario workload's own arrivals inside the window."""
    keep = np.asarray(w.eval_mask) & (np.asarray(w.submit) > 0)
    win = pd.DataFrame({"submit_relative_s": t0_s + np.asarray(w.submit, float)[keep], "pool": np.asarray(w.pool)[keep], "req": np.asarray(w.req)[keep],
                        "organisation_id": np.asarray(w.org)[keep]})
    hist = jobs.loc[jobs.submit_relative_s < t0_s, ["submit_relative_s", "pool", "req", "organisation_id"]]
    return arrival_bins(pd.concat([hist, win], ignore_index=True), n_pools, horizon_s=t0_s + span_s)


def forecast_series(f: DemandForecaster, jobs: pd.DataFrame, w, pool_ids: list[str], t0_s: float, length_s: float, step_s: float = 1800.0) -> dict:
    """Forecast vs realised demand for one scenario window. History before t0 = real trace arrivals; inside the window = the scenario's own
    arrivals (so bursts / multipliers are forecast too). Row at time t uses only arrivals up to t."""
    P = len(pool_ids)
    g, c, o = combined_bins(jobs, w, P, t0_s, length_s + 2 * f.horizon_s + 2 * BIN_S)
    b0 = int(round(t0_s / BIN_S))
    ts_rel = np.arange(step_s, length_s + 1e-9, step_s)                              # forecast issued at t (seconds since window start)
    tb = b0 + (ts_rel / BIN_S).astype(int) - 1                                       # last fully observed bin
    ok = tb >= 2 * DAY_BINS
    tb = tb[ok]; ts_rel = ts_rel[ok]
    if len(tb) == 0:
        return {"available": False, "reason": "window starts less than 2 days into the trace (lags unavailable)"}
    X, y = feature_frame(g, c, o, f.hb, t_bins=tb)
    mu, lo, hi = f.predict(X)
    n = len(tb)
    series = []
    for k in range(n):
        d = {}
        for p, pid in enumerate(pool_ids):
            i = p * n + k
            d[pid] = {"next_gpus": round(float(mu[i]), 2), "p10": round(float(lo[i]), 2), "p90": round(float(hi[i]), 2),
                      "persistence_gpus": round(float(X.g_6.iloc[i] * f.hb / 6.0), 2), "realised_gpus": round(float(y[i]), 2)}
        series.append({"t": float(ts_rel[k]), "horizon_s": f.horizon_s, "pools": d})
    return {"available": True, "horizon_s": f.horizon_s, "step_s": step_s, "series": series,
            "in_training_period": bool(t0_s < TRAIN_END_DAY * 86400.0),
            "quantity": "GPUs requested by jobs arriving in the next horizon (demand, not utilisation)",
            "method": "gradient boosting on recent arrival volume, time of day, same-time-yesterday/last-week and org spread; P10/P90 quantile models",
            "trained_on": f"trace days < {TRAIN_END_DAY}", "heldout_skill": heldout_skill(), "evidence": "calculated_forecast"}
