# Proof pack: is it connected, is the RL trained, is the data used meaningfully?

Everything below was produced by running the real system; numbers come from `analysis/proof/*.json`, re-generate with the commands at the end.

## 1. Front end and back end are connected
- Browser at `http://127.0.0.1:8081/index.html` talked to the FastAPI backend at `http://127.0.0.1:8010`; the page was driven by the **trained RL policy** (policy box shows "Learned (RL)").
- The browser recorded **7 HTTP calls** to the API and **1 WebSocket** (`/runs/eac66cec0e-rl_ppo/stream?start=0&speed=600&paused=false`): **196 frames, 3.4 MB**, carrying 5,764 job arrivals, 5,653 scheduler starts, 157 finishes, 28 preemptions and 194 board snapshots.
- The **backend's own access log** shows the same requests (same run id `eac66cec0e-rl_ppo`):
```
INFO:     127.0.0.1:49239 - "GET /presets HTTP/1.1" 200 OK
INFO:     127.0.0.1:49238 - "GET /meta HTTP/1.1" 200 OK
INFO:     127.0.0.1:49239 - "POST /whatif HTTP/1.1" 200 OK
INFO:     127.0.0.1:49275 - "GET /runs/eac66cec0e-rl_ppo/state?t=0 HTTP/1.1" 200 OK
INFO:     127.0.0.1:49276 - "WebSocket /runs/eac66cec0e-rl_ppo/stream?start=0&speed=600&paused=false" [accepted]
INFO:     127.0.0.1:49281 - "POST /whatif HTTP/1.1" 200 OK
INFO:     127.0.0.1:49289 - "GET /meta HTTP/1.1" 200 OK
```
- The in-app **Backend link** panel shows these counters live (server, transport, run id, batches, events, "last data n s ago").
- Automated: 22/22 browser checks on WebSocket and on polling (`server-room/tests/e2e/live-flow.mjs`), including: the engine snapshot equals the backend `/state` at the same time, and every temperature shown over 3 s is a value the backend sent for that board.

## 2. The RL model is trained (and what that did and did not buy)
- `models/ppo_u6_shuf_s12/best.zip`: 2,543,724 bytes, sha256 `65fc879e86221203…`, **208,402 parameters**. Trained 1,200,000 PPO steps on 8 parallel environments in 404 s, after behaviour-cloning the hint rule on 150 windows. **Candidate slots are randomly permuted at every decision, so slot position carries no information and the network has to read the job features.** 4 validation checks (days 118-124); training windows were days 45-115 only. Three seeds were trained (validation 0.348 / 0.357 / 0.362); the served one had the best validation score, chosen before any test number was seen.
- **Held-out test (days 130-172, six 3-day windows, never used for training or checkpoint choice), queue time relative to priority-FIFO (lower is better):**

| Policy | HP wait (h) | HP p95 (h) | Spot wait (h) | Queue-time ratio |
|---|---|---|---|---|
| priority FIFO | 7.89 | 26.7 | 39.2 | 1.000 |
| backfill | 6.16 | 25.0 | 29.3 | 0.843 |
| **RL, untrained (same network, random weights)** | 4.57 | 28.4 | 16.1 | 0.571 |
| **RL, trained** | 3.24 | 21.4 | 16.5 | 0.451 |
| shortest predicted job (rule) | 2.93 | 18.6 | 22.8 | 0.468 |
| oracle with true durations (unattainable) | 1.57 | 7.3 | 12.1 | 0.284 |

- **Control (this is the test that matters):** with slot order hidden, the same network with random weights scores 0.57 here and the trained one 0.45. On all 17 held-out windows (`analysis/rl/rl_shuffle_eval.json`): random valid choice 0.602, random-weights network 0.574, trained seeds 0.509-0.513, hint rule 0.509. So training matters and reaches rule-level quality. An earlier version with candidates pre-sorted by the hint hid this: even random weights scored the same as the trained network (0.452 vs 0.455), which would have made the RL meaningless.
- **What the trained agent does** (day-130 window, 2,160 real choices between startable jobs): it skips the queue head in **67.0%** of them and, when it skips, picks a shorter-predicted job in **94.5%** (untrained network: 70.0%).
- **Honest verdict:** RL beats FIFO, priority-FIFO and backfill and **ties the simple "shortest predicted job" rule** on queue time (about 0.51-0.52 vs 0.51 over 17 held-out windows; slightly ahead on what-if windows, 0.422 vs 0.444, and on held-out BurstGPT shapes, 0.583 vs 0.596). It keeps the lowest spot waits and does about 30% fewer preemptions than the rule; HP tail waits are slightly worse. It does not beat the rule decisively. Full tables and caveats: `analysis/rl/README.md`.
- Chart: `rl-training-proof.png`. Live: in the room, press **Compare policies** (Policy scoreboard) to have the backend run every policy, including the trained one, on the current scenario:

