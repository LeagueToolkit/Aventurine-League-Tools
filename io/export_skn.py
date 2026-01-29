import bpy
import mathutils
import struct
import os
import re
from ..utils.binary_utils import BinaryStream
from . import import_skl

def clean_blender_name(name):
    """Remove Blender's .001, .002 etc. suffixes from names"""
    return re.sub(r'\.\d{3}$', '', name)

def check_shared_vertices_between_materials(mesh_obj):
    """
    Check if any vertices are shared between faces with different materials.
    Returns a list of material names that share vertices, or empty list if none.
    """
    mesh = mesh_obj.data
    mesh.calc_loop_triangles()

    if len(mesh.materials) <= 1:
        return []

    # Map each vertex to the set of material indices that use it
    vertex_materials = {}
    for tri in mesh.loop_triangles:
        mat_idx = tri.material_index
        for v_idx in tri.vertices:
            if v_idx not in vertex_materials:
                vertex_materials[v_idx] = set()
            vertex_materials[v_idx].add(mat_idx)

    # Find vertices used by multiple materials
    shared_materials = set()
    for v_idx, mat_indices in vertex_materials.items():
        if len(mat_indices) > 1:
            for mat_idx in mat_indices:
                if mat_idx < len(mesh.materials) and mesh.materials[mat_idx]:
                    shared_materials.add(mesh.materials[mat_idx].name)

    return list(shared_materials)


def collect_mesh_data(mesh_obj, armature_obj, bone_to_idx, submesh_name, material_index=None, disable_scaling=False, disable_transforms=False):
    """
    Collect geometry data from a single mesh object.
    If material_index is specified, only collect triangles belonging to that material.
    """

    mesh = mesh_obj.data
    mesh.calc_loop_triangles()

    # Matrix to go from Mesh World to Armature Local
    world_to_armature = armature_obj.matrix_world.inverted() @ mesh_obj.matrix_world
    scale = 1.0 if disable_scaling else import_skl.EXPORT_SCALE

    # Map vertex groups to SKL bone indices
    group_to_bone_idx = {}
    for group in mesh_obj.vertex_groups:
        clean_name = group.name.split('.')[0] if '.' in group.name else group.name
        if clean_name in bone_to_idx:
            group_to_bone_idx[group.index] = bone_to_idx[clean_name]
        elif group.name in bone_to_idx:
            group_to_bone_idx[group.index] = bone_to_idx[group.name]

    # Filter triangles by material index if specified
    if material_index is not None:
        filtered_tris = [tri for tri in mesh.loop_triangles if tri.material_index == material_index]
    else:
        filtered_tris = list(mesh.loop_triangles)

    if not filtered_tris:
        return None

    # Collect which vertices are actually used by the filtered triangles
    used_vertex_indices = set()
    for tri in filtered_tris:
        used_vertex_indices.update(tri.vertices)

    # Create a mapping from old vertex index to new (compacted) index
    old_to_new = {}
    for new_idx, old_idx in enumerate(sorted(used_vertex_indices)):
        old_to_new[old_idx] = new_idx

    # Map each vertex ID to its UV and Normal from the first loop that uses it
    vert_uvs = {}
    vert_normals = {}
    if mesh.uv_layers.active:
        uv_data = mesh.uv_layers.active.data
        for loop in mesh.loops:
            v_idx = loop.vertex_index
            if v_idx in used_vertex_indices and v_idx not in vert_uvs:
                vert_uvs[v_idx] = uv_data[loop.index].uv
                vert_normals[v_idx] = loop.normal

    submesh_vertices = []
    for old_idx in sorted(used_vertex_indices):
        v = mesh.vertices[old_idx]

        # Position
        v_B = world_to_armature @ v.co
        if disable_transforms:
            v_L = mathutils.Vector((v_B.x * scale, v_B.y * scale, v_B.z * scale))
        else:
            v_L = mathutils.Vector((-v_B.x * scale, v_B.z * scale, -v_B.y * scale))

        # Normal (prefer loop normal for fidelity, fallback to vertex normal)
        n_B = vert_normals.get(old_idx, v.normal)
        n_A = (world_to_armature.to_3x3() @ n_B).normalized()
        if disable_transforms:
            n_L = mathutils.Vector((n_A.x, n_A.y, n_A.z))
        else:
            n_L = mathutils.Vector((-n_A.x, n_A.z, -n_A.y))

        # UV
        uv = vert_uvs.get(old_idx, (0.0, 0.0))

        # Weights
        influences = [0, 0, 0, 0]
        weights = [0.0, 0.0, 0.0, 0.0]
        vg_weights = sorted([(group_to_bone_idx[g.group], g.weight)
                           for g in v.groups if g.group in group_to_bone_idx],
                          key=lambda x: x[1], reverse=True)

        for j in range(min(4, len(vg_weights))):
            influences[j] = vg_weights[j][0]
            weights[j] = vg_weights[j][1]

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

    # Remap triangle indices to the new compacted vertex indices
    submesh_indices = []
    for tri in filtered_tris:
        for v_idx in tri.vertices:
            submesh_indices.append(old_to_new[v_idx])

    return {
        'name': submesh_name,
        'vertices': submesh_vertices,
        'indices': submesh_indices
    }


