# GPU Scheduling Lens: scheduler package

Node-level replay simulator for the Alibaba GPU trace (466,867 jobs, 6 GPU-model pools, 4,278 nodes).
Environment: `conda env create -f environment.yml` (or `conda activate htb`).

```bash
python -m scheduler.run_baselines --start-day 90 --days 5 --load 0.85   # compare policies on a window
python -m scheduler.make_samples --start-day 90 --hours 6                # NDJSON runs for the frontend
python -m pytest tests -q                                                # 18 simulator tests
```

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
