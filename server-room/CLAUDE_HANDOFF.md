# Claude handoff: experimental 3D GPU fabric

## Scope and evidence

This branch extends the existing `thingraph/server-room` Three.js facility. It preserves the Blender GPU GLB, room geometry, materials, textures, four working GPU pods, camera controls, animations, WebSocket replay, 21st.dev UI components, scheduler code, and RL checkpoints.

The frontend build and 20 Node tests pass. The rack test mode was exercised in a browser. The Python scheduling backend could not run in the Codex environment because the documented `htb` Conda environment and its packages were unavailable. Do not treat the live backend path as browser-verified until the checks in this document pass in Claude's Python environment.

## Implemented work

### Functional rack fabric

- Six columns of 20 existing server racks now represent the six Alibaba scheduler pools: `a100`, `a10`, `h800`, `series1`, `a800`, and `series2`.
- These are aggregate pool views. A visible rack is not presented as one physical GPU or one simulated node.
- Rack beacons show `idle`, `busy`, `overloaded`, or `failed` state.
- Clicking any functional rack selects its pool and opens the existing device inspector.
- The pool inspector shows backend capacity, busy GPUs, utilisation, running jobs, high-priority and spot queues, largest free node, mapped node failures, and thermal proxy data where the backend has board mappings.
- Scheduler routes with a board ID continue to travel to the four GPU pods. Start events for pools without a displayed pod can travel to the corresponding rack aggregate.
- The remaining 240 room racks stay decorative because the backend has no resource identity for them.

### Local rack test mode

`?mode=rack-test&rackState=normal|stress|failure` supplies clearly labelled mock `rackPools` data. It exists only to exercise rack rendering and picking when the Python backend is unavailable. It does not call the live backend, alter production scheduling, or claim that its values are telemetry.

The browser test verified all six columns, H800 rack selection, the inspection panel, `idle`, `overloaded`, and `failed` state changes, and the absence of the backend-error banner. The wide evidence image is `analysis/visualization/functional-racks-test-wide.jpg`.

### Custom job submission

The backend-mode inspector now contains a small form for:

- GPU pool;
- GPU count;
- priority (`hp` or `spot`);
- expected duration in minutes.

The form does not schedule work in the browser. It calls `ReplayEngine.addJob()`, which adds one item to the scenario's existing `injected_jobs` array and requests a new backend run. The backend remains the source of queue order, placement, completion, failure, and requeue events. The room consumes those events through the existing replay engine.

### Forecast presentation

The selected GPU board now shows the backend's supported 30-minute capacity forecast:

- current simulated utilisation;
- chosen utilisation forecast;
- survival-based alternative projection;
- a presentation-only capacity-pressure band;
- historical forecast mean absolute error, when present;
- an explicit statement that no prediction interval is supplied.

The pressure band is calculated in the UI from forecast utilisation: moderate at 70% and high at 90%. It is not a backend prediction.

The backend does not currently predict job arrivals over 1–24 hours. It also does not supply uncertainty intervals. No arrival forecast or trained forecasting model was invented for this branch.

## Architecture and design decisions

### Three.js scene

`gpu-room.js` owns the scene integration. It discovers the original room objects by their `Rack N` names, calculates their bounds, and adds thin status beacons and transparent picking hitboxes without changing the rack geometry or materials. Six deterministic columns are used so the visual mapping remains stable.

The scene reads a snapshot from one engine surface on each animation frame. Rack colours come from `snapshot.rackPools`. Existing board rings, Blender GPU material colours, fans, queue chips, route particles, and camera behaviour remain in the same animation loop.

### ReplayEngine

`ReplayEngine` continues to adapt backend events to the scene's existing engine contract. It now:

- builds aggregate `rackPools` from backend run metadata and snapshot pool totals;
- lets the UI focus a pool as well as a board;
- retains the pool on visual route records so starts without a displayed board can route to a rack aggregate.

It does not perform scheduling or create thermal measurements.

### Rack fabric

