# Proof pack: is it connected, is the RL trained, is the data used meaningfully?

Everything below was produced by running the real system; numbers come from `analysis/proof/*.json`, re-generate with the commands at the end.

## 1. Front end and back end are connected
- Browser at `http://127.0.0.1:8081/index.html` talked to the FastAPI backend at `http://127.0.0.1:8010`; the page was driven by the **trained RL policy** (policy box shows "Learned (RL)").
- The browser recorded **7 HTTP calls** to the API and **1 WebSocket** (`/runs/12fc9b35f8-rl_ppo/stream?start=0&speed=600&paused=false`): **203 frames, 3.3 MB**, carrying 5,783 job arrivals, 5,599 scheduler starts, 99 finishes, 37 preemptions and 201 board snapshots.
- The **backend's own access log** shows the same requests (same run id `12fc9b35f8-rl_ppo`):
```
INFO:     127.0.0.1:57327 - "GET /presets HTTP/1.1" 200 OK
INFO:     127.0.0.1:57326 - "GET /meta HTTP/1.1" 200 OK
INFO:     127.0.0.1:57327 - "POST /whatif HTTP/1.1" 200 OK
INFO:     127.0.0.1:57330 - "GET /runs/12fc9b35f8-rl_ppo/state?t=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:57331 - "WebSocket /runs/12fc9b35f8-rl_ppo/stream?start=0&speed=600&paused=false" [accepted]
INFO:     127.0.0.1:57352 - "POST /whatif HTTP/1.1" 200 OK
INFO:     127.0.0.1:57422 - "GET /presets HTTP/1.1" 200 OK
INFO:     127.0.0.1:57421 - "GET /meta HTTP/1.1" 200 OK
```
- The in-app **Backend link** panel shows these counters live (server, transport, run id, batches, events, "last data n s ago").
- Automated: 22/22 browser checks on WebSocket and on polling (`server-room/tests/e2e/live-flow.mjs`), including: the engine snapshot equals the backend `/state` at the same time, and every temperature shown over 3 s is a value the backend sent for that board.

## 2. The RL model is trained (and what that did and did not buy)
- `models/ppo_bc/best.zip`: 683,352 bytes, sha256 `b01d17dcb3401b96…`, **54,026 parameters**. Trained 2,000,000 PPO steps on 8 parallel environments in 210 s, after behaviour-cloning the hint rule on 60 windows; 8 validation checks (days 118-124). Training windows were days 45-115 only.
- **Held-out test (days 130-172, six 3-day windows, never used for training or checkpoint choice), queue time relative to priority-FIFO (lower is better):**

| Policy | HP wait (h) | HP p95 (h) | Spot wait (h) | Queue-time ratio |
|---|---|---|---|---|
| priority FIFO | 7.89 | 26.7 | 39.2 | 1.000 |
| backfill | 6.16 | 25.0 | 29.3 | 0.843 |
| **RL, untrained (same network, random weights)** | 5.82 | 25.9 | 17.9 | 0.737 |
| **RL, trained** | 4.76 | 23.7 | 17.8 | 0.634 |
| shortest predicted job (rule) | 4.34 | 32.3 | 23.9 | 0.626 |
| oracle with true durations (unattainable) | 1.57 | 7.3 | 12.1 | 0.284 |

- **Control:** the untrained network with identical architecture scores 0.74; training takes it to 0.63. So training matters, **but a large part of the gain comes from the candidate list being ranked by the runtime-hint model**: even random weights beat priority-FIFO.
- **What the trained agent does** (day-130 window, 2,702 real choices between startable jobs): it skips the queue head in **46.7%** of them, picks a shorter-predicted job in **86.8%** of those skips, and agrees with the hand-written hint rule **89.3%** of the time (untrained: 35.7%).
- **Honest verdict:** RL beats FIFO, priority-FIFO and backfill and has the lowest spot waits of the realistic policies, but it **ties, and does not beat, the simple "shortest predicted job" rule** on the headline metric. PPO fine-tuning barely moved the cloned policy (chart, left).
- Chart: `rl-training-proof.png`. Live: in the room, press **Compare policies** (Policy scoreboard) to have the backend run every policy, including the trained one, on the current scenario:

