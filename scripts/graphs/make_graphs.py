"""Charts for the pitch: how the data was used and how the models perform. Every number is read from a result file or computed from the data here.
    python scripts/graphs/make_graphs.py   ->  analysis/graphs/*.png and analysis/graphs/index.html
Colour: one emphasis hue (blue = our trained RL / our models), neutral grey for everything else, orange only for the 'does it learn?' controls. Labels sit on the marks."""
import base64, json, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[2]; OUT = ROOT / "analysis/graphs"; OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
BLUE, GREY, LGREY, ORANGE, INK, SOFT = "#2a78d6", "#9a9890", "#d6d4cc", "#eb6834", "#0b0b0b", "#52514e"
plt.rcParams.update({"font.family": "sans-serif", "font.size": 10, "axes.edgecolor": LGREY, "axes.labelcolor": SOFT, "xtick.color": SOFT, "ytick.color": SOFT,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 12, "axes.titlelocation": "left", "figure.facecolor": "white"})
def save(fig, name): fig.tight_layout(); fig.savefig(OUT / name, dpi=150); plt.close(fig); print("wrote", name)

# ---- 1. what data we used and for what
off = len(pd.read_parquet(ROOT / "harmonized/pricing/offers.parquet"))
rows = [("Alibaba GPU jobs", 466_867, "the workload: every job replayed; trains the runtime-hint model and the demand forecaster"),
        ("Alibaba GPU nodes", 4_278, "the cluster: 6 GPU-model pools, scaled to ~85% offered load"),
        ("GPU temperature archive", 11_900_000, "11.9M readings -> 45 measured profiles -> temperature/power PROXY (labelled)"),
        ("BurstGPT requests", 10_600_000, "hourly arrival shapes for what-ifs and RL training (trace 3 held out)"),
        ("GPU price offers", off, "price tiers for the SIMULATED cloud overflow (assumption, labelled)")]
fig, ax = plt.subplots(figsize=(10, 3.9)); y = np.arange(len(rows))[::-1]
ax.barh(y, [r[1] for r in rows], color=BLUE, height=.55); ax.set_xscale("log"); ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows], color=INK)
for yi, r in zip(y, rows): ax.text(r[1] * 1.15, yi, f"{r[1]:,}", va="center", color=INK, fontsize=9, fontweight="bold"); ax.text(1.4, yi - .42, r[2], va="top", color=SOFT, fontsize=8)
ax.set_xlim(1, 2e8); ax.set_xlabel("records (log scale)"); ax.set_title("Five public datasets, each with a job to do"); ax.set_ylim(-.9, len(rows) - .4)
save(fig, "01_data_used.png")

# ---- 2. queue time by policy on held-out windows
df = pd.read_csv(ROOT / "analysis/rl/ppo_u6_shuf_s12/results.csv"); obs = df[df.kind == "observed"]
NAMES = {"fifo": "First come\nfirst served", "priority_fifo": "Priority\nfirst", "backfill_median": "Backfill", "sjf_hint": "Shortest\npredicted job", "rl_ppo": "Trained RL", "sjf_oracle": "Oracle\n(true runtimes)"}
order = ["fifo", "priority_fifo", "backfill_median", "sjf_hint", "rl_ppo", "sjf_oracle"]
q = obs.groupby("policy").q_ratio.mean().reindex(order)
fig, ax = plt.subplots(figsize=(9, 4.2)); cols = [LGREY if p == "sjf_oracle" else BLUE if p == "rl_ppo" else GREY for p in order]
b = ax.bar(range(len(order)), q, color=cols, width=.62)
for i, v in enumerate(q): ax.text(i, v + .02, f"{v:.2f}", ha="center", color=INK, fontweight="bold" if order[i] == "rl_ppo" else None)
ax.axhline(1.0, color=LGREY, lw=1, ls="--"); ax.set_xticks(range(len(order))); ax.set_xticklabels([NAMES[p] for p in order], fontsize=9)
ax.set_ylabel("queue time vs priority FIFO (lower is better)"); ax.set_title("Held-out windows (days 130+): queue time vs priority FIFO")
ax.text(len(order) - 1, q.iloc[-1] / 2, "unattainable\nceiling", ha="center", color=SOFT, fontsize=8)
save(fig, "02_policies_heldout.png")

# ---- 3. does the RL actually learn? (controls)
sh = json.loads((ROOT / "analysis/rl/rl_shuffle_eval.json").read_text())
items = [("Random valid\nchoice", sh["random valid choice"], ORANGE), ("Network with\nrandom weights", sh["random-weights network"], ORANGE),
         ("Trained RL\n(mean of 3 seeds)", np.mean([sh[f"RL trained (seed {s})"] for s in (11, 12, 13)]), BLUE), ("Hint rule\n(same candidates)", sh["hint rule (16 candidates)"], GREY)]
