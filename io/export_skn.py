import bpy
import mathutils
import struct
import os
import re
from ..utils.binary_utils import BinaryStream

def clean_blender_name(name):
    """Remove Blender's .001, .002 etc. suffixes from names"""
    return re.sub(r'\.\d{3}$', '', name)

def collect_mesh_data(mesh_obj, armature_obj, bone_to_idx, submesh_name):
    """Collect geometry data from a single mesh object"""
    
    # Matrix to go from Mesh World to Armature Local
    world_to_armature = armature_obj.matrix_world.inverted() @ mesh_obj.matrix_world
    
    mesh = mesh_obj.data
    mesh.calc_loop_triangles()
    
    # Map vertex groups to SKL bone indices
    group_to_bone_idx = {}
    for group in mesh_obj.vertex_groups:
        clean_name = group.name.split('.')[0] if '.' in group.name else group.name
        if clean_name in bone_to_idx:
            group_to_bone_idx[group.index] = bone_to_idx[clean_name]
        elif group.name in bone_to_idx:
            group_to_bone_idx[group.index] = bone_to_idx[group.name]
    
    submesh_indices = []
    submesh_vertices = []
    vert_map = {}
    
    for tri in mesh.loop_triangles:
        for loop_idx in tri.loops:
            vert_idx = mesh.loops[loop_idx].vertex_index
            uv = mesh.uv_layers.active.data[loop_idx].uv if mesh.uv_layers.active else (0.0, 0.0)
            normal_B = mesh.loops[loop_idx].normal
            
            key = (vert_idx, round(uv[0], 6), round(uv[1], 6), 
                   round(normal_B.x, 6), round(normal_B.y, 6), round(normal_B.z, 6))
            
            if key not in vert_map:
                new_v_idx = len(submesh_vertices)
                vert_map[key] = new_v_idx
                
                # Armature-Local Position -> League Space
                v_B = world_to_armature @ mesh.vertices[vert_idx].co
                v_L = mathutils.Vector((-v_B.x, v_B.z, -v_B.y))

                
                n_A = (world_to_armature.to_3x3() @ normal_B).normalized()
                n_L = mathutils.Vector((-n_A.x, n_A.z, -n_A.y))
                
                # Weights
                v = mesh.vertices[vert_idx]
                influences = [0, 0, 0, 0]
                weights = [0.0, 0.0, 0.0, 0.0]
                
                vg_weights = sorted([(group_to_bone_idx[g.group], g.weight) 
                                   for g in v.groups if g.group in group_to_bone_idx], 
                                  key=lambda x: x[1], reverse=True)
                
                for i in range(min(4, len(vg_weights))):
                    influences[i] = vg_weights[i][0]
                    weights[i] = vg_weights[i][1]
                
                w_sum = sum(weights)
                if w_sum > 0:
                    weights = [w / w_sum for w in weights]
                else:
                    weights = [1.0, 0.0, 0.0, 0.0]
                
                submesh_vertices.append({
                    'pos': v_L,
                    'inf': influences,
                    'weight': weights,
                    'normal': n_L,
                    'uv': (uv[0], 1.0 - uv[1])
                })
            
            submesh_indices.append(vert_map[key])
    
    return {
        'name': submesh_name,
        'vertices': submesh_vertices,
        'indices': submesh_indices
    }


