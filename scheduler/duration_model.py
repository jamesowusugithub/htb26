"""Runtime hint model: predicts log job duration from what is known at submission.

Trained only on jobs that had *finished* before `train_cut_s` (what a scheduler could have learned from
history), so evaluation windows after the cut see no leakage. Survivorship bias is deliberate: long
jobs that were still running at the cut are unseen, exactly as in production.
Duration is only weakly predictable from these fields (see analysis); this model supplies a *hint*.
"""
from __future__ import annotations
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from .data import ROOT

FEATURES = ["org", "pool", "prio", "gpus", "cpu", "workers", "hod", "dow"]
MODEL_DIR = ROOT / "models"


def feature_table(jobs: pd.DataFrame, org_codes: dict) -> pd.DataFrame:
    sub = jobs.submit_relative_s.to_numpy(dtype=float)
    return pd.DataFrame({
        "org": jobs.organisation_id.map(org_codes).fillna(-1).to_numpy().astype(np.int64),
        "pool": jobs.pool.to_numpy(), "prio": jobs.prio.to_numpy(), "gpus": jobs.req.to_numpy() / 100.0,
        "cpu": jobs.cpu_request_vcpus.to_numpy(dtype=float), "workers": jobs.worker_count.to_numpy(dtype=float),
        "hod": (sub // 3600 % 24), "dow": (sub // 86400 % 7)}, index=jobs.job_id.to_numpy())


class DurationHint:
    def __init__(self, train_cut_days: float = 40.0):
        self.train_cut_s = train_cut_days * 86400
        self.model: HistGradientBoostingRegressor | None = None
        self.org_codes: dict = {}
        self.table: pd.DataFrame | None = None
        self.pred_log: pd.Series | None = None

    def fit(self, jobs_full: pd.DataFrame) -> "DurationHint":
        j = jobs_full
        self.org_codes = {o: i for i, o in enumerate(sorted(j.organisation_id.unique()))}
        ft = feature_table(j, self.org_codes)
        done = (j.submit_relative_s + j.duration_s <= self.train_cut_s).to_numpy()
        self.model = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08, categorical_features=[0, 1, 2],
                                                   random_state=0)
        self.model.fit(ft.loc[done, FEATURES], np.log1p(j.duration_s.to_numpy()[done]))
        self.table = ft
        self.pred_log = pd.Series(self.model.predict(ft[FEATURES]), index=ft.index)   # all jobs; only usable after the cut
        self.n_train = int(done.sum())
        return self

    def predict_seconds(self, job_ids) -> np.ndarray:
        """Estimate for workload job ids (what-if duplicates `123#x4` map to their source job)."""
        base = pd.Index([str(i).split("#")[0] for i in job_ids])
        return np.expm1(self.pred_log.reindex(base).to_numpy())

    def save(self, name="duration_hint.joblib"):
        MODEL_DIR.mkdir(exist_ok=True)
        joblib.dump(self, MODEL_DIR / name)


def load_or_fit(jobs_full: pd.DataFrame, train_cut_days: float = 40.0, name: str = "duration_hint.joblib") -> DurationHint:
    p = MODEL_DIR / name
    if p.exists():
        m = joblib.load(p)
        if abs(m.train_cut_s - train_cut_days * 86400) < 1:
            return m
    m = DurationHint(train_cut_days).fit(jobs_full)
    m.save(name)
    return m