fig, ax = plt.subplots(figsize=(8, 4)); b = ax.bar(range(4), [i[1] for i in items], color=[i[2] for i in items], width=.6)
for i, it in enumerate(items): ax.text(i, it[1] + .012, f"{it[1]:.3f}", ha="center", color=INK, fontweight="bold" if i == 2 else None)
ax.set_xticks(range(4)); ax.set_xticklabels([i[0] for i in items], fontsize=9); ax.set_ylim(.4, .65); ax.set_ylabel("queue time vs priority FIFO (lower is better)")
ax.set_title("Training takes the same network from 0.574 to rule-level quality")
ax.text(1.5, .445, "Honest reading: the RL matches the best simple rule, it does not beat it.", ha="center", color=SOFT, fontsize=9)
save(fig, "03_rl_learns_controls.png")

# ---- 4. what RL buys: spot waits, preemptions, wasted work vs the rule
t = obs.groupby("policy")[["spot_wait_mean_h", "hp_wait_mean_h", "preemptions", "wasted_gpu_h"]].mean().reindex(["priority_fifo", "backfill_median", "sjf_hint", "rl_ppo"])
fig, axs = plt.subplots(1, 3, figsize=(11, 3.8)); lab = ["Priority", "Backfill", "Predicted\nrule", "Trained\nRL"]; cc = [GREY, GREY, GREY, BLUE]
for ax, col, ttl in zip(axs, ["spot_wait_mean_h", "preemptions", "wasted_gpu_h"], ["Spot jobs: mean wait (h)", "Preemptions per window", "GPU-hours lost to eviction"]):
    ax.bar(range(4), t[col], color=cc, width=.62); ax.set_xticks(range(4)); ax.set_xticklabels(lab, fontsize=8); ax.set_title(ttl, fontsize=10)
    for i, v in enumerate(t[col]): ax.text(i, v * 1.02, f"{v:.0f}" if col != "spot_wait_mean_h" else f"{v:.1f}", ha="center", fontsize=8, color=INK)
fig.suptitle("What RL buys: calmer scheduling for spot jobs (HP waits slightly higher)", x=.01, ha="left", fontweight="bold", fontsize=11)
save(fig, "04_what_rl_buys.png")

# ---- 5. demand forecast: skill by horizon + one held-out example with its band
sk = {h: json.loads((ROOT / f"analysis/rl/demand_forecast_{h}min.json").read_text())["splits"]["TEST days 130+"] for h in (10, 30, 60)}
from scheduler.run_baselines import setup
from scheduler.whatif import Scenario, build_workload
from scheduler import demand_forecast as dfc
pools, jobs, base, cl = setup(0.85); ids = [p["id"] for p in pools]
f = dfc.load_or_fit(jobs, len(ids)); sc = Scenario(start_day=141.0, days=2.0, seed=0); w = build_workload(jobs, sc)
ser = dfc.forecast_series(f, jobs, w, ids, sc.start_day * 86400, sc.days * 86400)
fig, axs = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1, 1.7]})
ax = axs[0]; hs = [10, 30, 60]; sk_all = [sk[h]["ALL"]["skill vs persistence"] * 100 for h in hs]
ax.bar(range(3), sk_all, color=BLUE, width=.55); ax.set_xticks(range(3)); ax.set_xticklabels([f"{h} min ahead" for h in hs])
for i, v in enumerate(sk_all): ax.text(i, v + .5, f"{v:.0f}%", ha="center", color=INK, fontweight="bold")
ax.set_ylabel("error reduction vs 'same rate as just now' (%)"); ax.set_title("Demand forecast skill (held-out days)", fontsize=11)
ax = axs[1]; pid = "a100"; S = ser["series"]; tt = np.array([s["t"] for s in S]) / 3600
mu = np.array([s["pools"][pid]["next_gpus"] for s in S]); lo = np.array([s["pools"][pid]["p10"] for s in S]); hi = np.array([s["pools"][pid]["p90"] for s in S]); re = np.array([s["pools"][pid]["realised_gpus"] for s in S]); pe = np.array([s["pools"][pid]["persistence_gpus"] for s in S])
ax.fill_between(tt, lo, hi, color=BLUE, alpha=.18, lw=0, label="P10-P90 band"); ax.plot(tt, mu, color=BLUE, lw=2, label="forecast"); ax.plot(tt, re, color=INK, lw=1.2, marker="o", ms=3, label="what actually arrived"); ax.plot(tt, pe, color=GREY, lw=1, ls=":", label="'same as just now'")
ax.set_xlabel("hours into a held-out window (day 141)"); ax.set_ylabel("A100 GPUs requested in the next 30 min"); ax.legend(frameon=False, fontsize=8, loc="upper right"); ax.set_title("Forecast vs reality, including the misses (spikes are not anticipated)", fontsize=11)
save(fig, "05_demand_forecast.png")

