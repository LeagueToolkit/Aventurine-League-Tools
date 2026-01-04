"""SKN mesh importer - fixed to match skeleton coordinate system and binding"""
import bpy
import os
import mathutils
from ..utils.binary_utils import BinaryStream, Vector
from . import import_skl
from ..utils import texture_manager


class SKNVertex:
    __slots__ = ('position', 'influences', 'weights', 'uv')
    
    def __init__(self):
        self.position = None
        self.influences = None
        self.weights = None
        self.uv = None


class SKNSubmesh:
    __slots__ = ('name', 'vertex_start', 'vertex_count', 'index_start', 'index_count')
    
    def __init__(self):
        self.name = None
        self.vertex_start = None
        self.vertex_count = None
        self.index_start = None
        self.index_count = None


def read_skn(filepath):
    indices = []
    vertices = []
    submeshes = []
    
    with open(filepath, 'rb') as f:
        bs = BinaryStream(f)
        
        magic = bs.read_uint32()
        if magic != 0x00112233:
            raise Exception(f'Wrong SKN signature')
        
        major, minor = bs.read_uint16(), bs.read_uint16()
        
        vertex_type = 0
        if major == 0:
            index_count, vertex_count = bs.read_uint32(), bs.read_uint32()
            submesh = SKNSubmesh()
            submesh.name = 'Base'
            submesh.vertex_start = 0
            submesh.vertex_count = vertex_count
            submesh.index_start = 0
            submesh.index_count = index_count
            submeshes.append(submesh)
        else:
            submesh_count = bs.read_uint32()
            submeshes = [SKNSubmesh() for _ in range(submesh_count)]
            
            for submesh in submeshes:
                submesh.name = bs.read_padded_ascii(64)
                submesh.vertex_start = bs.read_uint32()
                submesh.vertex_count = bs.read_uint32()
                submesh.index_start = bs.read_uint32()
                submesh.index_count = bs.read_uint32()
            
            if major >= 4:
                bs.pad(4) # flags
            
            index_count, vertex_count = bs.read_uint32(), bs.read_uint32()
            
            if major >= 4:
                bs.pad(4) # vertex_size
                vertex_type = bs.read_uint32()
                bs.pad(40) # AABB and Sphere
        
        # Read indices
        face_count = index_count // 3
        for i in range(face_count):
            face = bs.read_uint16(3)
            if not (face[0] == face[1] or face[1] == face[2] or face[2] == face[0]):
                indices.extend(face)
        
        # Read vertices
        vertices = [SKNVertex() for _ in range(vertex_count)]
        for vertex in vertices:
            vertex.position = bs.read_vec3()
            vertex.influences = bs.read_bytes(4)
            vertex.weights = bs.read_float(4)
            bs.pad(12) # Normal
            vertex.uv = bs.read_vec2()
            
            if vertex_type >= 1:
                bs.pad(4)
                if vertex_type == 2:
                    bs.pad(16)
    
    return indices, vertices, submeshes


def create_mesh(indices, vertices, submeshes, name, armature_obj=None, joints=None, influences=None):
    # Coordinate system: X -> X, Y -> Z, Z -> -Y (Standing Up)
    verts = []
    for v in vertices:
        # Flip X to match Maya/Reliable import (Sword in left hand)
        verts.append((-v.position.x, -v.position.z, v.position.y))
    
    mesh = bpy.data.meshes.new(name)
    faces = [(indices[i], indices[i+1], indices[i+2]) for i in range(0, len(indices), 3)]
    mesh.from_pydata(verts, [], faces)
    
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for vert_idx, loop_idx in zip(poly.vertices, poly.loop_indices):
            vertex = vertices[vert_idx]
            uv_layer.data[loop_idx].uv = (vertex.uv.x, 1.0 - vertex.uv.y)
    
    for submesh in submeshes:
        mat = bpy.data.materials.new(submesh.name)
        mat.use_nodes = True
        mesh.materials.append(mat)
        
        face_start = submesh.index_start // 3
        face_end = (submesh.index_start + submesh.index_count) // 3
        mat_idx = len(mesh.materials) - 1
        for i in range(face_start, min(face_end, len(mesh.polygons))):
            mesh.polygons[i].material_index = mat_idx
    
    # Bind to armature
    if armature_obj and joints:
        obj.parent = armature_obj
        obj.matrix_parent_inverse = armature_obj.matrix_world.inverted()
        
        group_map = {}
        for i, joint in enumerate(joints):
            vg = obj.vertex_groups.new(name=joint.name)
            group_map[i] = vg
        
        mod = obj.modifiers.new(name='Armature', type='ARMATURE')
        mod.object = armature_obj
        mod.use_vertex_groups = True
        mod.use_bone_envelopes = False
        
        for vtx_idx, vertex in enumerate(vertices):
            # Safe way to handle multi-influence with possibly mapped indices
            v_weights = {}
            for k in range(4):
                bone_id = vertex.influences[k]
                weight = vertex.weights[k]
                
                if weight > 0.0001:
                    actual_joint_idx = bone_id
                    if influences and bone_id < len(influences):
                        actual_joint_idx = influences[bone_id]
                    
                    if actual_joint_idx < len(joints):
                        v_weights[actual_joint_idx] = v_weights.get(actual_joint_idx, 0.0) + weight
            
            # Add to groups
            for joint_idx, combined_weight in v_weights.items():
                group_map[joint_idx].add([vtx_idx], combined_weight, 'ADD')
    
    return obj


def load(operator, context, filepath, load_skl_file=True, split_by_material=False):
    try:
        indices, vertices, submeshes = read_skn(filepath)
        
        armature_obj = None
        joints = None
        influences = None
        
        if load_skl_file:
            skl_path = filepath.lower().replace('.skn', '.skl')
            if not os.path.exists(skl_path):
                skl_path = filepath.replace('.skn', '.skl')
                
            if os.path.exists(skl_path):
                try:
                    joints, influences = import_skl.read_skl(skl_path)
                    armature_obj = import_skl.create_armature(joints)
                except Exception as e:
                    operator.report({'WARNING'}, f'SKL load failed: {str(e)}')
        
        name = os.path.splitext(os.path.basename(filepath))[0]
        mesh_obj = create_mesh(indices, vertices, submeshes, name, armature_obj, joints, influences)

        try:
            texture_manager.import_textures(mesh_obj, filepath)
        except Exception as e:
            print(f"Texture import warnings: {e}")
            import traceback
            traceback.print_exc()

        
        if split_by_material:
            bpy.ops.object.select_all(action='DESELECT')
            mesh_obj.select_set(True)
            context.view_layer.objects.active = mesh_obj
            bpy.ops.mesh.separate(type='MATERIAL')
            
            for obj in context.selected_objects:
                if obj.type == 'MESH' and len(obj.data.materials) > 0:
                    mat = obj.data.materials[0]
                    if mat:
                        obj.name = mat.name
                    obj["lol_skn_filepath"] = filepath
                    obj["lol_skn_filename"] = os.path.basename(filepath)
        else:
            mesh_obj["lol_skn_filepath"] = filepath
            mesh_obj["lol_skn_filename"] = os.path.basename(filepath)
        
        if armature_obj:
            armature_obj["lol_skn_filepath"] = filepath
            armature_obj["lol_skl_filepath"] = filepath.replace('.skn', '.skl')
        
        operator.report({'INFO'}, f'Imported {len(vertices)} vertices')
        return {'FINISHED'}
    
    except Exception as e:
        operator.report({'ERROR'}, f'Failed: {str(e)}')
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
