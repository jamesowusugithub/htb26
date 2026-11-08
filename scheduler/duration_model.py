"""Runtime hint model: predicts log job duration from what is known at submission.

v2 adds *job-history* features: for each job, the durations of recently FINISHED jobs with the same template
(organisation, pool, GPU request, CPUs, workers) and of the same organisation. Jobs recur, so this roughly doubles
the rank correlation (0.26 -> 0.51 on held-out days >= 130). Leakage control: a job's history uses only jobs whose
finish time is <= its submit time, so features never see the future (tested). The booster is trained only on jobs
that had FINISHED before `train_cut_s`.
"""
from __future__ import annotations
import joblib
import numpy as np
import pandas as pd
from numba import njit
from sklearn.ensemble import HistGradientBoostingRegressor
from .data import ROOT

BASE = ["org", "pool", "prio", "gpus", "cpu", "workers", "hod", "dow"]
HIST = ["key_last", "key_med5", "key_n", "org_med20", "org_mean20", "org_n"]
FEATURES = BASE + HIST
MODEL_DIR = ROOT / "models"
VERSION = 2


@njit(cache=True)
def _history(sub, fin, dur, key, org, nkey, norg):
    order_f = np.argsort(fin, kind="stable")
    K = 5
    O = 20
    kbuf = np.zeros((nkey, K))
    kcnt = np.zeros(nkey, np.int64)
    obuf = np.zeros((norg, O))
    ocnt = np.zeros(norg, np.int64)
    out = np.full((len(sub), 6), np.nan)
    j = 0
    for i in range(len(sub)):                      # jobs sorted by submit
        while j < len(order_f) and fin[order_f[j]] <= sub[i]:
            q = order_f[j]
            kq = key[q]
            oq = org[q]
            kbuf[kq, kcnt[kq] % K] = dur[q]
            kcnt[kq] += 1
            obuf[oq, ocnt[oq] % O] = dur[q]
            ocnt[oq] += 1
            j += 1
        k = key[i]
        o = org[i]
        if kcnt[k] > 0:
            m = min(kcnt[k], K)
            out[i, 0] = np.log1p(kbuf[k, (kcnt[k] - 1) % K])
            out[i, 1] = np.log1p(np.median(kbuf[k, :m]))
            out[i, 2] = kcnt[k]
        if ocnt[o] > 0:
            m = min(ocnt[o], O)
            out[i, 3] = np.log1p(np.median(obuf[o, :m]))
            out[i, 4] = np.log1p(np.mean(obuf[o, :m]))
            out[i, 5] = ocnt[o]
    return out


def feature_table(jobs: pd.DataFrame) -> pd.DataFrame:
    """jobs must be sorted by submit time (data.load_jobs does this)."""
    sub = jobs.submit_relative_s.to_numpy(float)
    dur = jobs.duration_s.to_numpy(float)
    org = pd.factorize(jobs.organisation_id)[0]
    key = pd.factorize(pd.MultiIndex.from_arrays([org, jobs.pool.to_numpy(), jobs.req.to_numpy(),
                                                  jobs.cpu_request_vcpus.to_numpy(), jobs.worker_count.to_numpy()]))[0]
    H = _history(sub, sub + dur, dur, key, org, int(key.max()) + 1, int(org.max()) + 1)
    base = pd.DataFrame({"org": org, "pool": jobs.pool.to_numpy(), "prio": jobs.prio.to_numpy(), "gpus": jobs.req.to_numpy() / 100.0,
                         "cpu": jobs.cpu_request_vcpus.to_numpy(float), "workers": jobs.worker_count.to_numpy(float),
                         "hod": sub // 3600 % 24, "dow": sub // 86400 % 7}, index=jobs.job_id.to_numpy())
    return pd.concat([base, pd.DataFrame(H, columns=HIST, index=base.index)], axis=1)


class DurationHint:
    def __init__(self, train_cut_days: float = 40.0):
        self.train_cut_s = train_cut_days * 86400
        self.version = VERSION
        self.model = None
        self.pred_log: pd.Series | None = None

    def fit(self, jobs_full: pd.DataFrame) -> "DurationHint":
        ft = feature_table(jobs_full)
        fin = jobs_full.submit_relative_s.to_numpy(float) + jobs_full.duration_s.to_numpy(float)
        done = fin <= self.train_cut_s                      # only jobs already finished at the cut
        y = np.log1p(jobs_full.duration_s.to_numpy(float))
        self.model = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08, categorical_features=[0, 1, 2], random_state=0)
        self.model.fit(ft.loc[done, FEATURES], y[done])
        self.pred_log = pd.Series(self.model.predict(ft[FEATURES]), index=ft.index)   # past-only features: safe for every job
        self.n_train = int(done.sum())
        return self

    def predict_seconds(self, job_ids) -> np.ndarray:
        base = pd.Index([str(i).split("#")[0] for i in job_ids])
        return np.expm1(self.pred_log.reindex(base).to_numpy())

    def save(self, name):
        MODEL_DIR.mkdir(exist_ok=True)
        self.model = None                                    # predictions are cached; the booster is not needed to serve
        joblib.dump(self, MODEL_DIR / name)


def load_or_fit(jobs_full: pd.DataFrame, train_cut_days: float = 40.0, name: str = "duration_hint_v2.joblib") -> DurationHint:
    p = MODEL_DIR / name
    if p.exists():
        m = joblib.load(p)
        if abs(m.train_cut_s - train_cut_days * 86400) < 1 and getattr(m, "version", 1) == VERSION:
            return m
    m = DurationHint(train_cut_days).fit(jobs_full)
    m.save(name)
    return m