| Live scoreboard, held-out day 130 | HP wait (h) | HP p95 (h) | Spot wait (h) |
|---|---|---|---|
| fifo | 10.48 | 22.0 | 14.0 |
| priority_fifo | 7.08 | 16.6 | 30.7 |
| backfill_median | 4.15 | 15.3 | 22.2 |
| sjf_hint | 4.16 | 28.5 | 21.1 |
| rl_ppo | 4.78 | 21.1 | 11.9 |
| sjf_oracle | 1.17 | 7.7 | 12.0 |

## 3. The data is used in the way the project describes
**"Make the invisible visible":** the raw trace has columns `job_name, organization, gpu_model, cpu_request, gpu_request, worker_num, submit_time, duration, job_type` and **no queue, start, wait or eviction data**. The backend reconstructs them and the room shows them.

**One job, end to end.** The room's inspector showed job **311796** on **GPU-08** (Board 8 · NVIDIA A10 · slice 2 of 6 · 648 nodes (648 GPUs)):

| Layer | What it holds for this job |
|---|---|
| Raw file `data/alibaba-2026-spot-gpu/job_info_df.csv` | `{"job_name": "311796", "organization": "13", "gpu_model": "A10", "cpu_request": "4.0", "gpu_request": "1.0", "worker_num": "1", "submit_time": "11240726.0", "duration": "911.0", "job_type": "HP"}` |
| Harmonised `harmonized/alibaba/jobs.parquet` | pool `nvidia_a10`, `high_priority`, submit 11240726 s, duration 911 s (source row 374,968) |
| Simulator feed (run `12fc9b35f8-rl_ppo`) | arrive t=8726s; start t=8726s on node 955, board 8; finish t=9637s (simulated wait 0s) |
| 3D room | board 8 = "GPU-08", "Assigned job 311796" |

Checks: raw submit 130.101 days = window start day 130 + 8726 s; raw duration 911.0 s = feed `service_s` 911 s = finish - start.

| Source | Used? | How |
|---|---|---|
| Alibaba jobs (466,867) | **Yes** | every job in the replay window; trains the runtime-hint model (finished jobs before day 40); survival curves for the forecast; RL training windows |
| Alibaba nodes (4,278) | **Yes** | the cluster, 6 GPU-model pools, scaled to ~85% offered load (a10 3889, a100 290, a800 11, h800 14, series1 861, series2 28 simulated nodes) |
| Thermal archive (11.9M readings -> 45 profiles) | **Yes, as a proxy** | measured H100 profiles -> board temperature and power; labelled as proxy, never claimed for Alibaba hardware |
| GPU pricing | **No** | not connected to the live system yet |
| BurstGPT (10.6M requests) | **No** | not connected yet |

## 4. What this does NOT prove (read before presenting)
- Waits, placements, evictions and failures are **simulated** under stated assumptions; the trace itself has no ground truth for them.
- Temperatures/power are an **H100-based proxy**; the 80 C alert threshold and the +35 C cooling-fault size are **assumptions**.
- The displayed 30-minute forecast is **persistence**: a survival-based projection was measured to be worse.
- RL is **not better than the best simple rule**; one training seed; 3-day windows.
- Bug found and fixed while producing this pack: the API's `sjf_hint` policy had been using true durations (it equalled the oracle); the regression test `test_realistic_hint_policy_never_sees_true_durations` now guards it. Earlier research tables used a different code path and were not affected.

## Reproduce
```bash
uvicorn scheduler.api:app --port 8010                       # backend (port 8000 was already in use on this machine by another app)
cd server-room && npm run build && npx http-server dist -p 8081 -c-1
python scripts/proof/rl_proof.py                             # model facts, untrained control, decisions, chart
node server-room/tests/e2e/proof.mjs --api=http://127.0.0.1:8010 --web=http://127.0.0.1:8081
python scripts/proof/lineage.py && python scripts/proof/build_report.py
```
Open: http://127.0.0.1:8081/index.html?api=http://127.0.0.1:8010&preset=heldout_demo&policy=rl_ppo
