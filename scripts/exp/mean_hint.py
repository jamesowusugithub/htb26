"""Rank by expected duration (mean) instead of typical duration (median of log)? Heavy tails make these differ."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from scipy.stats import spearmanr
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler.run_baselines import setup, run_policy
from scheduler.policies import POLICIES
from scheduler.whatif import Scenario, build_workload, build_cluster
from scheduler import duration_model as dm
from scheduler.sim import FC_QINT
pools, jobs, base, cl = setup(0.85)
ft = dm.feature_table(jobs); dur = jobs.duration_s.to_numpy(float); fin = jobs.submit_relative_s.to_numpy(float) + dur; done = fin <= 40 * 86400
m_log = HistGradientBoostingRegressor(max_iter=250, learning_rate=.08, categorical_features=[0, 1, 2], random_state=0).fit(ft.loc[done, dm.FEATURES], np.log1p(dur[done]))
m_mean = HistGradientBoostingRegressor(loss="gamma", max_iter=250, learning_rate=.08, categorical_features=[0, 1, 2], random_state=0).fit(ft.loc[done, dm.FEATURES], dur[done])
preds = {"median-of-log (current)": pd.Series(np.expm1(m_log.predict(ft[dm.FEATURES])), index=ft.index), "expected duration (gamma loss)": pd.Series(m_mean.predict(ft[dm.FEATURES]), index=ft.index)}
test = jobs.submit_relative_s.to_numpy() >= 130 * 86400
for k, p in preds.items(): print(f"{k:32s} spearman {spearmanr(p.to_numpy()[test], dur[test])[0]:.3f}")
rows = {k: [] for k in list(preds) + ["priority_fifo", "oracle"]}
for d in (130., 133., 145., 151., 157., 169.):
    sc = Scenario(start_day=d, days=3.0, seed=0); w = build_workload(jobs, sc); c = build_cluster(cl, sc)
    q0 = float(run_policy(c, w, POLICIES["priority_fifo"], snapshot_dt=None).fc[FC_QINT]); rows["priority_fifo"].append(1.0)
    rows["oracle"].append(float(run_policy(c, w, POLICIES["sjf_oracle"], snapshot_dt=None).fc[FC_QINT]) / q0)
    for k, p in preds.items():
        est = p.reindex(pd.Index([str(i).split("#")[0] for i in w.job_id])).to_numpy(); est = np.where(np.isfinite(est), est, np.nanmedian(est))
        rows[k].append(float(run_policy(c, w, POLICIES["sjf_hint"], est=est, snapshot_dt=None).fc[FC_QINT]) / q0)
print("\nqueue-time ratio vs priority_fifo, mean of 6 held-out windows (lower is better):")
for k, v in rows.items(): print(f"  {k:32s} {np.mean(v):.3f}")
