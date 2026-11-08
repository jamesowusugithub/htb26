# GPU scheduling room

This extends the mandatory `thingraph/server-room` foundation. Its room layout,
wall and rack builders, material system, lighting and elevated orbit camera are
retained. The new GPU hall uses a Blender-authored GLB with instanced geometry.

```powershell
cd server-room
npm ci
npm start
```

Open http://127.0.0.1:8080. For the static distribution:

```powershell
npm test
npm run build
npm run preview
```

Open http://127.0.0.1:8081. The asset and SDK files are bundled locally; runtime
does not require Blender to remain connected or an external CDN.

## Interactions

- Drag to orbit; scroll to zoom. Room, GPU hall and GPU detail change viewpoints.
- Click an individual board to inspect its state, assigned job and progress.
- Add a high-priority job or a burst. Coloured particles travel from the gateway
  to reserved GPUs before processing begins.
- Processing raises the modelled temperature and changes the board lighting.
- Fail the selected GPU to make it unavailable and requeue interrupted work.
  Repair returns the GPU to the available pool.
- Pause, change playback speed, switch admission policy or reset the scenario.

## Evidence boundary

This is a deterministic synthetic event demonstration. Jobs, placements,
durations, temperatures, utilisation and failures are illustrative. It is not
a replay of observed assignments or a validated physical thermal model. The
separate analytical datasets are preserved and are not presented as observations
from this fictional room. No RL or ML training is used.

## Blender asset

`assets/gpu/gpu-board.glb` was created through the existing Blender MCP bridge.
The source script and MCP client are in `../scripts/blender/`; generation details
are in `../analysis/visualization/blender-asset-report.md`. Existing Blender
objects were preserved. The browser instances shared GPU geometry, recolours
status materials and rotates the fan geometry during processing.

Browser screenshots and validation notes are in `../analysis/visualization/`.
The supplied repository is the visual reference; no separate user reference
images were attached to this request.

## Backend mode (integration branch)

The room can now replay results from the scheduling backend instead of the synthetic demo. See `INTEGRATION.md`.
The evidence boundary above applies to `?mode=synthetic` only; in backend mode the UI states that waits and placements are simulated
and that temperature/power are a proxy from measured H100 profiles.
