# The Restaurant — backend/frontend contract (frozen T1)

Backend is authoritative. Frontends only render events; they never decide scheduling.
Sim is tick-based: 1 tick = 1 simulated cycle (= 1 simulated second). Package: `backend/app/rest/`.
All REST under `/api/rest`. WebSocket: `/ws/rest/{run_id}`.

## Events (every event: `seq:int` strictly increasing per run, `t:int` tick, `type:str`)

| type | extra fields |
|---|---|
| JOB_ARRIVED | job{id, priority: low|medium|high|vip, vram_gb, compute_units, duration_s, deadline_t, splittable, tiers:[premium|standard|cloud]} |
| DECISION | job_id, action: assign|cloud|hold|split, target_gpu_ids:[str], scheduler: rl|fifo|priority|fallback_heuristic, factors{queue_len, deadline_slack, pred_temp, cost}, mask_summary{valid:int,total:int} |
| ALLOCATION_REJECTED | job_id, gpu_id, reason: memory|tier|thermal|down |
| JOB_STARTED | job_id, gpu_ids:[str], eta_t |
| JOB_COMPLETED | job_id, on_time:bool, wait_s, cost |
| JOB_FAILED | job_id, reason, requeued:bool |
| GPU_TELEMETRY | gpu_id, temp, util, vram_used_gb, health: normal|warning|critical|down (every tick, every GPU) |
| THERMAL_WARNING | gpu_id, level: warning|critical, temp |
| GPU_DISABLED / GPU_RESTORED | gpu_id |
| METRICS | completed, waiting, received, avg_wait_s, p95_wait_s, slo_rate, avg_util, cost, thermal_incidents, starved |

GPU ids: `premium-0..`, `standard-0..`, `cloud-0` (cloud pool is one logical GPU entry with large capacity).
Config (`GET /config`): `{nodes:[{id, gpus:[{id, tier, vram_gb, compute}]}], thresholds:{warning:75, critical:85}, overflow_threshold:10, scheduler}`.
Default demo: 2 premium (H100 80GB), 3 standard (A100 40GB), cloud pool.

## REST (JSON)
- `POST /runs` {seed:int, scenario: normal|spike|failure, scheduler: rl|fifo|priority, config?} -> {run_id}
- `GET /runs/{id}/snapshot` -> full state {t, gpus[], queue[], running[], metrics, last_seq, scheduler} (reconnect resync)
  - (additive) each `running[]` entry: `{job_id, gpu_ids, eta_t, start_t, job}` where `job` has the same shape as the JOB_ARRIVED `job` payload, so a resynced UI can rebuild priority / vram / deadline.
- `POST /runs/{id}/{start|pause|reset}`; `POST /runs/{id}/speed` {speed:0.5..16}; `POST /runs/{id}/scheduler` {scheduler}
- `POST /runs/{id}/job` {…job fields, optional} ; `/spike` {n:int=12}; `/vip`; `/force_heat` {gpu_id, delta:+20}; `/disable_gpu` {gpu_id}; `/restore_gpu` {gpu_id}
  - (additive) `/force_heat` immediately emits one `GPU_TELEMETRY` for that GPU (new seq, current `t`, `health` = level at the new temp) and pushes it over WS, so a paused run updates at once. The `THERMAL_WARNING` transition is still emitted by the next tick.
- `POST /bench` {seeds:20, scenarios:[…]} -> bench table (JSON + markdown)
- WS frames: `{seq_from, seq_to, t, events:[...]}`. Client dedupes by `seq`; on gap or reconnect, fetch `/snapshot`.

## Rules
- Scheduler label `rl` only when a trained checkpoint is loaded and acting; else `fallback_heuristic`, shown loudly in UI.
- Safety layer rejects: VRAM overflow, tier-incompatible, GPU down, predicted temp >= critical. Rejection => ALLOCATION_REJECTED, state unchanged.
- Thermal default: active +2C/tick, idle -1C/tick (PRD FR-03, labelled illustrative); replaced by fitted params from `thermal_params.json` if present.
- (additive) Temps are clamped to a simulated throttle/shutdown ceiling `thermal_cap` (default 105C; simulated, not a real-hardware limit). `GPU_TELEMETRY.temp` never exceeds it.
- Same seed + same scenario => identical event log (test via hash).
