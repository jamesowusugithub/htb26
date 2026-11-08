"""Demand forecaster vs naive baselines. Train < day 100, tune on 100-129 (hyper-params were NOT tuned beyond defaults), report on >= 130 (held out)."""
import sys, json; from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scheduler.run_baselines import setup
from scheduler.demand_forecast import arrival_bins, feature_frame, DemandForecaster, DAY_BINS, FEATURES
pools, jobs, base, cl = setup(0.85)
P = len(pools); names = [p["id"] for p in pools]
H = float(sys.argv[1]) if len(sys.argv) > 1 else 1800.0
g, c, o = arrival_bins(jobs, P)
f = DemandForecaster(H).fit(g, c, o, train_end_bin=100 * DAY_BINS)
X, y = feature_frame(g, c, o, f.hb)
day = X.t_bin.to_numpy() / DAY_BINS
res = {"horizon_s": H, "splits": {}}
mu, lo, hi = f.predict(X)
sc = f.hb / 6.0                                  # persistence = recent arrival RATE held constant, scaled to the forecast horizon (fair at every horizon)
base_preds = {"persistence (last 30 min)": X.g_6.to_numpy() * sc, "mean of last hour": X.g_12.to_numpy() * f.hb / 12.0,
              "same time yesterday": X.yday_next.to_numpy(), "same time last week": np.nan_to_num(X.wk_next.to_numpy(), nan=0.0)}
def table(m, label):
    rows = []
    for p in list(range(P)) + [None]:
        mm = m & ((X.pool.to_numpy() == p) if p is not None else True)
        ys = y[mm]; r = {"pool": names[p] if p is not None else "ALL", "mean_demand_gpus": float(ys.mean()), "n": int(mm.sum())}
        r["MAE model"] = float(np.abs(mu[mm] - ys).mean())
        for k, v in base_preds.items(): r[f"MAE {k}"] = float(np.abs(v[mm] - ys).mean())
        pers = r["MAE persistence (last 30 min)"]; r["skill vs persistence"] = 1 - r["MAE model"] / pers
        best_naive = min(r[f"MAE {k}"] for k in base_preds); r["skill vs best naive"] = 1 - r["MAE model"] / best_naive
        r["P10-P90 coverage"] = float(((ys >= lo[mm]) & (ys <= hi[mm])).mean())
        hot = ys >= np.quantile(ys, 0.9)                          # the busiest 10% of half-hours
        r["MAE model (busiest 10%)"] = float(np.abs(mu[mm][hot] - ys[hot]).mean()); r["MAE persistence (busiest 10%)"] = float(np.abs(base_preds["persistence (last 30 min)"][mm][hot] - ys[hot]).mean())
        rows.append(r)
    df = pd.DataFrame(rows).set_index("pool"); res["splits"][label] = df.round(4).to_dict(orient="index"); return df
val = table((day >= 100) & (day < 130), "validation days 100-129")
test = table(day >= 130, "TEST days 130+")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print("VALIDATION"); print(val[["mean_demand_gpus", "MAE model", "MAE persistence (last 30 min)", "MAE same time yesterday", "skill vs persistence", "skill vs best naive", "P10-P90 coverage"]].round(3).to_string())
print("\nTEST (held out)"); print(test[["mean_demand_gpus", "MAE model", "MAE persistence (last 30 min)", "MAE same time yesterday", "skill vs persistence", "skill vs best naive", "P10-P90 coverage", "MAE model (busiest 10%)", "MAE persistence (busiest 10%)"]].round(3).to_string())
tag = f"{int(H/60)}min"
Path(f"analysis/rl/demand_forecast_{tag}.json").write_text(json.dumps(res, indent=1)); test.round(4).to_csv(f"analysis/rl/demand_forecast_{tag}_test.csv")