| Live scoreboard, held-out day 130 | HP wait (h) | HP p95 (h) | Spot wait (h) |
|---|---|---|---|
| fifo | 10.48 | 22.0 | 14.0 |
| priority_fifo | 7.08 | 16.6 | 30.7 |
| backfill_median | 4.15 | 15.3 | 22.2 |
| sjf_hint | 3.50 | 26.6 | 24.1 |
| rl_ppo | 4.09 | 28.7 | 12.3 |
| sjf_oracle | 1.17 | 7.7 | 12.0 |

## 3. The data is used in the way the project describes
**"Make the invisible visible":** the raw trace has columns `job_name, organization, gpu_model, cpu_request, gpu_request, worker_num, submit_time, duration, job_type` and **no queue, start, wait or eviction data**. The backend reconstructs them and the room shows them.

**One job, end to end.** The room's inspector showed job **311609** on **GPU-08** (Board 8 · NVIDIA A10 · slice 2 of 6 · 648 nodes (648 GPUs)):

| Layer | What it holds for this job |
|---|---|
| Raw file `data/alibaba-2026-spot-gpu/job_info_df.csv` | `{"job_name": "311609", "organization": "13", "gpu_model": "A10", "cpu_request": "4.0", "gpu_request": "1.0", "worker_num": "1", "submit_time": "11238896.0", "duration": "911.0", "job_type": "HP"}` |
| Harmonised `harmonized/alibaba/jobs.parquet` | pool `nvidia_a10`, `high_priority`, submit 11238896 s, duration 911 s (source row 374,944) |
| Simulator feed (run `eac66cec0e-rl_ppo`) | arrive t=6896s; start t=6896s on node 955, board 8; finish t=7807s (simulated wait 0s) |
| 3D room | board 8 = "GPU-08", "Assigned job 311609" |

Checks: raw submit 130.080 days = window start day 130 + 6896 s; raw duration 911.0 s = feed `service_s` 911 s = finish - start.

| Source | Used? | How |
|---|---|---|
| Alibaba jobs (466,867) | **Yes** | every job in the replay window; trains the runtime-hint model (finished jobs before day 40) and the demand forecaster (days before 100); RL training windows |
| Alibaba nodes (4,278) | **Yes** | the cluster, 6 GPU-model pools, scaled to ~85% offered load (a10 3889, a100 290, a800 11, h800 14, series1 861, series2 28 simulated nodes) |
| Thermal archive (11.9M readings -> 45 profiles) | **Yes, as a proxy** | measured H100 profiles -> board temperature and power; labelled as proxy, never claimed for Alibaba hardware |
| GPU pricing | **Yes, for the simulated cloud overflow** | price tiers anchored to the offers data (premium = cheapest H100-80GB offer, standard = cheapest L40S); no Alibaba GPU has an exact price match, so the tiers are labelled assumptions and cloud assignments are simulated, never observed |
| BurstGPT (10.6M requests) | **Yes** | hourly arrival-shape profiles for what-ifs and RL training (traces 1-2); trace 3 is held out and used only for testing |

## 4. What this does NOT prove (read before presenting)
- Waits, placements, evictions and failures are **simulated** under stated assumptions; the trace itself has no ground truth for them.
- Temperatures/power are an **H100-based proxy**; the 80 C alert threshold and the +35 C cooling-fault size are **assumptions**.
- The displayed 30-minute **utilisation** forecast is **persistence**: a survival projection and a learned state forecaster were both measured and neither beat it (`analysis/rl/state_forecast_*.json`). The **demand forecast** (GPUs requested in the next 30 min, with a P10-P90 band) is learned: 18% lower error than rate-persistence on held-out days, ~82% band coverage, little skill on the A10 pool, and sudden spikes are not anticipated.
- RL **ties** the best simple rule (it does not beat it decisively); three seeds, 3-day windows. Cloud spend is a simulated rental cost, charged for the full predicted job at start.
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
