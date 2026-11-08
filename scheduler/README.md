# GPU Scheduling Lens: scheduler package

Node-level replay simulator for the Alibaba GPU trace (466,867 jobs, 6 GPU-model pools, 4,278 nodes).
Environment: `conda env create -f environment.yml` (or `conda activate htb`).

```bash
python -m scheduler.run_baselines --start-day 90 --days 5 --load 0.85   # compare policies on a window
python -m scheduler.make_samples --start-day 90 --hours 6                # NDJSON runs for the frontend
python -m scheduler.whatif --preset growth_30 --start-day 90            # what-if scenario under every policy
uvicorn scheduler.api:app --port 8000                                    # frontend API, docs at /docs
python -m pytest tests -q                                                # 36 tests
```

## What-ifs (`whatif.py`)
A scenario is parameters + seed (`scenario_id` = hash), so any run is reproducible and every policy sees the
identical workload. Knobs: `arrival_mult`, `burst {start_h,duration_h,mult}`, `spot_share`, `duration_mult`,
`capacity` (one factor or per pool), `resume_preempted`. Presets: baseline, growth_30, demand_halves, burst_3x,
spot_heavy, longer_jobs, lose_a10_capacity, capacity_plus_20.
**Limit:** perturbations change jobs *arriving in the window*; the carry-over (already running at window start,
which holds most GPU-seconds) is left as observed. So "demand falls" understates relief; capacity changes act on everything.

## API (`api.py`)
`GET /meta` pools, policies, assumptions · `GET /presets` · `POST /whatif {preset|scenario, policies, snapshot_s}`
returns metrics + a comparison table + run ids · `GET /runs/{id}/events?t_from&t_to&types` NDJSON slice ·
`GET /runs/{id}/timeline` per-pool series · `WS /runs/{id}/stream?speed=3600` paced playback
(`{type:'batch', t_from, t_to, items:[...]}` then `{type:'end'}`). Event format: `schema/events.schema.json`.
NaN metrics (e.g. spot wait with no spot jobs) are sent as `null`. Windows are capped at 7 days.

## Model (all choices are in `assumptions.yaml`, tagged observed / calculated / assumption)
- **Pool** = all nodes of one GPU model (`pools.yaml`). Jobs are pinned to their recorded model.
- **Node-level packing:** whole-GPU requests need that many free GPUs on *one* node; fractional requests share a GPU.
- **Preemption:** HP may evict spot; evicted work restarts from scratch (`resume=True` to switch).
- **Capacity scaling:** whole nodes added/removed per pool so offered load = `--load` (default 0.85).
- **Warm start:** a window begins with jobs submitted earlier that are still running (assumed zero historic wait).
  Needed because ~5% of jobs hold ~95% of GPU-seconds.
- **Hidden durations:** only `sjf_oracle` and `backfill_oracle` see true durations (ceilings, `realistic=False`).

## Files
`data.py` loaders, workloads, cluster scaling · `sim.py` numba core · `policies.py` baselines ·
`metrics.py` · `export.py` + `schema/events.schema.json` frontend feed · `samples/` example runs.
