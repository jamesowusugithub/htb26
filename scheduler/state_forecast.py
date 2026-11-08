"""EXPERIMENT - NOT USED BY THE API. Measured on held-out windows (analysis/rl/state_forecast_{30,120,360}min.json) this did not beat persistence
(only the A100 pool improved), so the displayed utilisation forecast stays persistence.

Cluster-state forecaster: pool utilisation and queue length H seconds ahead, from the replayed state (RECONSTRUCTED - the trace has no
queue or utilisation data) plus recent arrival volume. Compared with persistence ("it stays as it is"), the forecast shown before.

Rows: one per (pool, snapshot). Features use only the state up to the snapshot and arrivals up to that time.
Targets: busy fraction at t+H (modelled as a change from now) and total queue length at t+H (modelled in log1p space).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingRegressor
from .demand_forecast import BIN_S, DAY_BINS, _csum

FEATURES = ["pool", "log_cap", "busy", "busy_d1", "busy_d3", "busy_d6", "logq", "logq_hp", "logq_d3", "logq_d6", "run_per_gpu", "maxfree_frac",
            "dem6", "dem12", "dem48", "dem288", "tod_sin", "tod_cos"]
_MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
TRAIN_END_DAY = 100


def build_rows(tl: pd.DataFrame, g_bins: np.ndarray, t0_s: float, pool_ids: list[str], snap_dt: float, horizon_s: float, with_targets: bool = True) -> pd.DataFrame:
    """tl = scheduler.metrics.timeline(...) of one run; g_bins = GPUs requested per 5-min bin per pool covering history + window."""
    cg = _csum(g_bins)
    h = int(round(horizon_s / snap_dt)); rows = []
    for p, pid in enumerate(pool_ids):
        d = tl[tl.pool == pid].sort_values("t").reset_index(drop=True)
        n = len(d)
        if n < 8:
            continue
        cap = d.capacity_gpus.to_numpy()[0]
        busy = (d.busy_gpus.to_numpy() / max(cap, 1e-9)); q = (d.queue_hp + d.queue_spot).to_numpy(float); qhp = d.queue_hp.to_numpy(float)
        run = d.running_jobs.to_numpy(float); mf = d.max_free_gpus_on_one_node.to_numpy(float)
        t = d.t.to_numpy()
        k = np.arange(n)
        lag = lambda a, m: a[np.maximum(k - m, 0)]
        tb = np.minimum(((t0_s + t) // BIN_S).astype(int), g_bins.shape[1] - 1)
        win = lambda m: (cg[p, tb + 1] - cg[p, np.maximum(tb + 1 - m, 0)]) / max(cap, 1e-9)
        tod = ((t0_s + t) % 86400) / 86400 * 2 * np.pi
        r = pd.DataFrame({"pool": p, "log_cap": np.log1p(cap), "busy": busy, "busy_d1": busy - lag(busy, 1), "busy_d3": busy - lag(busy, 3), "busy_d6": busy - lag(busy, 6),
                          "logq": np.log1p(q), "logq_hp": np.log1p(qhp), "logq_d3": np.log1p(q) - np.log1p(lag(q, 3)), "logq_d6": np.log1p(q) - np.log1p(lag(q, 6)),
                          "run_per_gpu": run / max(cap, 1e-9), "maxfree_frac": mf / max(d.max_free_gpus_on_one_node.max(), 1.0),
                          "dem6": win(6), "dem12": win(12), "dem48": win(48), "dem288": win(288), "tod_sin": np.sin(tod), "tod_cos": np.cos(tod), "t": t})
        if with_targets:
            r["y_busy"] = np.r_[busy[h:], np.full(h, np.nan)]; r["y_logq"] = np.r_[np.log1p(q[h:]), np.full(h, np.nan)]
        r["q"] = q
        rows.append(r)
    return pd.concat(rows, ignore_index=True)


class StateForecaster:
    def __init__(self, horizon_s: float = 1800.0, seed: int = 0):
        self.horizon_s = horizon_s; self.seed = seed; self.m_busy = None; self.m_q = None

    def _gb(self):
        return HistGradientBoostingRegressor(loss="squared_error", max_iter=250, learning_rate=0.05, max_leaf_nodes=24, min_samples_leaf=200,
                                             l2_regularization=1.0, categorical_features=[0], random_state=self.seed)

    def fit(self, rows: pd.DataFrame):
        r = rows.dropna(subset=["y_busy", "y_logq"])
        self.m_busy = self._gb().fit(r[FEATURES], r.y_busy - r.busy)              # change in busy fraction
        self.m_q = self._gb().fit(r[FEATURES], r.y_logq - r.logq)                 # change in log1p(queue)
        return self

    def predict(self, rows: pd.DataFrame):
        busy = np.clip(rows.busy.to_numpy() + self.m_busy.predict(rows[FEATURES]), 0.0, 1.0)
        q = np.expm1(np.maximum(rows.logq.to_numpy() + self.m_q.predict(rows[FEATURES]), 0.0))
        return busy, q
