"""Can richer submission-time features (batch size, recent submit counts, spread of recent durations) beat hint v2?
Selection uses the VALIDATION period (days 118-127) only; the test period (>= day 130) is reported once at the end."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
from numba import njit
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler import data
from scheduler import duration_model as dm
pools = data.load_pool_config(); jobs = data.load_jobs(pools)
sub = jobs.submit_relative_s.to_numpy(float); dur = jobs.duration_s.to_numpy(float); fin = sub + dur; y = np.log1p(dur)
org = pd.factorize(jobs.organisation_id)[0]; pool = jobs.pool.to_numpy()
key = pd.factorize(pd.MultiIndex.from_arrays([org, pool, jobs.req.to_numpy(), jobs.cpu_request_vcpus.to_numpy(), jobs.worker_count.to_numpy()]))[0]
okey = pd.factorize(pd.MultiIndex.from_arrays([org, pool]))[0]

@njit(cache=True)
def extra(sub, fin, dur, key, okey, nkey, nokey):
    """Past-only features: same-template submit burstiness and spread of recent finished durations; org-pool history."""
    order_f = np.argsort(fin, kind="stable")
    R = 64; K = 10
    ksub = np.zeros((nkey, R)); kn = np.zeros(nkey, np.int64)
    osub = np.zeros((nokey, 256)); on = np.zeros(nokey, np.int64)
    kd = np.zeros((nkey, K)); kc = np.zeros(nkey, np.int64)
    od = np.zeros((nokey, 30)); oc = np.zeros(nokey, np.int64)
    out = np.full((len(sub), 11), np.nan)
    j = 0
    for i in range(len(sub)):
        while j < len(order_f) and fin[order_f[j]] <= sub[i]:
            q = order_f[j]; a = key[q]; b = okey[q]
            kd[a, kc[a] % K] = dur[q]; kc[a] += 1; od[b, oc[b] % 30] = dur[q]; oc[b] += 1; j += 1
        a = key[i]; b = okey[i]; t = sub[i]
        c10 = 0; c60 = 0; last = np.nan
        for r in range(min(kn[a], R)):
            s = ksub[a, (kn[a] - 1 - r) % R]
            if r == 0: last = t - s
            if t - s <= 600: c10 += 1
            if t - s <= 3600: c60 += 1
        o60 = 0
        for r in range(min(on[b], 256)):
            if t - osub[b, (on[b] - 1 - r) % 256] <= 3600: o60 += 1
            else: break
        out[i, 0] = c10; out[i, 1] = c60; out[i, 2] = last; out[i, 3] = o60
        if kc[a] > 0:
            m = min(kc[a], K); v = kd[a, :m]
            out[i, 4] = np.log1p(np.min(v)); out[i, 5] = np.log1p(np.max(v)); out[i, 6] = np.std(np.log1p(v))
        if oc[b] > 0:
            m = min(oc[b], 30); v = od[b, :m]
            out[i, 7] = np.log1p(np.median(v)); out[i, 8] = np.log1p(np.quantile(v, 0.9)); out[i, 9] = np.mean(v < 600); out[i, 10] = oc[b]
        ksub[a, kn[a] % R] = t; kn[a] += 1; osub[b, on[b] % 256] = t; on[b] += 1
    return out
E = extra(sub, fin, dur, key, okey, key.max() + 1, okey.max() + 1)
names = ["key_c10m", "key_c1h", "key_gap_s", "org_c1h", "key_min10", "key_max10", "key_std10", "op_med30", "op_q90_30", "op_frac_lt10m", "op_n"]
v2 = dm.feature_table(jobs); v3 = pd.concat([v2, pd.DataFrame(E, columns=names, index=v2.index)], axis=1)
done = fin <= 40 * 86400
val = (sub >= 118 * 86400) & (sub < 128 * 86400); test = sub >= 130 * 86400
def fit(cols, **kw):
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, categorical_features=[0, 1, 2], random_state=0, **kw).fit(v3.loc[done, cols], y[done]); p = m.predict(v3[cols]); return m, p
res = {}
for label, cols in (("v2 (current)", dm.FEATURES), ("v3 all new", dm.FEATURES + names), ("v3 burst only", dm.FEATURES + names[:4]), ("v3 spread only", dm.FEATURES + names[4:7]), ("v3 org-pool only", dm.FEATURES + names[7:])):
    m, p = fit(cols); res[label] = {"val_spearman": round(float(spearmanr(p[val], y[val])[0]), 3)}
    print(f"{label:18s} VALIDATION spearman {res[label]['val_spearman']:.3f}")
best = max(res, key=lambda k: res[k]["val_spearman"]); print("chosen on validation:", best)
cols = {"v2 (current)": dm.FEATURES, "v3 all new": dm.FEATURES + names, "v3 burst only": dm.FEATURES + names[:4], "v3 spread only": dm.FEATURES + names[4:7], "v3 org-pool only": dm.FEATURES + names[7:]}[best]
m, p = fit(cols); print(f"TEST (reported once) spearman: chosen {spearmanr(p[test], y[test])[0]:.3f}  vs v2 {spearmanr(fit(dm.FEATURES)[1][test], y[test])[0]:.3f}")
res["chosen"] = best; Path("analysis/proof/hint-v3-experiment.json").write_text(json.dumps(res, indent=1))
