# Does training with the combined layer (BurstGPT arrival shapes) help the RL scheduler?

Setup: `ppo_combined` = K=16, 256x256 network, 150 cloning windows, **60% of training episodes reshaped by BurstGPT trace 1/2 hourly arrival
shapes** (James's `integrated/workload_hourly.parquet`), 1.5M steps, seed 3. Control `ppo_k16` = same recipe **without** BurstGPT, 1.2M steps, seed 2.
Both evaluated on identical held-out scenarios: observed days >= 130 (17 windows) and the 4 burstiest 72 h shapes of **BurstGPT trace 3, never used in
training** (8 windows). Queue-time ratio vs priority-FIFO, lower is better (`results.csv`, `report.json` in each folder).

| Held-out set | control (no BurstGPT) | combined (BurstGPT) | shortest-predicted-job rule |
|---|---|---|---|
| observed windows | 0.580 | 0.575 | 0.506 |
| BurstGPT-trace-3 shapes | 0.644 | 0.640 | 0.586 |
| BurstGPT shapes, HP p95 wait (h) | 69.7 | 69.9 | 48.8 |
| BurstGPT shapes, spot wait (h) | 40.5 | 40.7 | 46.7 |

Verdict: **no measurable effect** (differences of 0.004-0.005, one seed each, different seeds/step counts). BurstGPT training neither helped nor hurt.
Both K=16 models are clearly better than the earlier 8-slot RL (0.647 on observed windows); that gain came from more candidate slots and the better
runtime hint, not from the combined data. RL beats FIFO and backfill but still loses to the shortest-predicted-job rule on the headline metric (it has lower spot waits).
Caveats: single seed; BurstGPT contributes only an arrival *shape* (no GPU, duration or clock information); pricing and thermal data are not used in the RL reward.
