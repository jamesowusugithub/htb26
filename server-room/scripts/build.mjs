import { cpSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'dist');
const glb=readFileSync(path.join(root,'assets/gpu/gpu-board.glb'));
if(glb.toString('utf8',0,4)!=='glTF'||glb.readUInt32LE(4)!==2||glb.readUInt32LE(8)!==glb.length)throw new Error('Invalid Blender GPU GLB');
mkdirSync(output,{recursive:true});
for(const entry of ['index.html','global.css','gpu-room.css','gpu-room.js','gpu-simulation.js','gpu-favicon.svg','assets','iconfont','packages']){
  cpSync(path.join(root,entry),path.join(output,entry),{recursive:true});
}
writeFileSync(path.join(output,'build-info.json'),JSON.stringify({foundation:'thingraph/server-room',upstreamCommit:'57966a9cac9e15d0d557a35707c9234fc062dbc7',gpuAsset:'Blender MCP generated GLB',gpuAssetBytes:glb.length,evidence:'synthetic interactive event demonstration'},null,2));
console.log(`Built static server-room distribution. Blender GLB validated: ${glb.length} bytes.`);