def write_skn_multi(filepath, mesh_objects, armature_obj, clean_names=True):
    """Write multiple Blender meshes to a single SKN file with multiple submeshes"""
    
    if not armature_obj:
        raise Exception("No armature found")
    
    # Sort bones to ensure stable indexing matching SKL
    bone_list = list(armature_obj.pose.bones)
    # Build bone name to index map, with cleaned names if option enabled
    bone_to_idx = {}
    for i, bone in enumerate(bone_list):
        bone_to_idx[bone.name] = i
        if clean_names:
            # Also map cleaned name to same index for vertex group lookup
            cleaned = clean_blender_name(bone.name)
            if cleaned != bone.name:
                bone_to_idx[cleaned] = i
    
    submesh_data = []
    total_vertex_count = 0
    total_index_count = 0
    
    for mesh_obj in mesh_objects:
        if mesh_obj.type != 'MESH':
            continue
            
        # Use object name or material name as submesh name
        if mesh_obj.data.materials and mesh_obj.data.materials[0]:
            submesh_name = mesh_obj.data.materials[0].name
        else:
            submesh_name = mesh_obj.name
        
        # Clean up Maya-style "mesh_" prefix
        if submesh_name.startswith("mesh_"):
            submesh_name = submesh_name[5:]
        
        if clean_names:
            submesh_name = clean_blender_name(submesh_name)
        
        data = collect_mesh_data(mesh_obj, armature_obj, bone_to_idx, submesh_name)
        
        if not data['indices']:
            continue
        
        submesh_info = {
            'name': data['name'],
            'vertex_start': total_vertex_count,
            'vertex_count': len(data['vertices']),
            'index_start': total_index_count,
            'index_count': len(data['indices']),
            'vertices': data['vertices'],
            'indices': [idx + total_vertex_count for idx in data['indices']]
        }
        
        submesh_data.append(submesh_info)
        total_vertex_count += len(data['vertices'])
        total_index_count += len(data['indices'])
    
    if not submesh_data:
        raise Exception("No geometry found to export")
    
    # Validate limits (same as Maya plugin)
    if total_vertex_count > 65535:
        raise Exception(f"Too many vertices: {total_vertex_count}, max allowed: 65535. Reduce mesh complexity or split into multiple files.")
    
    if len(submesh_data) > 32:
        raise Exception(f"Too many submeshes/materials: {len(submesh_data)}, max allowed: 32. Reduce number of materials.")
    
    # Write to file
    with open(filepath, 'wb') as f:
        bs = BinaryStream(f)
        
        bs.write_uint32(0x00112233)  # Magic
        bs.write_uint16(1, 1)  # Major, Minor
        
        bs.write_uint32(len(submesh_data))
        for sm in submesh_data:
            bs.write_padded_string(sm['name'], 64)
            bs.write_uint32(sm['vertex_start'], sm['vertex_count'], 
                           sm['index_start'], sm['index_count'])
            
        bs.write_uint32(total_index_count, total_vertex_count)
        
        for sm in submesh_data:
            for idx in sm['indices']:
                bs.write_uint16(idx)
                
        for sm in submesh_data:
            for v in sm['vertices']:
                bs.write_vec3(v['pos'])
                bs.write_uint8(*v['inf'])
                bs.write_float(*v['weight'])
                bs.write_vec3(v['normal'])
                bs.write_vec2(v['uv'])
                
    return len(submesh_data), total_vertex_count


def save(operator, context, filepath, export_skl_file=True, clean_names=True, target_armature=None):
    armature_obj = target_armature
    mesh_objects = []
    
    # Get all selected meshes
    selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
    
    if selected_meshes:
        mesh_objects = selected_meshes
        
        if not armature_obj:
            armature_obj = selected_meshes[0].find_armature()
            if not armature_obj and selected_meshes[0].parent and selected_meshes[0].parent.type == 'ARMATURE':
                armature_obj = selected_meshes[0].parent
                
    elif armature_obj:
        mesh_objects = [obj for obj in context.scene.objects 
                       if obj.type == 'MESH' and 
                       (obj.parent == armature_obj or obj.find_armature() == armature_obj)]
                       
    elif context.active_object and context.active_object.type == 'ARMATURE':
        armature_obj = context.active_object
        mesh_objects = [obj for obj in context.scene.objects 
                       if obj.type == 'MESH' and 
                       (obj.parent == armature_obj or obj.find_armature() == armature_obj)]
    else:
        armature_obj = next((obj for obj in context.scene.objects if obj.type == 'ARMATURE'), None)
        if armature_obj:
            mesh_objects = [obj for obj in context.scene.objects 
                           if obj.type == 'MESH' and 
                           (obj.parent == armature_obj or obj.find_armature() == armature_obj)]
    
    if not mesh_objects:
        operator.report({'ERROR'}, "No mesh objects found. Select meshes or select the armature to export all.")
        return {'CANCELLED'}
    
    if not armature_obj:
        operator.report({'ERROR'}, "No armature found. Meshes must be parented to an armature.")
        return {'CANCELLED'}
    
    try:
        submesh_count, vertex_count = write_skn_multi(filepath, mesh_objects, armature_obj, clean_names)
        operator.report({'INFO'}, f"Exported SKN: {submesh_count} submeshes, {vertex_count} vertices")
        
        if export_skl_file and armature_obj:
            skl_path = os.path.splitext(filepath)[0] + ".skl"
            from . import export_skl
            export_skl.write_skl(skl_path, armature_obj)
            operator.report({'INFO'}, f"Exported matching SKL: {skl_path}")
            
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