def write_skn_multi(filepath, mesh_objects, armature_obj, clean_names=True, disable_scaling=False, disable_transforms=False):
    """Write multiple Blender meshes to a single SKN file with multiple submeshes"""

    print("\n=== SKN EXPORT DEBUG ===")

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

        mesh = mesh_obj.data
        print(f"Processing mesh: '{mesh_obj.name}' with {len(mesh.materials)} material slots")
        for i, mat in enumerate(mesh.materials):
            mat_name = mat.name if mat else "(None)"
            print(f"  Slot {i}: '{mat_name}'")

        # Check for shared vertices between materials
        shared_mats = check_shared_vertices_between_materials(mesh_obj)
        if shared_mats:
            raise Exception(
                f"Mesh '{mesh_obj.name}' has vertices shared between multiple materials: {', '.join(shared_mats)}. "
                f"Please separate the mesh by material (Edit Mode > Mesh > Separate > By Material) before exporting."
            )

        # Process each material on the mesh as a separate submesh
        if mesh.materials:
            for mat_idx, material in enumerate(mesh.materials):
                if material is None:
                    submesh_name = mesh_obj.name
                else:
                    submesh_name = material.name

                # Clean up Maya-style "mesh_" prefix
                if submesh_name.startswith("mesh_"):
                    submesh_name = submesh_name[5:]

                if clean_names:
                    submesh_name = clean_blender_name(submesh_name)

                data = collect_mesh_data(mesh_obj, armature_obj, bone_to_idx, submesh_name,
                                        material_index=mat_idx,
                                        disable_scaling=disable_scaling,
                                        disable_transforms=disable_transforms)

                if data is None or not data['indices']:
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

                print(f"  Submesh: '{submesh_info['name']}' | verts: {submesh_info['vertex_count']} (start: {submesh_info['vertex_start']}) | indices: {submesh_info['index_count']} (start: {submesh_info['index_start']})")
                submesh_data.append(submesh_info)
                total_vertex_count += len(data['vertices'])
                total_index_count += len(data['indices'])
        else:
            # No materials - use mesh object name
            submesh_name = mesh_obj.name
            if submesh_name.startswith("mesh_"):
                submesh_name = submesh_name[5:]
            if clean_names:
                submesh_name = clean_blender_name(submesh_name)

            data = collect_mesh_data(mesh_obj, armature_obj, bone_to_idx, submesh_name,
                                    material_index=None,
                                    disable_scaling=disable_scaling,
                                    disable_transforms=disable_transforms)

            if data is None or not data['indices']:
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

            print(f"  Submesh: '{submesh_info['name']}' | verts: {submesh_info['vertex_count']} (start: {submesh_info['vertex_start']}) | indices: {submesh_info['index_count']} (start: {submesh_info['index_start']})")
            submesh_data.append(submesh_info)
            total_vertex_count += len(data['vertices'])
            total_index_count += len(data['indices'])

    print(f"Total: {len(submesh_data)} submeshes, {total_vertex_count} vertices, {total_index_count} indices")
    print("=== END DEBUG ===\n")

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


def save(operator, context, filepath, export_skl_file=True, clean_names=True, target_armature=None, disable_scaling=False, disable_transforms=False):
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
        submesh_count, vertex_count = write_skn_multi(filepath, mesh_objects, armature_obj, clean_names, disable_scaling, disable_transforms)
        operator.report({'INFO'}, f"Exported SKN: {submesh_count} submeshes, {vertex_count} vertices")

        if export_skl_file and armature_obj:
            skl_path = os.path.splitext(filepath)[0] + ".skl"
            from . import export_skl
            export_skl.write_skl(skl_path, armature_obj, disable_scaling, disable_transforms)
            operator.report({'INFO'}, f"Exported matching SKL: {skl_path}")
            
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