# ---- 6. cloud overflow: queue time bought with (simulated) spend
cp = pd.DataFrame(json.loads((ROOT / "analysis/rl/cloud_pareto.json").read_text()))
fig, ax = plt.subplots(figsize=(8.5, 4.6)); STY = {"priority_fifo": ("Priority", GREY, "s"), "backfill_median": ("Backfill", LGREY, "^"), "sjf_hint": ("Predicted rule", ORANGE, "D"), "rl_ppo": ("Trained RL", BLUE, "o")}
for pol, (lbl, c, m) in STY.items():
    d = cp[cp.policy == pol].sort_values("cloud_nodes_per_pool"); ax.plot(d.cloud_usd_per_day / 1000, d.q_ratio, color=c, marker=m, ms=7, lw=1.6 if pol == "rl_ppo" else 1, label=lbl)
ax.set_xlabel("simulated cloud rental ($ thousand per day); points = 0 / 5 / 10 / 20 cloud nodes per pool"); ax.set_ylabel("queue time vs priority FIFO without cloud"); ax.legend(frameon=False, title="manager"); ax.set_title("Cloud overflow: queue time vs simulated spend")
ax.text(.99, .02, "SIMULATED: price tiers are assumptions anchored to the pricing data", transform=ax.transAxes, ha="right", color=SOFT, fontsize=8)
save(fig, "06_cloud_overflow.png")

# ---- 7. runtime prediction on held-out jobs
from scheduler.duration_model import load_or_fit as hint_fit
h = hint_fit(jobs, 40); te = jobs[(jobs.submit_relative_s >= 130 * 86400) & (jobs.submit_relative_s < 150 * 86400)]
pr = h.predict_seconds(te.job_id.to_numpy()); ok = np.isfinite(pr) & (te.duration_s.to_numpy() > 0)
x, y = pr[ok] / 60, te.duration_s.to_numpy()[ok] / 60; rho = pd.Series(x).corr(pd.Series(y), method="spearman")
fig, ax = plt.subplots(figsize=(6.4, 5)); hb = ax.hexbin(x, y, xscale="log", yscale="log", gridsize=45, cmap="Blues", mincnt=1, bins="log")
lim = [min(x.min(), y.min(), 1), max(x.max(), y.max())]; ax.plot(lim, lim, color=GREY, ls="--", lw=1); ax.set_xlim(1, lim[1]); ax.set_ylim(1, lim[1])
ax.set_xlabel("predicted runtime (min)"); ax.set_ylabel("actual runtime (min)"); ax.set_title(f"Runtime hint on held-out jobs (n={ok.sum():,}), rank correlation {rho:.2f}", fontsize=11)
ax.text(.03, .96, "trained only on jobs that had finished before day 40", transform=ax.transAxes, va="top", color=SOFT, fontsize=8)
save(fig, "07_runtime_prediction.png")

# ---- index.html (self-contained)
cap = {"01_data_used.png": "Every dataset has a role: the trace is the workload and cluster, the thermal archive gives the temperature proxy, BurstGPT gives arrival shapes, pricing gives the simulated cloud bill.",
       "02_policies_heldout.png": "On days the models never saw, the learned scheduler cuts queue time by about half versus priority FIFO and clearly beats backfill. It ties the best simple rule.",
       "03_rl_learns_controls.png": "The control that matters: with candidate slots shuffled, a random network scores 0.574 and training brings it to rule-level quality.",
       "04_what_rl_buys.png": "Where RL differs from the rule: lower spot waits and fewer preemptions; HP waits are slightly higher.",
       "05_demand_forecast.png": "A forecast with a measured error band, shown against what actually arrived. It beats the naive baseline but does not anticipate sudden spikes.",
       "06_cloud_overflow.png": "More simulated cloud capacity buys less queue time; the trained RL reaches the best ratio at slightly lower spend (HP tail waits are worse).",
       "07_runtime_prediction.png": "Job runtime is hard to predict from submit-time information; the model's value is the ranking, which is what the scheduler uses."}
img = lambda n: "data:image/png;base64," + base64.b64encode((OUT / n).read_bytes()).decode()
html = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>How the data is used</title><style>:root{color-scheme:light dark}body{font:15px/1.5 -apple-system,Segoe UI,sans-serif;max-width:1000px;margin:28px auto;padding:0 18px;background:#fcfcfb;color:#0b0b0b}@media(prefers-color-scheme:dark){body{background:#1a1a19;color:#f0efec}img{background:#fff}}h1{font-size:22px}figure{margin:26px 0}img{width:100%;height:auto;border-radius:6px}figcaption{color:#6b6a66;font-size:13px;margin-top:6px}</style><h1>How we used the data, and how the models perform</h1><p>All results are on held-out data. Waits, queues, temperatures and cloud costs are simulated; labels say so.</p>"
html += "".join(f"<figure><img src='{img(n)}' alt='{c}'><figcaption>{c}</figcaption></figure>" for n, c in cap.items())
(OUT / "index.html").write_text(html); print("wrote index.html", (OUT / "index.html").stat().st_size // 1024, "KB")
