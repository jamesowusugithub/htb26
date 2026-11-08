"""Trace ONE job from the raw dataset to the pixel: raw CSV -> harmonised parquet -> simulator feed -> what the 3D room showed."""
import json, sys, urllib.request
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[2]
live = json.loads((ROOT / "analysis/proof/live-run.json").read_text())
job = live["shown"]["jobIdInInspector"]; run = live["st1"]["runId"]; api = live["url"].split("api=")[1].split("&")[0]
from urllib.parse import unquote; api = unquote(api)
out = {"job_id_shown_in_ui": job, "ui_board": live["shown"]["gpu"], "ui_subtitle": live["shown"]["subtitle"], "run_id": run}

# 1. harmonised parquet (what the simulator loads) -> points back to the raw row
hz = pd.read_parquet(ROOT / "harmonized/alibaba/jobs.parquet")
row = hz[hz.job_id == job].iloc[0]
out["harmonised"] = {k: (None if pd.isna(row[k]) else (row[k].item() if hasattr(row[k], "item") else str(row[k])))
                     for k in ("raw__job_name", "raw__organization", "raw__gpu_model", "raw__gpu_request", "raw__worker_num", "raw__submit_time", "raw__duration",
                               "raw__job_type", "gpu_model_identifier", "priority_class", "gpu_request_recorded_count", "submit_relative_s", "duration_s",
                               "source_file", "source_row_number")}
# 2. the ORIGINAL file row
raw = pd.read_csv(ROOT / "data/alibaba-2026-spot-gpu" / Path(row.source_file).name, dtype=str, skiprows=lambda i: i not in (0, int(row.source_row_number) + 1) if False else None, nrows=None)
rr = raw[raw.iloc[:, 0] == row.raw__job_name] if row.raw__job_name in set(raw.iloc[:, 0]) else raw.iloc[[int(row.source_row_number) - 1]]
out["raw_csv_columns"] = list(raw.columns)
out["raw_csv_row"] = rr.iloc[0].to_dict()
# 3. backend feed events for the same job in the exact run the UI displayed
txt = urllib.request.urlopen(f"{api}/runs/{run}/events").read().decode().splitlines()
ev = [json.loads(l) for l in txt]; mine = [e for e in ev if e.get("job") == job]
out["feed_events"] = [{k: v for k, v in e.items() if k in ("type", "t", "pool", "board", "node", "gpu_slots", "gpus", "priority", "service_s", "wait_s", "attempt", "cause", "warm", "duration_s")} for e in mine]
out["raw_columns_vs_feed_fields"] = {"raw_has_wait_or_start_time": any("wait" in c.lower() or "start" in c.lower() for c in raw.columns),
                                      "feed_adds": ["wait_s (simulated)", "start time + node + gpu_slots (simulated placement)", "board temperature/power (H100 proxy)"]}
(ROOT / "analysis/proof/lineage.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps(out, indent=1, default=str))
