# Interactive GPU room validation

Foundation: `thingraph/server-room`, commit
`57966a9cac9e15d0d557a35707c9234fc062dbc7`.

The original scene ran before modification. Its procedural room, 360 racks,
white architectural materials, glass partitions, lighting and elevated camera
were inspected in the actual browser. The implementation retains that scene.
The supplied repository is the visual reference; no additional user reference
images were attached. No claim is made about matching an unavailable image.

## Executed checks

- `npm ci` completed using the upstream lockfile.
- `npm test`: all five event-engine tests passed, covering dispatch travel,
  completion, failed-device exclusion, atomic requeue, policy ordering,
  deterministic stepping and invalid resource requests.
- `node --check gpu-room.js` passed.
- `npm run build` completed and checked the Blender GLB header and declared size.
- The built static distribution was served on localhost port 8081 and tested
  through the browser, not only the development source.
- The browser loaded the Blender GLB, with no captured JavaScript errors.
- Pointer selection changed inspection from GPU-01 to GPU-04. The viewer's
  overlay canvas required capture-phase pointer handling.
- Failure made GPU-04 unavailable, reduced active capacity and returned its
  interrupted job to the queue. Repair removed the failed state.
- Pause/resume, priority/round-robin switching, speed changes, burst arrival,
  reset, camera view buttons, pointer rotation and wheel zoom were exercised.
- Desktop and narrow browser layouts were inspected. Desktop screenshots retain
  the original room overview and show the GPU detail/failed states.

## Screenshot comparison

| Screenshot | What it establishes |
| --- | --- |
| `server-room-baseline.jpg` | Actual original browser scene before GPU additions |
| `gpu-room-overview.jpg` | Same architectural room and elevated presentation with GPU pods |
| `gpu-hall-live.jpg` | Added compute pods inside the original room |
| `gpu-detail-active.jpg` | Blender board geometry, fans, status lighting and processing inspection |
| `gpu-detail-failed.jpg` | Red failed-device state and unavailable inspection |
| `gpu-room-narrow.jpg` | Actual narrow browser layout |

## Limits

The event workload and thermal state are explicitly synthetic. This version does
not replay measured GPU placements or claim a scheduling improvement. It does
not train ML/RL, alter the analytical tables, or expose Blender to the browser.
The asset was exported through the existing local Blender MCP bridge.

Upstream `npm ci` reported 11 dependency advisories (4 moderate, 7 high). No
unreviewed dependency upgrades were applied during this visual task. Preview
servers are local development tools; the final static preview binds loopback.
The upstream repository did not include a top-level licence grant. Third-party
notices and the baseline source are retained.
