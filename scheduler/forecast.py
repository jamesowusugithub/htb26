"""Short-horizon utilisation projection from survival statistics (no leakage).

Kaplan-Meier duration curves per pool from jobs submitted *before* the window opens; jobs still running at that
moment are censored, so long jobs are not under-counted (the bias that makes a naive "finished jobs only" model
believe everything is short). For a job already running `e` seconds, P(still running at e+H) = S(e+H)/S(e).
"""
from __future__ import annotations
import numpy as np
import pandas as pd


class SurvivalCurves:
    def __init__(self, curves: list[tuple[np.ndarray, np.ndarray] | None]):
        self.curves = curves

    @classmethod
    def fit(cls, jobs: pd.DataFrame, t0_s: float, n_pools: int, min_jobs: int = 200) -> "SurvivalCurves":
        sub = jobs.submit_relative_s.to_numpy(float)
        dur = jobs.duration_s.to_numpy(float)
        pool = jobs.pool.to_numpy()
        pre = sub < t0_s
        out = []
        for p in range(n_pools):
            m = pre & (pool == p)
            if m.sum() < min_jobs:
                out.append(None)
                continue
            done = (sub[m] + dur[m]) <= t0_s
            t = np.where(done, dur[m], t0_s - sub[m])       # censored at the window opening
            order = np.argsort(t, kind="stable")
            t, ev = t[order], done[order]
            ut, idx = np.unique(t, return_index=True)
            n_at_risk = len(t) - idx
            d = np.add.reduceat(ev.astype(float), idx)
            surv = np.cumprod(1.0 - d / n_at_risk)
            out.append((ut, surv))
        return cls(out)

    def S(self, pool: int, t) -> np.ndarray:
        c = self.curves[pool]
        t = np.asarray(t, dtype=float)
        if c is None:
            return np.ones_like(t)
        ut, sv = c
        i = np.searchsorted(ut, t, side="right") - 1
        return np.where(i < 0, 1.0, sv[np.clip(i, 0, len(sv) - 1)])

    def cond_survival(self, pools: np.ndarray, elapsed: np.ndarray, horizon: float) -> np.ndarray:
        out = np.ones(len(elapsed))
        for p in np.unique(pools):
            m = pools == p
            if self.curves[p] is None:
                continue
            s0 = self.S(p, elapsed[m])
            out[m] = np.clip(self.S(p, elapsed[m] + horizon) / np.maximum(s0, 1e-9), 0.0, 1.0)
        return out

    @property
    def available(self) -> list[bool]:
        return [c is not None for c in self.curves]
