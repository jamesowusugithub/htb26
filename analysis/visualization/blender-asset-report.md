# Procedural GPU asset

Created through the existing Blender MCP add-on at `localhost:9876`, using its
`execute_code` command. No installation, add-on configuration or Blender restart
was required. Blender version: 4.5.15 LTS.

Asset: `server-room/assets/gpu/gpu-board.glb`. Generation script:
`scripts/blender/create_gpu_asset.py`. Socket client:
`scripts/blender/mcp_client.py`.

The new `GPU_Visualization_Assets` collection contains a green circuit board,
processor package and die, VRAM packages, solder pads, PCIe contacts, copper
traces, capacitors, screws, aluminium cooling fins, copper heat pipes, twin
swept-blade fans, rear plate, display bracket, power socket and status LEDs.
This is an illustrative reusable GPU, not a vendor-exact engineering model.

The asset has 288 new objects with 15 shared mesh datablocks. Repeated fins,
contacts, VRAM packages, fan blades and capacitors reuse geometry. The GLB is
124,260 bytes. Nominal dimensions are approximately 0.305 × 0.116 × 0.046 metres.
glTF uses the exporter's Y-up convention.

Three.js hooks:

- Root: `GPU_BOARD_ROOT`.
- Fan groups: `FAN_0`, `FAN_1`; rotate around local Y in the exported glTF.
- Emissive material: `STATUS_LED`.
- Processor material: `GPU_DIE`.
- Clone materials per interactive GPU instance when applying independent states;
  share geometry to minimise memory.

The source Cube, Camera and Light remain in Blender. Existing object names were
verified present after generation, selection was restored, and no `.blend` file
was saved or overwritten. Export selected only the newly created asset objects.
GLB magic/version/declared file length and required fan/material names were
checked. The original scene objects are absent from the exported GLB.

The parent implementation performs browser integration and visual checks.
