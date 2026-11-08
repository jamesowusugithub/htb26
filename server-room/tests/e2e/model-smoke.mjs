// Baseline: does the Blender GPU model load and render in the built room (synthetic mode)? Writes a screenshot.
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { serveDist, launch, openRoom, ui, sleep, root } from './harness.mjs';
const outDir = path.resolve(root, '../analysis/visualization/integration'); mkdirSync(outDir, { recursive: true });
const { server, port } = await serveDist();
const browser = await launch();
try {
  const { page, logs } = await openRoom(browser, `http://127.0.0.1:${port}/index.html?mode=synthetic`);
  await sleep(2500);
  const d = await ui(page);
  const glbErrors = logs.filter(l => /GLB|gltf|failed to load/i.test(l));
  console.log(JSON.stringify({ assetLoaded: d.assetLoaded, gpuAssetMeshes: d.gpuAssetMeshes, gpuCount: d.gpuCount, running: d.running, glbErrors }));
  await page.screenshot({ path: path.join(outDir, 'baseline-synthetic.png') });
  if (d.assetLoaded !== 'true' || Number(d.gpuAssetMeshes) < 1 || glbErrors.length) process.exitCode = 1;
} finally { await browser.close(); server.close(); }
