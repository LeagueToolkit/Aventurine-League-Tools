import bpy
import os
import struct
import mathutils
import math
from ..utils.binary_utils import BinaryStream, Hash

def write_anm(filepath, armature_obj, fps=30.0):
    """Write Blender animation to ANM file (Uncompressed v4 format)"""
    
    if not armature_obj.animation_data or not armature_obj.animation_data.action:
        raise Exception("No animation data found on armature")
    
    action = armature_obj.animation_data.action
    P = mathutils.Matrix(((-1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    P_inv = P.inverted()
    
    bones = list(armature_obj.pose.bones)
    
    # Frame range - skip frame 0 (bind pose) to match Maya's behavior
    # Import puts bind at frame 0, animation starts at frame 1
    frame_start = max(1, int(action.frame_range[0]))
    frame_end = int(action.frame_range[1])
    frame_count = max(1, frame_end - frame_start + 1)
    
    # Palettes for deduplication
    vec_palette = []
    vec_map = {}
    quat_palette = []
    quat_map = {}
    
    def add_to_vec_palette(v):
        key = (round(v.x, 6), round(v.y, 6), round(v.z, 6))
        if key not in vec_map:
            vec_map[key] = len(vec_palette)
            vec_palette.append(mathutils.Vector((v.x, v.y, v.z)))
        return vec_map[key]
    
    def add_to_quat_palette(q):
        q = q.normalized()
        key = (round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6))
        if key not in quat_map:
            quat_map[key] = len(quat_palette)
            quat_palette.append(mathutils.Quaternion((q.w, q.x, q.y, q.z)))
        return quat_map[key]

    # --- 1. Reconstruct Native Global Rest Hierarchy (MATCHING IMPORT) ---
    native_global_rest = {}
    
    def get_native_global(pb):
        if pb.name in native_global_rest:
            return native_global_rest[pb.name]
        
        # Get Native Bind Local (stored during SKL import)
        nb_t = pb.get("native_bind_t")
        if nb_t:
            n_t = mathutils.Vector(nb_t)
            n_r = mathutils.Quaternion(pb.get("native_bind_r"))
            s_val = pb.get("native_bind_s")
            n_s = mathutils.Vector(s_val) if s_val else mathutils.Vector((1,1,1))
        else:
            # Fallback - approximate from visual
            n_t = mathutils.Vector((0,0,0))
            n_r = mathutils.Quaternion((1,0,0,0))
            n_s = mathutils.Vector((1,1,1))

        # Build Native Local Matrix in Blender Space: N_local_B = P @ LocRotScale @ P_inv
        lm_t = mathutils.Matrix.Translation((n_t.x, n_t.y, n_t.z))
        lm_r = n_r.to_matrix().to_4x4()
        lm_s = mathutils.Matrix.Diagonal((n_s.x, n_s.y, n_s.z, 1.0))
        n_raw_mat = lm_t @ lm_r @ lm_s
        n_local_B = P @ n_raw_mat @ P_inv

        # Calculate Global by walking hierarchy
        if pb.parent:
            parent_global = get_native_global(pb.parent)
            g_mat = parent_global @ n_local_B
        else:
            g_mat = n_local_B
            
        native_global_rest[pb.name] = g_mat
        return g_mat

    for pbone in bones:
        get_native_global(pbone)

    # --- 2. Calculate Correction Matrices (MATCHING IMPORT: C = Ng.inv @ Vg) ---
    corrections = {}
    for pbone in bones:
        v_global = pbone.bone.matrix_local  # Visual Global Rest
        n_global = native_global_rest[pbone.name]
        corrections[pbone.name] = n_global.inverted() @ v_global

    # --- 3. Collect Frame Data ---
    joint_data = {}  # joint_hash -> list of (t_id, s_id, r_id) per frame
    
    current_frame_orig = bpy.context.scene.frame_current
    
    try:
        for f_idx in range(frame_count):
            frame = frame_start + f_idx
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            
            for pbone in bones:
                # Get current animated Visual Local matrix
                if pbone.parent:
                    v_local_anim = pbone.parent.matrix.inverted() @ pbone.matrix
                else:
                    v_local_anim = pbone.matrix
                
                # Get corrections
                C_child = corrections[pbone.name]
                C_parent = corrections[pbone.parent.name] if pbone.parent else mathutils.Matrix.Identity(4)
                
                # REVERSE the import formula:
                # Import: v_local = C_parent.inv @ n_local_B @ C_child
                # Export: n_local_B = C_parent @ v_local @ C_child.inv
                n_local_B = C_parent @ v_local_anim @ C_child.inverted()
                
                # Convert from Blender space to Native/LoL space: n_local_L = P_inv @ n_local_B @ P
                n_local_L = P_inv @ n_local_B @ P
                
                # Decompose
                t, r, s = n_local_L.decompose()
                
                # NOTE: Not applying flip because our import doesn't flip either
                # Maya does flip on both import and export, we do neither
                # t = mathutils.Vector((-t.x, t.y, t.z))
                # r = mathutils.Quaternion((r.w, r.x, -r.y, -r.z))
                
                # Add to palettes
                t_id = add_to_vec_palette(t)
                s_id = add_to_vec_palette(s)
                r_id = add_to_quat_palette(r)
                
                # Hash the bone name (strip .001 suffixes)
                bone_name = pbone.name.split('.')[0] if '.' in pbone.name else pbone.name
                h = Hash.elf(bone_name)
                
                if h not in joint_data:
                    joint_data[h] = []
                
                if len(joint_data[h]) == f_idx:
                    joint_data[h].append((t_id, s_id, r_id))
                    
    finally:
        bpy.context.scene.frame_set(current_frame_orig)

    # --- 4. Write Binary File ---
    sorted_hashes = sorted(joint_data.keys())
    
    with open(filepath, 'wb') as f:
        bs = BinaryStream(f)
        
        # Header
        bs.write_ascii('r3d2anmd')
        bs.write_uint32(4)  # version
        
        bs.write_uint32(0)  # filesize placeholder (offset 12)
        bs.write_uint32(0xBE0794D3, 0, 0)  # format token, unknown, flags
        
        bs.write_uint32(len(joint_data), frame_count)
        bs.write_float(1.0 / fps)  # frame duration
        
        bs.write_int32(0, 0, 0)  # tracks offset, asset name offset, time offset (unused in v4)
        
        vecs_offset_pos = bs.tell()
        bs.write_int32(64)  # vecs offset (always 64 for v4)
        bs.write_int32(0, 0)  # quats offset, frames offset (fill later)
        
        bs.stream.write(b'\x00' * 12)  # Padding to reach offset 64
        
        # Write vector palette
        for v in vec_palette:
            bs.write_float(v.x, v.y, v.z)
            
        quat_offset = bs.tell() - 12  # Subtract 12 as per v4 format spec
        
        # Write quaternion palette (x, y, z, w order)
        for q in quat_palette:
            bs.write_float(q.x, q.y, q.z, q.w)
            
        frame_offset = bs.tell() - 12
        
        # Write frame data: for each frame, for each joint
        for f_idx in range(frame_count):
            for h in sorted_hashes:
                frames = joint_data[h]
                if f_idx < len(frames):
                    t_id, s_id, r_id = frames[f_idx]
                else:
                    t_id, s_id, r_id = (0, 0, 0)
                    
                bs.write_uint32(h)
                bs.write_uint16(t_id, s_id, r_id, 0)  # t, s, r indices + padding
        
        # Patch file size
        total_size = bs.tell()
        bs.seek(12)
        bs.write_uint32(total_size)
        
        # Patch offsets
        bs.seek(vecs_offset_pos + 4)
        bs.write_int32(quat_offset, frame_offset)
    
    return True

def save(operator, context, filepath, target_armature=None):
    armature_obj = target_armature
    
    if not armature_obj:
        armature_obj = context.active_object
        if not armature_obj or armature_obj.type != 'ARMATURE':
            armature_obj = next((o for o in context.scene.objects if o.type == 'ARMATURE'), None)
        
    if not armature_obj:
        operator.report({'ERROR'}, "No Armature found")
        return {'CANCELLED'}
    
    try:
        fps = context.scene.render.fps
        write_anm(filepath, armature_obj, fps)
        operator.report({'INFO'}, f"Exported ANM: {filepath}")
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
