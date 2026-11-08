"""Generate the restaurant recordings from the real trace:  python scripts/restaurant/make_traces.py [--rl models/ppo_combined/best]"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from scheduler.run_baselines import setup
from scheduler.duration_model import load_or_fit
from scheduler import restaurant_export as rx
ap = argparse.ArgumentParser()
ap.add_argument("--rl", default=None); ap.add_argument("--K", type=int, default=16)
ap.add_argument("--start-day", type=float, default=145.0); ap.add_argument("--minutes", type=float, default=150.0); ap.add_argument("--nodes", type=int, default=5)
ap.add_argument("--out", default=str(ROOT / "restaurant/public/traces"))
a = ap.parse_args()
pools, jobs, base, cl = setup(0.85); hint = load_or_fit(jobs, 40)
model = None
if a.rl:
    from sb3_contrib import MaskablePPO
    model = MaskablePPO.load(a.rl, device="cpu")
recs = rx.make_recordings(jobs, pools, hint, model, a.K, a.start_day, a.minutes, 60.0, a.nodes)
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
for pol, rec in recs.items():
    (out / f"{pol}.json").write_text(json.dumps(rec, separators=(",", ":")))
    ev = rec["events"]; m = [e for e in ev if e["type"] == "METRICS"][-1]
    print(f"{pol:14s} events {len(ev):5d}  received {m['received']:3d} completed {m['completed']:3d} waiting {m['waiting']:3d}  avg wait {m['avg_wait_s']:5.1f} min  p95 {m['p95_wait_s']:5.1f} min  -> {out / (pol + '.json')}")
