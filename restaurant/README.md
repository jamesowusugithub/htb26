# frontend-restaurant (Phaser "5-year-old" view)

Vite + React + TypeScript + Phaser 3, port 5174. All art is generated in code at boot (no assets, fonts or CDNs).

- `npm run dev` / `npm run build && npm run preview`
- `?source=replay` plays `public/sample-events.json` (hand-scripted, regenerate with `npm run sample`); `?source=live` (default) talks to `VITE_API_URL` (default http://localhost:8000), optional `&run=<id>`; falls back to replay with a visible banner.
- `npm run test:e2e` (needs the preview server running): Playwright acceptance, screenshots to `shots/`.
- Contract: `../contracts/CONTRACT.md`. Live mode is exercised against the real backend by `tests/e2e-live.cjs` (`BASE=http://localhost:5174 node tests/e2e-live.cjs`, backend on :8000).