`rack-fabric.js` is a pure mapping and aggregation module. It maps six backend pools to six non-overlapping 20-rack columns. It combines pool totals with mapped board failure and thermal fields where those fields exist. It derives utilisation and display state from supplied values.

The display state rules are:

- `failed`: capacity is zero, or every mapped node is down;
- `overloaded`: work is queued and utilisation is at least 90%, or no node has free GPU capacity;
- `busy`: busy GPUs are greater than zero;
- `idle`: none of the conditions above applies.

### React UI

`ui/overlay.jsx` remains the small React island mounted over the original Three.js viewer. It passes backend snapshots and callbacks to the panels. `ui/backend-panels.jsx` contains the aggregate rack inspector, custom-job form, and capacity forecast. Existing components and layout are reused.

## Backend integration contract

The frontend uses these existing endpoints through `backend-client.js`:

- `GET /health`: backend readiness.
- `GET /meta`: pools, policies, display mapping, assumptions, and thermal metadata.
- `GET /presets`: available scenarios.
- `POST /whatif`: creates scheduler runs for a scenario and one or more policies.
- `GET /runs/{run_id}`: run metadata.
- `GET /runs/{run_id}/state?t={seconds}`: replay catch-up state.
- `GET /runs/{run_id}/events?t_from={seconds}&t_to={seconds}`: NDJSON events for polling fallback.
- `GET /runs/{run_id}/timeline`: per-pool snapshot series. This branch does not yet chart it.
- `WS /runs/{run_id}/stream`: paced event batches. The client sends `pause`, `resume`, `speed`, and `seek` commands.

The existing `POST /whatif` body is shaped as follows:

```json
{
  "scenario": {
    "start_day": 90,
    "days": 1,
    "injected_jobs": [
      {
        "at_h": 1.000001,
        "pool": "a100",
        "gpus": 4,
        "priority": "hp",
        "duration_s": 1800
      }
    ]
  },
  "policies": ["priority_fifo"],
  "snapshot_s": 60
}
```

The exact scenario contains other existing fields. `scenario-ops.js` clones that scenario and appends the job just after the current playhead. The Python `_inject_jobs()` function validates the pool and priority, converts GPU count to scheduler units, and inserts the job into the workload. It uses IDs such as `INJ-001`.

Relevant event records include:

- `arrive`: job, pool, GPU request, priority, and duration;
- `start`: job, pool, node, optional displayed board, service duration, and attempt;
- `finish`: completed job and wait;
- `preempt`: interrupted job and cause;
- `fail` and `repair`: pool, node, and optional displayed board;
- `snapshot`: per-pool capacity, demand, queue and completion totals plus displayed board states;
- `thermal_alert`: proxy temperature threshold state.

The replay path is:

```text
custom form
  -> backend action in gpu-room.js
  -> ReplayEngine.addJob()
  -> scenario-ops.addInjectedJob()
  -> POST /whatif
  -> Python workload injection and scheduler run
  -> state + WebSocket or polling events
  -> ReplayEngine.snapshot()
  -> Three.js scene and React inspector
```

## Forecast details and limitations

The backend forecast horizon is 1,800 seconds. `scheduler/forecast.py` fits per-pool Kaplan-Meier survival curves from jobs submitted before the evaluation window. For a running job, it estimates the probability that the job survives for another 30 minutes. `scheduler/export.py` combines expected survivors with queued and recent demand to calculate `projection_util_pct`.

The exporter measured that this survival projection did not beat persistence. It therefore exposes current utilisation held constant as the chosen `forecast.util_pct`. It keeps the survival result as `projection_util_pct` and reports both error measurements in run metadata. Temperature and power forecasts are thermal proxies, not Alibaba measurements.

Known forecast limits:

- no 1–24 hour arrival prediction;
- no forecast distribution or confidence interval;
- no future actual value in the live inspector until time advances;
- only the four board-mapped pools have board-level forecast fields;
- the UI pressure label is a thresholded presentation of forecast utilisation, not a model output.

## Files changed

