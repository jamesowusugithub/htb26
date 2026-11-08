"""Learn a temperature model from the measured telemetry and test it honestly.
Task (scheduler time scale): given a GPU's temperature now and the load planned for the next minute, predict temperature 60 s later.
Evaluation: held-out SESSIONS (no session appears in both train and test), compared with persistence and the static util->temp proxy."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler.thermal import ThermalProxy
ROOT = Path(__file__).resolve().parents[2]
cols = ["session_id", "gpu_model_identifier", "workload", "gpu_index_within_run", "elapsed_seconds", "temperature_c", "utilisation_percent", "power_w"]
H = 60
rows = []
for f in sorted(glob.glob(str(ROOT / "harmonized/thermal/gpu_telemetry/*.parquet"))):
    d = pd.read_parquet(f, columns=cols)
    if d.gpu_model_identifier.iloc[0] not in ("nvidia_h100", "nvidia_b200"): continue
    d = d[(d.temperature_c > 5) & d.utilisation_percent.notna() & d.elapsed_seconds.notna()]          # drop 0 C sensor dropouts
    d["sec"] = np.floor(d.elapsed_seconds).astype(int)
    g = d.groupby(["session_id", "gpu_model_identifier", "workload", "gpu_index_within_run", "sec"], observed=True).agg(temp=("temperature_c", "mean"), util=("utilisation_percent", "mean"), power=("power_w", "mean")).reset_index()
    rows.append(g)
tel = pd.concat(rows, ignore_index=True); print("1-second bins:", len(tel), "| sessions", tel.session_id.nunique())
out = []
for (s, m, w, gi), g in tel.groupby(["session_id", "gpu_model_identifier", "workload", "gpu_index_within_run"], observed=True):
    g = g.set_index("sec")[["temp", "util", "power"]].reindex(range(g.sec.min(), g.sec.max() + 1)).interpolate(limit=5)
    if len(g) < 200: continue
    u = g.util.to_numpy(); T = g.temp.to_numpy(); P = g.power.to_numpy()
    cu = np.concatenate([[0], np.cumsum(np.nan_to_num(u))]); cp = np.concatenate([[0], np.cumsum(np.nan_to_num(P))])
    idx = np.arange(60, len(g) - H, 10)
    u10 = (cu[idx + 1] - cu[idx - 9]) / 10; u60 = (cu[idx + 1] - cu[idx - 59]) / 60; un = (cu[idx + H + 1] - cu[idx + 1]) / H; p60 = (cp[idx + 1] - cp[idx - 59]) / 60
    out.append(pd.DataFrame({"session": s, "model": m, "workload": w, "gpu": gi, "T0": T[idx], "u_now": u[idx], "u10": u10, "u60": u60, "u_next": un, "p60": p60, "T_future": T[idx + H], "T_min_seen": np.minimum.accumulate(T)[idx]}))
D = pd.concat(out, ignore_index=True).dropna(); print("training examples:", len(D))
proxy = ThermalProxy.load()
D["proxy_static"] = proxy.target(D.u_next)[0]                       # my current proxy: pooled-H100 band medians (ignores state)
D["persist"] = D.T0
D["mcode"] = (D.model == "nvidia_b200").astype(int); D["wcode"] = pd.factorize(D.workload)[0]
F = ["T0", "u_now", "u10", "u60", "u_next", "mcode"]
rmse = lambda a, b: float(np.sqrt(np.mean((a - b) ** 2)))
def cv(df, feats, name):
    pred = np.zeros(len(df))
    for tr, te in GroupKFold(5).split(df, groups=df.session):
        m = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=0).fit(df.iloc[tr][feats], (df.T_future - df.T0).iloc[tr])
        pred[te] = df.T0.iloc[te] + m.predict(df.iloc[te][feats])
    return pred
D["learned"] = cv(D, F, "all")
res = {"n_examples": int(len(D)), "sessions": int(D.session.nunique()), "horizon_s": H, "rmse_c": {}, "by_model": {}}
for k in ("persist", "proxy_static", "learned"): res["rmse_c"][k] = round(rmse(D[k], D.T_future), 2)
for mname, g in D.groupby("model"):
    res["by_model"][mname] = {k: round(rmse(g[k], g.T_future), 2) for k in ("persist", "proxy_static", "learned")}
res["target_std_c"] = round(float(D.T_future.std()), 2)
# hard cases: large load change over the next minute (where a scheduler's decision matters)
big = np.abs(D.u_next - D.u60) > 30
res["rmse_when_load_changes_gt30pct"] = {k: round(rmse(D[big][k], D[big].T_future), 2) for k in ("persist", "proxy_static", "learned")}; res["n_load_change"] = int(big.sum())
# cross-hardware transfer: train on H100 only, test on B200 sessions (and the reverse)
for a, b in (("nvidia_h100", "nvidia_b200"), ("nvidia_b200", "nvidia_h100")):
    tr, te = D[D.model == a], D[D.model == b]
    m = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=0).fit(tr[F[:-1]], tr.T_future - tr.T0)
    res.setdefault("transfer", {})[f"train_{a[7:]}_test_{b[7:]}"] = {"learned_rmse_c": round(rmse(te.T0 + m.predict(te[F[:-1]]), te.T_future), 2),
        "persistence_rmse_c": round(rmse(te.persist, te.T_future), 2), "static_proxy_rmse_c": round(rmse(te.proxy_static, te.T_future), 2)}
print(json.dumps(res, indent=1))
Path(ROOT / "analysis/proof/thermal-model-experiment.json").write_text(json.dumps(res, indent=1))
# fit the final models on all sessions (one per hardware) for use in the simulator export
import joblib
final = {}
for mname, g in D.groupby("model"):
    final[mname] = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.08, random_state=0).fit(g[F[:-1]], g.T_future - g.T0)
joblib.dump({"models": final, "features": F[:-1], "horizon_s": H, "trained_on": {k: int((D.model == k).sum()) for k in final}}, ROOT / "models/thermal_model.joblib")
