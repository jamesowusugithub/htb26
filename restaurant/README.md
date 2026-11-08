# frontend-restaurant (Phaser "5-year-old" view)

Vite + React + TypeScript + Phaser 3, port 5174. All art is generated in code at boot (no assets, fonts or CDNs).

- `npm run dev` / `npm run build && npm run preview`
- `?source=replay` plays `public/sample-events.json` (hand-scripted, regenerate with `npm run sample`); `?source=live` (default) talks to `VITE_API_URL` (default http://localhost:8000), optional `&run=<id>`; falls back to replay with a visible banner.
- `npm run test:e2e` (needs the preview server running): Playwright acceptance, screenshots to `shots/`.
- Contract: `../contracts/CONTRACT.md`. Live mode is exercised against the real backend by `tests/e2e-live.cjs` (`BASE=http://localhost:5174 node tests/e2e-live.cjs`, backend on :8000).

## New orders and the takeaway (real backend decisions)
- Open `?trace=rl_ppo&api=http://127.0.0.1:8020` (backend from this repo: `uvicorn scheduler.api:app --port 8020`). The **New order** controls post jobs that are NOT in the
  Alibaba trace to `POST /restaurant/trace`; the trained policy schedules them (no retraining) and the animation reloads at the same minute. Past events do not change (tested).
  Without `&api=` the recording is static and read-only.
- **Takeaway = cloud overflow**, a clearly labelled SIMULATED fallback: the Alibaba trace has no cloud assignments and the original simulator had no cloud concept, so nothing
  was routed there. `scheduler/sim.py` now has flagged cloud nodes; a job that has waited past `overflow_wait_min` is sent there only if its PREDICTED rental cost (hint model
  runtime x GPUs x price) is under `max_job_cost_usd`. Capacity (`nodes`, `gpus_per_node`), threshold, price multiplier and budget are configurable. Prices are tier assumptions
  anchored to the pricing data (no Alibaba GPU has an exact price match): see `scheduler/cloud.py`. Actual cost is charged on the real runtime, so it can exceed the prediction.
- Tests: `tests/test_cloud.py`, `tests/test_restaurant_orders_takeaway.py`, browser test `node tests/e2e-orders-takeaway.mjs` (needs backend, preview server, puppeteer-core).