- `server-room/gpu-room.js`: rack discovery, beacons, rack picking, pool routes, rack test mode, custom-job callback, and scene status updates.
- `server-room/replay-engine.js`: aggregate rack-pool snapshots, pool focus, and route pool identity.
- `server-room/rack-fabric.js`: pure six-pool rack mapping and state aggregation.
- `server-room/rack-test-data.js`: clearly labelled local mock states for rack UI verification only.
- `server-room/ui/overlay.jsx`: chooses board or rack inspection and mounts custom-job and forecast panels.
- `server-room/ui/backend-panels.jsx`: rack inspector, custom-job form, supported forecast display, and explicit forecast limitations.
- `server-room/integration.css`: small additive styles for rack, test-mode, form, and forecast elements.
- `server-room/scripts/build.mjs`: copies the two new rack modules into the static distribution.
- `server-room/tests/rack-fabric.test.mjs`: verifies non-overlapping mappings, exact pool values, board aggregation, and all display states.
- `server-room/tests/replay-engine.test.mjs`: verifies custom injection fields pass through scenario operations.
- `analysis/visualization/functional-racks-test-wide.jpg`: browser evidence for rack columns and the selected H800 aggregate.
- `server-room/CLAUDE_HANDOFF.md`: this handoff.

No scheduler, API, RL, dataset, Blender asset, or model file is changed by this branch.

## Tests completed

Run from `server-room`:

```powershell
npm test
npm run build
```

Results at handoff:

- 20 of 20 Node tests passed.
- Production build passed.
- Blender GLB validation passed during the build: 124,260 bytes.
- Browser smoke test loaded the room, GLB, and rack test mode with no console errors.
- Browser rack test selected the H800 aggregate and displayed 615 of 640 busy GPUs, 96% utilisation, 77 running jobs, and 6 high-priority plus 4 spot jobs from the labelled stress fixture.
- Browser state tests confirmed A100 `idle`, H800 `overloaded`, and H800 `failed` states.
- `git diff --check` passed.

Not verified:

- a custom job submitted from the browser to a running Python backend;
- live queue and route animation for that submitted job;
- live forecast panels against Claude's current backend process;
- failure and recovery against the latest concurrently developed Python branch.

## Instructions for Claude

1. Use a clean worktree based on the intended integration branch.
2. Apply or merge this local commit without replacing newer scheduler, API, RL, or restaurant work.
3. Resolve conflicts in favour of Claude's newer backend contracts, while preserving the frontend calls described above.
4. Create the documented Python environment and start the API.
5. Start the built frontend with `?mode=backend`.
6. Confirm `GET /meta` returns all six pool IDs and `meta.display` still describes 24 boards for the four pods.
7. Submit a custom job for each priority. Confirm that `/whatif` receives the entered pool, GPU count, priority, and duration.
8. Confirm the job appears as `INJ-*` in an `arrive` event, enters the selected pool queue if capacity is unavailable, receives a `start` event from the actual scheduler, and animates towards the correct pod or aggregate rack.
9. Select racks for all six pools. Compare inspector values exactly with the current backend snapshot.
10. Test a failure and repair on a board-mapped pool. Confirm beacon state, node counts, eviction, requeue, and recovery.
11. Confirm the forecast panel matches `boards[i].forecast` and `meta.forecast`. Do not present `projection_util_pct` as the chosen forecast unless the backend contract changes.
12. Run the Python and Node suites, then capture backend-mode browser evidence.

## How to run

From the repository root:

```powershell
conda env create -f environment.yml
conda activate htb
python -m pytest
python -m uvicorn scheduler.api:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd server-room
npm ci
npm test
npm run build
npm run preview
```

Open the real backend integration:

```text
http://127.0.0.1:8081/?mode=backend
```

Open the isolated rack visual test only when the backend is unavailable:

```text
http://127.0.0.1:8081/?mode=rack-test&rackState=stress
```

Other rack fixture values are `normal` and `failure`. Never use rack-test output as backend evidence.
