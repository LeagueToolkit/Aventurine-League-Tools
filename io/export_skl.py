import bpy
import mathutils
import os
from ..utils.binary_utils import BinaryStream, Hash

def write_skl(filepath, armature_obj):
    """Write Blender armature to SKL file (Version 0)"""
    
    # Coordinate conversion matrix P (X-mirror + Y-up to Z-up)
    P = mathutils.Matrix(((-1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    P_inv = P.inverted()
    
    # Get bones and preserve order
    bones = armature_obj.pose.bones
    bone_list = list(bones)
    bone_name_to_index = {b.name: i for i, b in enumerate(bone_list)}
    
    joint_count = len(bone_list)
    
    # --- Pre-calculate Matrices (Recursive) to handle Mix of Native/New bones ---
    # format: [bone_index] = (Matrix_Global_League, Matrix_Local_League)
    
    league_matrices = {} 
    
    def calc_league_matrix(bone_idx):
        if bone_idx in league_matrices:
            return league_matrices[bone_idx]
            
        pbone = bone_list[bone_idx]
        
        # 1. Determine Local League Matrix
        nb_t = pbone.get("native_bind_t")
        nb_r = pbone.get("native_bind_r")
        nb_s = pbone.get("native_bind_s")
        
        if nb_t and nb_r and nb_s:
            # Use Original Native Bind (Preserves offsets and orientation)
            # This ignores Blender's visual edits to Head/Tail, which is GOOD for game compatibility
            lm_t = mathutils.Matrix.Translation(mathutils.Vector(nb_t))
            lm_r = mathutils.Quaternion(nb_r).to_matrix().to_4x4()
            lm_s = mathutils.Matrix.Diagonal((nb_s[0], nb_s[1], nb_s[2], 1.0))
            l_mat_local = lm_t @ lm_r @ lm_s
        else:
            # New Bone or Missing Data: Convert Blender Rest Pose to League
            # Blender Local: Parent_Inv @ Child
            if pbone.parent:
                b_local = pbone.parent.bone.matrix_local.inverted() @ pbone.bone.matrix_local
            else:
                b_local = pbone.bone.matrix_local
            
            # Convert to League: L = P_inv @ B @ P
            l_mat_local = P_inv @ b_local @ P
            
        # 2. Determine Global League Matrix
        parent_idx = bone_name_to_index.get(pbone.parent.name) if pbone.parent else -1
        
        if parent_idx >= 0:
            parent_global, _ = calc_league_matrix(parent_idx)
            l_mat_global = parent_global @ l_mat_local
        else:
            l_mat_global = l_mat_local
            
        league_matrices[bone_idx] = (l_mat_global, l_mat_local)
        return l_mat_global, l_mat_local

    # Compute all
    for i in range(joint_count):
        calc_league_matrix(i)

    with open(filepath, 'wb') as f:
        bs = BinaryStream(f)
        
        # 1. Header 
        bs.write_uint32(0) # Resource size placeholder
        bs.write_uint32(0x22FD4FC3) # Magic
        bs.write_uint32(0) # Version
        
        bs.write_uint16(0) # Flags
        bs.write_uint16(joint_count)
        bs.write_uint32(joint_count) # Influence count
        
        # Offsets
        joints_offset = 64
        joint_indices_offset = joints_offset + joint_count * 100
        influences_offset = joint_indices_offset + joint_count * 8
        joint_names_offset = influences_offset + joint_count * 2
        
        bs.write_int32(joints_offset, joint_indices_offset, influences_offset, 0, 0, joint_names_offset)
        
        # 5 Reserved offsets
        for _ in range(5):
            bs.write_uint32(0xFFFFFFFF)
            
        # 2. Names
        name_offsets = {}
        bs.seek(joint_names_offset)
        for i, pbone in enumerate(bone_list):
            name_offsets[i] = bs.tell()
            name = pbone.name.split('.')[0] if '.' in pbone.name else pbone.name
            bs.write_ascii(name)
            bs.write_uint8(0)
            
        # 3. Joint Data
        bs.seek(joints_offset)
        for i, pbone in enumerate(bone_list):
            bs.write_uint16(0) # flags
            bs.write_uint16(i) # id
            
            parent_idx = -1
            if pbone.parent:
                parent_idx = bone_name_to_index.get(pbone.parent.name, -1)
            bs.write_int16(parent_idx)
            
            bs.write_uint16(0) # flags
            clean_name = pbone.name.split('.')[0] if '.' in pbone.name else pbone.name
            bs.write_uint32(Hash.elf(clean_name))
            bs.write_float(2.1) # radius
            
            # Retrieve calculated matrices
            l_mat_global, l_mat_local = league_matrices[i]
            
            # Local Transform (TRS)
            l_t, l_r, l_s = l_mat_local.decompose()
            
            bs.write_vec3(l_t)
            bs.write_vec3(l_s)
            bs.write_quat(l_r)
            
            # Inversed Global Transform (Bind Matrix Inv)
            ig_mat = l_mat_global.inverted()
            ig_t, ig_r, ig_s = ig_mat.decompose()
            
            bs.write_vec3(ig_t)
            bs.write_vec3(ig_s)
            bs.write_quat(ig_r)
            
            # Name offset
            curr_pos = bs.tell()
            bs.write_int32(name_offsets[i] - curr_pos)
            
        # 4. Indices and Influences
        bs.seek(joint_indices_offset)
        for i, pbone in enumerate(bone_list):
            bs.write_uint16(i)
            bs.write_uint16(0)
            clean_name = pbone.name.split('.')[0] if '.' in pbone.name else pbone.name
            bs.write_uint32(Hash.elf(clean_name))
            
        bs.seek(influences_offset)
        for i in range(joint_count):
            bs.write_uint16(i)
            
        # 6. Finalize Size
        total_size = bs.tell()
        bs.seek(0)
        bs.write_uint32(total_size)
        
    return True

def save(operator, context, filepath, target_armature=None):
    armature_obj = target_armature
    
    if not armature_obj:
        armature_obj = context.active_object
        if not armature_obj or armature_obj.type != 'ARMATURE':
            # Try to find an armature in the scene
            armature_obj = next((obj for obj in context.scene.objects if obj.type == 'ARMATURE'), None)
        
    if not armature_obj:
        operator.report({'ERROR'}, "No Armature found in scene")
        return {'CANCELLED'}
    
    try:
        write_skl(filepath, armature_obj)
        operator.report({'INFO'}, f"Exported SKL: {filepath}")
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
