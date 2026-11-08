# Upstream foundation

Source: https://github.com/thingraph/server-room

Baseline commit: `57966a9cac9e15d0d557a35707c9234fc062dbc7`.

The original Three.js/x-viewer room, racks, wall layout, lights, materials,
camera controls and rack interactions are retained. `gpu-room.js` adds a GPU
laboratory and an explicitly synthetic scheduling event demonstration.

The GPU board GLB was generated in the user's running Blender instance through
the Blender MCP bridge. Its procedural source is in `../scripts/blender/`.
Original Blender scene objects were preserved. The 24 board placements reuse
its mesh geometry with Three.js instancing.

No RL or ML training is used. Job assignments, utilisation, temperatures and
failures in the browser are illustrative scenario state, not measured history
from the independent analytical datasets.

Upstream files did not include a top-level licence file at this commit.
This repository does not add a licence grant for third-party code or assets.
