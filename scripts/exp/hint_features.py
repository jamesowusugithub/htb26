"""Does more training data or job-history features raise the rank correlation of the runtime hint?
Everything is computed with strictly past information: a job's history features use only jobs that had FINISHED before its submit."""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd
from numba import njit
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler import data
pools = data.load_pool_config(); jobs = data.load_jobs(pools)
sub = jobs.submit_relative_s.to_numpy(float); dur = jobs.duration_s.to_numpy(float); fin = sub + dur
N = len(jobs)

@njit(cache=True)
def history(sub, fin, dur, key, org, nkey, norg):
    """For each job (in submit order): stats of the last finished durations of same-key jobs and same-org jobs."""
    order_f = np.argsort(fin, kind="stable")
    K = 5; O = 20
    kbuf = np.zeros((nkey, K)); kcnt = np.zeros(nkey, np.int64)
    obuf = np.zeros((norg, O)); ocnt = np.zeros(norg, np.int64)
    out = np.full((len(sub), 6), np.nan)
    j = 0
    for i in range(len(sub)):                       # jobs are sorted by submit
        while j < len(order_f) and fin[order_f[j]] <= sub[i]:
            q = order_f[j]; kq = key[q]; oq = org[q]
            kbuf[kq, kcnt[kq] % K] = dur[q]; kcnt[kq] += 1
            obuf[oq, ocnt[oq] % O] = dur[q]; ocnt[oq] += 1
            j += 1
        k = key[i]; o = org[i]
        if kcnt[k] > 0:
            m = min(kcnt[k], K)
            out[i, 0] = np.log1p(kbuf[k, (kcnt[k] - 1) % K]); out[i, 1] = np.log1p(np.median(kbuf[k, :m])); out[i, 2] = kcnt[k]
        if ocnt[o] > 0:
            m = min(ocnt[o], O)
            out[i, 3] = np.log1p(np.median(obuf[o, :m])); out[i, 4] = np.log1p(np.mean(obuf[o, :m])); out[i, 5] = ocnt[o]
    return out

org = pd.factorize(jobs.organisation_id)[0]
key = pd.factorize(pd.MultiIndex.from_arrays([org, jobs.pool.to_numpy(), jobs.req.to_numpy(), jobs.cpu_request_vcpus.to_numpy(), jobs.worker_count.to_numpy()]))[0]
t = time.time(); H = history(sub, fin, dur, key, org, key.max() + 1, org.max() + 1); print(f"history features {time.time()-t:.1f}s; same-key history available for {np.isfinite(H[:,0]).mean():.1%} of jobs, same-org for {np.isfinite(H[:,3]).mean():.1%}")
base = pd.DataFrame({"org": org, "pool": jobs.pool.to_numpy(), "prio": jobs.prio.to_numpy(), "gpus": jobs.req.to_numpy() / 100, "cpu": jobs.cpu_request_vcpus.to_numpy(float),
                     "workers": jobs.worker_count.to_numpy(float), "hod": sub // 3600 % 24, "dow": sub // 86400 % 7})
hist = pd.DataFrame(H, columns=["key_last", "key_med5", "key_n", "org_med20", "org_mean20", "org_n"])
X_base, X_full = base, pd.concat([base, hist], axis=1)
y = np.log1p(dur); test = sub >= 130 * 86400
cat = [0, 1, 2]
def fit_eval(X, cut_days, iters=250):
    tr = (fin <= cut_days * 86400)                  # only jobs already finished at the cut
    m = HistGradientBoostingRegressor(max_iter=iters, learning_rate=0.08, categorical_features=cat, random_state=0).fit(X[tr], y[tr])
    p = m.predict(X[test])
    return {"n_train": int(tr.sum()), "spearman": round(float(spearmanr(p, y[test])[0]), 3), "auc_gt_1h": round(float(roc_auc_score(dur[test] > 3600, p)), 3),
            "auc_gt_1d": round(float(roc_auc_score(dur[test] > 86400, p)), 3)}, p
res = {"learning_curve": []}
for cut in (20, 40, 60, 80, 100, 125):
    a, _ = fit_eval(X_base, cut); b, _ = fit_eval(X_full, cut)
    res["learning_curve"].append({"train_cut_day": cut, "base_features": a, "plus_history": b}); print(f"cut day {cut:>3}: base spearman {a['spearman']:.3f} (n={a['n_train']:,})   +history {b['spearman']:.3f}  auc>1h {b['auc_gt_1h']:.3f}")
# more boosting iterations at the 40-day cut (is the model under-trained?)
res["iterations"] = {}
for it in (50, 250, 1000):
    a, _ = fit_eval(X_full, 40, iters=it); res["iterations"][it] = a["spearman"]; print(f"40-day cut, {it:>4} boosting iterations: spearman {a['spearman']:.3f}")
# the single feature that matters: how well does 'median of the last 5 finished same-key jobs' alone rank durations?
ok = test & np.isfinite(H[:, 1]); res["key_med5_alone_spearman"] = round(float(spearmanr(H[ok, 1], y[ok])[0]), 3); res["key_hist_coverage_test"] = round(float(ok.sum() / test.sum()), 3)
print("same-key history median alone: spearman", res["key_med5_alone_spearman"], "on", f"{res['key_hist_coverage_test']:.1%}", "of test jobs")
Path("analysis/proof/hint-experiment.json").write_text(json.dumps(res, indent=1))
# save the best predictions for all jobs (cut 40, with history) so the simulator can use them without leakage
tr = fin <= 40 * 86400
m = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08, categorical_features=cat, random_state=0).fit(X_full[tr], y[tr])
pd.Series(m.predict(X_full), index=jobs.job_id.to_numpy()).to_frame("pred_log").to_parquet("/private/tmp/claude-501/-Users-carlkaziboni-Documents-htb26-gpu/f988ba59-71fe-4b23-89d3-58b451205e60/scratchpad/hint_v2_pred.parquet")
