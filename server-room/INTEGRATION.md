# Backend integration: 3D room driven by the scheduling backend

The room now replays real results from the FastAPI scheduler (`scheduler/api.py`). The Blender GPU model, materials,
fan animation, camera and layout are unchanged; the scene reads one engine object, and that object is now fed by the backend.

## Run it
```bash
# terminal 1 (repo root) - backend
conda activate htb && uvicorn scheduler.api:app --port 8000
# terminal 2 (server-room/)
npm ci && npm run build && npm run preview        # http://127.0.0.1:8081
```
URL options: `?api=http://host:8000` `&preset=live_demo|node_failure|cooling_fault|spike_and_failure` `&policy=priority_fifo|fifo|backfill_median|sjf_hint|rl_ppo`
`&transport=polling` (force the polling fallback) `&mode=synthetic` (the original synthetic demo) `&mode=backend` (never fall back).
If the backend is unreachable, `auto` shows the synthetic demo **labelled as such** with the reason in the footer; `mode=backend` shows an error and no data.

## Data flow
`POST /whatif` (scenario + policy) -> run id -> `GET /runs/{id}/state?t=` (instant catch-up) -> `WS /runs/{id}/stream` (paced batches; controls
`pause|resume|speed|seek`; polling over `GET /runs/{id}/events` if WebSocket is unavailable) -> `replay-engine.js` -> `snapshot()` -> scene + overlay.
Files: `backend-client.js` (transport), `replay-engine.js` (state), `scenario-ops.js` (what-if parameter edits), `ui/backend-panels.jsx`, `integration.css`.

## What is on screen, and where it comes from
| On screen | Source |
|---|---|
| 24 boards = 4 pods x 6 slices of node sets | `meta.display` (a board is a *slice of nodes* of a pool, not one physical GPU). Pods: A100, A10, H800, series 1; A800 and series 2 run but are not drawn (see Pools panel) |
| Board colour/status (idle, running, cooling, failed) | backend snapshot `boards[i].status` |
| Utilisation, temperature, power, 30-min forecast | backend snapshot. **Temperature/power are a proxy** from measured H100 profiles (labelled in UI); no Alibaba thermal data exists. Power is withheld for the A10 pod |
| Overheating (pulsing red ring, alert chip) | backend `thermal_alert` events; the 80 C threshold is an **assumption** above every measured reading |
| Incoming jobs, queue positions (#1..#5, chips at the gateway) | backend `queue_head` of the selected board's pool, in the policy's ordering (for `rl_ppo` that is arrival order) |
| Routing particles | one per backend `start` event (visual flight time only); red reverse particle for every eviction. >48 simultaneous are counted, not hidden |
| Assigned job + progress | latest `start` on the board; progress = elapsed / `service_s` |
| Completed, queued, arrivals/min | backend counters |
| Failures | backend `fail`/`repair` events; evicted jobs return to the queue |

## What-if controls -> real backend scenarios
Every control only edits scenario parameters and asks the backend to recompute; the new run is identical to the old one up to the click (tested), so the scene does not jump.
| Control | Scenario parameter |
|---|---|
| Add job | `injected_jobs` (1 GPU, HP, 15 min) into the selected pool |
| Job burst | `burst` x4 for 30 simulated minutes |
| Fail GPU / Repair | `failures` (fails the **node slice** behind the board; repair sets `repair_after_h`) |
| Cooling fault | `cooling_fault` +35 C (assumed size) |
| Policy | re-run with the chosen policy (FIFO, priority, backfill, shortest-predicted, learned RL) |
| Scenario | preset from `GET /presets` |
Speed 1x = 10 simulated minutes per real second.

## Honesty rules (enforced by tests)
The engine contains no random numbers and no thermal or scheduling arithmetic; displayed temperatures are always values the backend sent for that board;
`mode=backend` with no backend shows no data. Known limits: the 30-minute forecast is persistence (a survival projection was tested and was worse, see `meta.forecast`);
waits and placements are simulated; one-day windows (a run is ~5-10 MB).

## Tests
`npm test` (engine/client/scenario-ops against the real exported feed) - `npm run test:e2e` (real backend + headless Chrome, 22 checks; `-- --transport=polling` for the fallback) -
`node tests/e2e/offline.mjs` - `npm run test:model` (Blender GLB loads and renders). Screenshots: `analysis/visualization/integration/`.
