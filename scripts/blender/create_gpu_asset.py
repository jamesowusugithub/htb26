"""Add a procedural GPU asset through the existing Blender MCP connection.

The embedded program preserves existing scene objects and restores selection.
Only the new collection is exported. It does not save or replace a .blend file.
"""
from pathlib import Path
import json
from mcp_client import command

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / 'server-room/assets/gpu'

BLENDER_CODE = r'''
import bpy, math, json
from mathutils import Vector
from pathlib import Path

destination = Path(__DESTINATION__)
destination.mkdir(parents=True, exist_ok=True)
old_selected = list(bpy.context.selected_objects)
old_active = bpy.context.view_layer.objects.active
old_mode = old_active.mode if old_active else 'OBJECT'
old_objects = set(bpy.data.objects.keys())
if old_active and old_mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
collection = bpy.data.collections.new('GPU_Visualization_Assets')
bpy.context.scene.collection.children.link(collection)
objects = []

def material(name, color, metallic=0.0, roughness=.4, emission=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*color, 1)
        bsdf.inputs['Emission Strength'].default_value = emission
    return m

pcb = material('GPU_PCB_GREEN', (.018, .19, .105), .12, .4)
dark = material('GPU_SHROUD_GRAPHITE', (.035, .045, .055), .55, .3)
rubber = material('GPU_FAN_BLACK', (.012, .016, .023), .15, .48)
aluminium = material('GPU_HEATSINK_ALUMINIUM', (.49, .57, .64), .92, .25)
copper = material('GPU_HEATPIPE_COPPER', (.66, .24, .065), .88, .26)
gold = material('GPU_CONNECTOR_GOLD', (.83, .59, .15), .9, .22)
chip = material('GPU_VRAM_PACKAGE', (.025, .031, .038), .2, .48)
die = material('GPU_DIE', (.12, .27, .34), .78, .17, .3)
status = material('STATUS_LED', (.015, .8, .46), .1, .25, 4)
white = material('GPU_SILKSCREEN', (.63, .77, .72), .05, .6)

cube_vertices = [(-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),
                 (-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)]
cube_faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
cube_cache = {}
def cube(name, size, loc, mat, parent=None, bevel=0):
    key = mat.name
    if key not in cube_cache:
        mesh = bpy.data.meshes.new('ReusableBox_' + key)
        mesh.from_pydata(cube_vertices, [], cube_faces)
        mesh.materials.append(mat)
        cube_cache[key] = mesh
    obj = bpy.data.objects.new(name, cube_cache[key])
    collection.objects.link(obj)
    obj.location = loc
    obj.scale = size
    obj.parent = parent
    objects.append(obj)
    return obj

cylinder_cache = {}
def cylinder(name, radius, depth, loc, mat, parent=None, segments=24):
    key = (segments, mat.name)
    if key not in cylinder_cache:
        verts = [(math.cos(i*2*math.pi/segments), math.sin(i*2*math.pi/segments), z)
                 for z in (-.5,.5) for i in range(segments)]
        faces = [tuple(range(segments-1,-1,-1)), tuple(range(segments,segments*2))]
        faces += [(i,(i+1)%segments,(i+1)%segments+segments,i+segments) for i in range(segments)]
        mesh = bpy.data.meshes.new('ReusableCylinder_' + mat.name)
        mesh.from_pydata(verts, [], faces)
        mesh.materials.append(mat)
        for p in mesh.polygons:
            p.use_smooth = p.index >= 2
        cylinder_cache[key] = mesh
    obj = bpy.data.objects.new(name, cylinder_cache[key])
    collection.objects.link(obj)
    obj.location = loc
    obj.scale = (radius, radius, depth)
    obj.parent = parent
    objects.append(obj)
    return obj

root = bpy.data.objects.new('GPU_BOARD_ROOT', None)
collection.objects.link(root)
objects.append(root)
root['asset_role'] = 'Reusable illustrative GPU module; not a vendor-exact engineering model'
root['length_m'] = .300
root['front_axis_blender'] = '+Z; glTF export converts to +Y'

cube('PCB_LAMINATE', (.29,.112,.002), (0,0,0), pcb, root)
cube('GPU_PACKAGE', (.045,.045,.003), (0,0,.0026), chip, root)
cube('GPU_DIE', (.031,.031,.001), (0,0,.0046), die, root)
for side in (-1,1):
    for i in range(6):
        cube('VRAM_%s_%02d' % (side,i), (.014,.011,.0028),
             (-.105+i*.042,side*.043,.0025), chip, root)
        for j in range(4):
            cube('VRAM_SOLDER_PAD', (.0015,.001,.0004),
                 (-.111+i*.042+j*.0038,side*.050,.0014), gold, root)
for i in range(44):
    cube('PCIE_GOLD_CONTACT_%02d'%i, (.003,.009,.0003),
         (-.122+i*.0057,-.054,.0013), gold, root)
for i in range(16):
    x=-.131+i*.0173
    cube('PCB_TRACE_%02d'%i, (.0007,.079,.00012), (x,.003,.0011), copper, root)
    cube('PCB_COMPONENT_%02d'%i, (.006,.003,.002), (x,.050,.0021), chip, root)
    cylinder('CAPACITOR_%02d'%i, .0018,.0035,(x,-.039,.003),aluminium,root,segments=12)
for x in (-.137,.137):
    for y in (-.045,.045):
        cylinder('BOARD_SCREW',.0023,.0015,(x,y,.0022),aluminium,root,segments=12)
        cube('MOUNT_PAD',(.008,.008,.0002),(x,y,.00115),gold,root)

# A dense shared-geometry fin stack and copper pipes make the cooler recognisable.
for i in range(58):
    cube('COOLING_FIN_%02d'%i, (.0012,.086,.021),
         (-.132+i*.0046,0,.016),aluminium,root)
for y in (-.026,0,.026):
    pipe=cylinder('COPPER_HEATPIPE',.0025,.265,(0,y,.007),copper,root)
    pipe.rotation_euler[1]=math.pi/2
# Open central strip reveals the processor material between the two fan housings.
for y in (-.048,.048):
    cube('COOLER_FRAME_RAIL',(.292,.006,.029),(0,y,.025),dark,root)
for x in (-.146,.146):
    cube('COOLER_FRAME_END',(.006,.094,.029),(x,0,.025),dark,root)
cube('GPU_BACKPLATE',(.286,.106,.0016),(0,0,-.0021),dark,root)
for i in range(8):
    cube('BACKPLATE_SILVER_INLAY',(.018,.0012,.0002),(-.104+i*.029,.039,-.003),aluminium,root)

blade_mesh=bpy.data.meshes.new('ReusableSweptFanBlade')
blade_mesh.from_pydata([(.011,-.003,0),(.021,-.011,0),(.037,-.009,0),
                       (.040,.002,0),(.021,.004,.0012),(.011,.003,.0012)],[],[(0,1,2,3,4,5)])
blade_mesh.materials.append(rubber)
for fan_index,x in enumerate((-.073,.073)):
    motor=bpy.data.objects.new('FAN_%d'%fan_index,None)
    collection.objects.link(motor)
    motor.parent=root
    motor.location=(x,0,.036)
    motor['spin_axis_gltf']='Y'
    objects.append(motor)
    cylinder('FAN_HUB_%d'%fan_index,.012,.008,(0,0,.001),dark,motor)
    cylinder('FAN_HUB_BADGE_%d'%fan_index,.008,.0005,(0,0,.0053),aluminium,motor)
    for i in range(11):
        blade=bpy.data.objects.new('FAN_%d_BLADE_%02d'%(fan_index,i),blade_mesh)
        collection.objects.link(blade)
        blade.parent=motor
        blade.rotation_euler[2]=i*2*math.pi/11
        objects.append(blade)
    # Static circular housing, with a hollow torus generated directly.
    major_segments,minor_segments=48,6
    verts=[]
    for a in range(major_segments):
        theta=a*2*math.pi/major_segments
        for b in range(minor_segments):
            phi=b*2*math.pi/minor_segments
            r=.043+.0024*math.cos(phi)
            verts.append((x+r*math.cos(theta),r*math.sin(theta),.037+.0024*math.sin(phi)))
    faces=[]
    for a in range(major_segments):
        for b in range(minor_segments):
            faces.append((a*minor_segments+b,((a+1)%major_segments)*minor_segments+b,
                          ((a+1)%major_segments)*minor_segments+(b+1)%minor_segments,
                          a*minor_segments+(b+1)%minor_segments))
    mesh=bpy.data.meshes.new('FanHousingMesh_%d'%fan_index)
    mesh.from_pydata(verts,[],faces)
    mesh.materials.append(dark)
    ring=bpy.data.objects.new('FAN_STATIC_HOUSING_%d'%fan_index,mesh)
    collection.objects.link(ring)
    ring.parent=root
    objects.append(ring)

# Bracket, connector sockets and state LEDs remain visible on the perimeter.
cube('IO_BRACKET',(.0025,.114,.039),(-.149,0,.017),aluminium,root)
for y in (-.033,-.011,.011,.033):
    cube('DISPLAY_SOCKET',(.004,.014,.007),(-.151,y,.014),dark,root)
cube('POWER_SOCKET',(.025,.010,.012),(.115,.054,.008),dark,root)
for i in range(6):
    cube('POWER_PIN',(.002,.004,.002),(.105+i*.004,.060,.008),gold,root)
for i in range(3):
    cube('STATUS_LED_%d'%i,(.004,.002,.002),(.112+i*.009,-.050,.041),status,root)
for i in range(5):
    cube('FRAME_ACCENT_%d'%i,(.015,.0012,.001),(-.12+i*.056,-.051,.034),aluminium,root)

bpy.context.view_layer.update()
try:
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=root
    result=bpy.ops.export_scene.gltf(filepath=str(destination/'gpu-board.glb'),
        export_format='GLB',use_selection=True,export_materials='EXPORT',
        export_animations=False,export_yup=True)
    if 'FINISHED' not in result:
        raise RuntimeError('glTF export did not finish: '+str(result))
finally:
    for obj in objects:
        obj.select_set(False)
    for obj in old_selected:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=old_active
    if old_active and old_mode!='OBJECT':
        bpy.ops.object.mode_set(mode=old_mode)

metadata={
    'created_through':'Blender MCP execute_code on existing localhost:9876 add-on',
    'blender_version':bpy.app.version_string,
    'collection':collection.name,'root_object':root.name,
    'new_object_count':len(objects),'mesh_count':sum(obj.type=='MESH' for obj in objects),
    'unique_mesh_count':len({obj.data.name for obj in objects if obj.type=='MESH'}),
    'approximate_dimensions_m':[.305,.116,.046],
    'materials':[m.name for m in [pcb,dark,rubber,aluminium,copper,gold,chip,die,status,white]],
    'fan_groups':['FAN_0','FAN_1'],'fan_rotation_axis_in_gltf':'Y',
    'status_material':'STATUS_LED','die_material':'GPU_DIE',
    'illustrative_not_vendor_exact':True,
    'original_objects_preserved':all(name in bpy.data.objects for name in old_objects),
    'selection_restored':sorted(obj.name for obj in bpy.context.selected_objects)==sorted(obj.name for obj in old_selected),
    'exported_file':'gpu-board.glb',
}
(destination/'gpu-board-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
print(json.dumps(metadata))
'''


if __name__ == '__main__':
    code = BLENDER_CODE.replace('__DESTINATION__', repr(str(DESTINATION)))
    print(json.dumps(command('execute_code', {'code': code}), indent=2))
    target = DESTINATION / 'gpu-board.glb'
    assert target.read_bytes()[:4] == b'glTF'
    print('Verified GLB:', target, target.stat().st_size, 'bytes')
