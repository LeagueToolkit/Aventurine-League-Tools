"""ANM animation importer - Matrix-based robust transform conversion"""
import bpy
import mathutils
import math
import os
from ..utils.binary_utils import BinaryStream, Vector, Quaternion, Hash


class ANMPose:
    __slots__ = ('translation', 'rotation', 'scale')
    
    def __init__(self):
        self.translation = None
        self.rotation = None
        self.scale = None


class ANMTrack:
    __slots__ = ('joint_hash', 'poses')
    
    def __init__(self, joint_hash):
        self.joint_hash = joint_hash
        self.poses = {} # f -> ANMPose


class ANMData:
    __slots__ = ('fps', 'duration', 'tracks', 'frame_count')
    
    def __init__(self):
        self.fps = 30.0
        self.duration = 0.0
        self.tracks = []
        self.frame_count = 0


def decompress_quat(bytes_data):
    first = bytes_data[0] | (bytes_data[1] << 8)
    second = bytes_data[2] | (bytes_data[3] << 8)
    third = bytes_data[4] | (bytes_data[5] << 8)
    bits = first | (second << 16) | (third << 32)
    
    max_index = (bits >> 45) & 3
    one_div_sqrt2 = 0.70710678118
    sqrt2_div_32767 = 0.00004315969
    
    a = ((bits >> 30) & 32767) * sqrt2_div_32767 - one_div_sqrt2
    b = ((bits >> 15) & 32767) * sqrt2_div_32767 - one_div_sqrt2
    c = (bits & 32767) * sqrt2_div_32767 - one_div_sqrt2
    d = math.sqrt(max(0.0, 1.0 - (a * a + b * b + c * c)))
    
    # components: x, y, z, w correspond to d, a, b, c depending on max_index
    if max_index == 0:
        return mathutils.Quaternion((c, d, a, b)) # (w, x, y, z)
    elif max_index == 1:
        return mathutils.Quaternion((c, a, d, b))
    elif max_index == 2:
        return mathutils.Quaternion((c, a, b, d))
    else:
        return mathutils.Quaternion((d, a, b, c))


def read_anm(filepath):
    anm = ANMData()
    
    with open(filepath, 'rb') as f:
        bs = BinaryStream(f)
        
        magic = bs.read_ascii(8)
        version = bs.read_uint32()
        
        if magic == 'r3d2canm':
            # Compressed ANM
            bs.pad(12) # Resource size, token, flags
            joint_count, frame_count = bs.read_uint32(2)
            bs.pad(4) # jump cache count
            
            max_time, anm.fps = bs.read_float(2)
            anm.duration = max_time + 1.0 / anm.fps
            anm.frame_count = int(round(anm.duration * anm.fps))
            
            bs.pad(24) # Quantization properties
            translation_min = bs.read_vec3()
            translation_max = bs.read_vec3()
            scale_min = bs.read_vec3()
            scale_max = bs.read_vec3()
            
            frames_offset = bs.read_int32()
            bs.pad(4) # jump caches
            joint_hashes_offset = bs.read_int32()
            
            # Read joint hashes
            bs.seek(joint_hashes_offset + 12)
            joint_hashes = bs.read_uint32(joint_count)
            if not isinstance(joint_hashes, (list, tuple)):
                joint_hashes = [joint_hashes]
            
            anm.tracks = [ANMTrack(h) for h in joint_hashes]
            
            # Read compressed frames
            bs.seek(frames_offset + 12)
            for i in range(frame_count):
                compressed_time, bits = bs.read_uint16(2)
                compressed_transform = bs.read_bytes(6)
                
                joint_idx = bits & 16383
                if joint_idx >= joint_count:
                    continue
                    
                track = anm.tracks[joint_idx]
                time = compressed_time / 65535.0 * max_time
                frame_id = int(round(time * anm.fps))
                
                if frame_id not in track.poses:
                    pose = ANMPose()
                    track.poses[frame_id] = pose
                else:
                    pose = track.poses[frame_id]
                
                transform_type = bits >> 14
                if transform_type == 0: # Rotation
                    pose.rotation = decompress_quat(compressed_transform)
                elif transform_type == 1: # Translation
                    v = compressed_transform
                    tx = (translation_max.x - translation_min.x) / 65535.0 * (v[0] | (v[1] << 8)) + translation_min.x
                    ty = (translation_max.y - translation_min.y) / 65535.0 * (v[2] | (v[3] << 8)) + translation_min.y
                    tz = (translation_max.z - translation_min.z) / 65535.0 * (v[4] | (v[5] << 8)) + translation_min.z
                    pose.translation = mathutils.Vector((tx, ty, tz))
                elif transform_type == 2: # Scale
                    v = compressed_transform
                    sx = (scale_max.x - scale_min.x) / 65535.0 * (v[0] | (v[1] << 8)) + scale_min.x
                    sy = (scale_max.y - scale_min.y) / 65535.0 * (v[2] | (v[3] << 8)) + scale_min.y
                    sz = (scale_max.z - scale_min.z) / 65535.0 * (v[4] | (v[5] << 8)) + scale_min.z
                    pose.scale = mathutils.Vector((sx, sy, sz))

        elif magic == 'r3d2anmd':
            # Uncompressed ANM (v4, v5)
            if version == 5:
                bs.pad(16) # size, token, version, flags
                track_count, frame_count = bs.read_uint32(2)
                
                frame_duration = bs.read_float()
                anm.fps = 1.0 / frame_duration
                anm.duration = frame_count * frame_duration
                anm.frame_count = frame_count
                
                joint_hashes_offset = bs.read_int32()
                bs.pad(8) # asset name, time
                vecs_offset, quats_offset, frames_offset = bs.read_int32(3)
                
                # Joint hashes
                bs.seek(joint_hashes_offset + 12)
                joint_hashes = bs.read_uint32(track_count)
                if not isinstance(joint_hashes, (list, tuple)):
                    joint_hashes = [joint_hashes]
                
                # Vector palette
                bs.seek(vecs_offset + 12)
                vec_count = (quats_offset - vecs_offset) // 12
                vec_palette = [mathutils.Vector(bs.read_float(3)) for _ in range(vec_count)]
                
                # Quat palette (quantized)
                bs.seek(quats_offset + 12)
                quat_count = (joint_hashes_offset - quats_offset) // 6
                quat_palette = [decompress_quat(bs.read_bytes(6)) for _ in range(quat_count)]
                
                # Tracks
                anm.tracks = [ANMTrack(h) for h in joint_hashes]
                
                # Frames data
                bs.seek(frames_offset + 12)
                for f in range(frame_count):
                    for t in range(track_count):
                        trans_idx, scale_idx, rot_idx = bs.read_uint16(3)
                        pose = ANMPose()
                        pose.translation = vec_palette[trans_idx]
                        pose.scale = vec_palette[scale_idx]
                        pose.rotation = quat_palette[rot_idx]
                        anm.tracks[t].poses[f] = pose

            elif version == 4:
                bs.pad(16)
                track_count, frame_count = bs.read_uint32(2)
                frame_duration = bs.read_float()
                anm.fps = 1.0 / frame_duration
                anm.duration = frame_count * frame_duration
                anm.frame_count = frame_count
                
                bs.pad(12)
                vecs_offset, quats_offset, frames_offset = bs.read_int32(3)
                
                # Vector palette
                bs.seek(vecs_offset + 12)
                vec_count = (quats_offset - vecs_offset) // 12
                vec_palette = [mathutils.Vector(bs.read_float(3)) for _ in range(vec_count)]
                
                # Quat palette (Full 16-byte)
                bs.seek(quats_offset + 12)
                quat_count = (frames_offset - quats_offset) // 16
                quat_palette = []
                for _ in range(quat_count):
                    q = bs.read_float(4)
                    quat_palette.append(mathutils.Quaternion((q[3], q[0], q[1], q[2]))) # (w, x, y, z)
                
                # Read frames with embedded hashes
                bs.seek(frames_offset + 12)
                hash_to_track = {}
                for f in range(frame_count):
                    for _ in range(track_count):
                        joint_hash = bs.read_uint32()
                        trans_idx, scale_idx, rot_idx = bs.read_uint16(3)
                        bs.pad(2) # padding
                        
                        if joint_hash not in hash_to_track:
                            track = ANMTrack(joint_hash)
                            hash_to_track[joint_hash] = track
                            anm.tracks.append(track)
                        
                        pose = ANMPose()
                        pose.translation = vec_palette[trans_idx]
                        pose.scale = vec_palette[scale_idx]
                        pose.rotation = quat_palette[rot_idx]
                        hash_to_track[joint_hash].poses[f] = pose
            else:
                # Legacy r3d2anmd (v3 or other old versions)
                bs.pad(4) # skl id
                track_count, frame_count = bs.read_uint32(2)
                anm.fps = float(bs.read_uint32())
                if anm.fps == 0:
                    anm.fps = 30.0
                anm.duration = frame_count / anm.fps
                anm.frame_count = frame_count
                
                for i in range(track_count):
                    joint_name = bs.read_padded_ascii(32).rstrip('\0')
                    joint_hash = Hash.elf(joint_name)
                    bs.pad(4) # flags
                    
                    track = ANMTrack(joint_hash)
                    anm.tracks.append(track)
                    
                    for f_id in range(frame_count):
                        q = bs.read_float(4)
                        t = bs.read_float(3)
                        pose = ANMPose()
                        pose.rotation = mathutils.Quaternion((q[3], q[0], q[1], q[2]))
                        pose.translation = mathutils.Vector(t)
                        pose.scale = mathutils.Vector((1, 1, 1))
                        track.poses[f_id] = pose

        else:
            # Legacy ANM (v1, v2, v3)
            f.seek(8)
            version = bs.read_uint32()
            bs.pad(4) # skl id
            track_count, frame_count = bs.read_uint32(2)
            anm.fps = float(bs.read_uint32())
            if anm.fps == 0:
                anm.fps = 30.0
            anm.duration = frame_count / anm.fps
            anm.frame_count = frame_count
            
            for i in range(track_count):
                joint_name = bs.read_padded_ascii(32).rstrip('\0')
                joint_hash = Hash.elf(joint_name)
                bs.pad(4) # flags
                
                track = ANMTrack(joint_hash)
                anm.tracks.append(track)
                
                for f_id in range(frame_count):
                    q = bs.read_float(4)
                    t = bs.read_float(3)
                    pose = ANMPose()
                    pose.rotation = mathutils.Quaternion((q[3], q[0], q[1], q[2]))
                    pose.translation = mathutils.Vector(t)
                    pose.scale = mathutils.Vector((1, 1, 1))
                    track.poses[f_id] = pose
    
    return anm


def apply_anm(anm, armature_obj, frame_offset=0):
    if armature_obj.type != 'ARMATURE':
        return
        
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')
    
    # Bone map: Hash -> PoseBone
    bone_map = {}
    for bone in armature_obj.pose.bones:
        bone.rotation_mode = 'QUATERNION'
        h = Hash.elf(bone.name)
        bone_map[h] = bone
        
    # Set scene settings (only if not inserting at offset)
    scene = bpy.context.scene
    scene.render.fps = int(max(1, anm.fps))
    if frame_offset == 0:
        scene.frame_start = 0
        # Offset end frame by 1 because we are shifting all keys by +1
        scene.frame_end = max(0, anm.frame_count)
    
    # Matrix P: X'=-x, Y'=-z, Z'=y
    P = mathutils.Matrix(((-1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    P_inv = P.inverted()
    
    # --- 1. Reconstruct NATIVE Global Rest Pose Hierarchy ---
    # We need to know exactly where the Native bones are in Blender Global Space
    # so we can compare them to the Visual bones.
    
    native_global_rest = {}
    
    # Iterate in hierarchy order (parents first)
    # We can rely on pose.bones iteration if the list is sorted, but safe to do recursive or robust loop
    # Blender pose.bones is usually sorted by hierarchy? Not guaranteed.
    # Let's do a safe topological sort or just map parents.
    
    def get_native_global(pb):
        if pb.name in native_global_rest:
            return native_global_rest[pb.name]
        
        # Get Native Bind Local (in Blender Space)
        nb_t = pb.get("native_bind_t")
        if nb_t:
             # Tuple to Vector
            n_t = mathutils.Vector(nb_t)
            n_r = mathutils.Quaternion(pb.get("native_bind_r"))
            s_val = pb.get("native_bind_s")
            n_s = mathutils.Vector(s_val) if s_val else mathutils.Vector((1,1,1))
        else:
            # Fallback to current bind props (approximate)
            n_t = mathutils.Vector((-pb.get("bind_translation").x, pb.get("bind_translation").z, -pb.get("bind_translation").y))
            # Just use Identity for rot fallback if critical fail, but usually bind_quat works
            n_r = mathutils.Quaternion((1,0,0,0)) 
            n_s = mathutils.Vector((1,1,1))

        # Build Native Local Matrix in Blender Space (P @ M @ P_inv)
        # N_local_B = P @ LocRotScale(nt, nr, ns) @ P_inv
        lm_t = mathutils.Matrix.Translation((n_t.x, n_t.y, n_t.z))
        lm_r = n_r.to_matrix().to_4x4()
        lm_s = mathutils.Matrix.Diagonal((n_s.x, n_s.y, n_s.z, 1.0))
        n_raw_mat = lm_t @ lm_r @ lm_s
        n_local_B = P @ n_raw_mat @ P_inv

        # Calc Global
        if pb.parent:
            parent_global = get_native_global(pb.parent)
            g_mat = parent_global @ n_local_B
        else:
            g_mat = n_local_B
            
        native_global_rest[pb.name] = g_mat
        return g_mat

    for pbone in armature_obj.pose.bones:
        get_native_global(pbone)

    # --- 2. Calculate Correction Matrices ---
    # Correction = Native_Global_Rest.inv @ Visual_Global_Rest
    # This maps a point from Native Global Space to Visual Global Space.
    corrections = {}
    visual_global_rest = {}
    
    for pbone in armature_obj.pose.bones:
        # Visual Global Rest is just the Edit Bone's matrix (matrix_local in pose bone is essentially that if no Anim)
        # Actually pbone.bone.matrix_local IS the rest matrix in Armature space.
        v_global = pbone.bone.matrix_local
        visual_global_rest[pbone.name] = v_global
        
        n_global = native_global_rest[pbone.name]
        
        # C = Ng.inv @ Vg
        corrections[pbone.name] = n_global.inverted() @ v_global

    # --- 3. Apply Animation with Retargeting ---
    
    # Tracks dictionary
    tracks_dict = {t.joint_hash: t for t in anm.tracks}
    
    # Apply animations
    matched_count = 0
    for pbone in armature_obj.pose.bones:
        pbone_hash = Hash.elf(pbone.name)
        track = tracks_dict.get(pbone_hash)
        if track:
            matched_count += 1
            
        # Get Pre-calculated data
        C_child = corrections[pbone.name]
        if pbone.parent:
            C_parent = corrections[pbone.parent.name]
        else:
            # If no parent, Correction is Identity? No.
            # If no parent, Parent Global is Identity.
            # C_parent = (Native_Parent_Global.inv @ Visual_Parent_Global)
            # Both are Identity (World Origin).
            C_parent = mathutils.Matrix.Identity(4)

        # Fallback values
        nb_t = pbone.get("native_bind_t")
        if nb_t:
            def_t = mathutils.Vector(nb_t)
            def_r = mathutils.Quaternion(pbone.get("native_bind_r"))
            s_val = pbone.get("native_bind_s")
            def_s = mathutils.Vector(s_val) if s_val else mathutils.Vector((1,1,1))
        else:
            def_t = mathutils.Vector((0,0,0))
            def_r = mathutils.Quaternion((1,0,0,0))
            def_s = mathutils.Vector((1,1,1))
        
        # Helper to set keyframe with Selective Keying
        def set_keyframe(frame, n_local_B, has_t=True, has_r=True, has_s=True):
            # Formula: Visual_Local = C_parent.inv @ Native_Local @ C_child
            
            # Retarget
            v_local = C_parent.inverted() @ n_local_B @ C_child
            
            # Handle Rest Pose Compensation (Blender Basis)
            # Basis = Rest_Visual_Local.inv @ v_local
            
            # Get "Rest Visual Local"
            if pbone.parent:
                rest_v_parent = pbone.parent.bone.matrix_local
                rest_v_child = pbone.bone.matrix_local
                rest_v_local = rest_v_parent.inverted() @ rest_v_child
            else:
                rest_v_local = pbone.bone.matrix_local

            basis_mat = rest_v_local.inverted() @ v_local
            
            loc, rot, sca = basis_mat.decompose()
            pbone.location = loc
            pbone.rotation_quaternion = rot
            pbone.scale = sca
            
            # Only insert keys for components that actually contain data
            if has_t:
                pbone.keyframe_insert(data_path="location", frame=frame)
            if has_r:
                pbone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            if has_s:
                pbone.keyframe_insert(data_path="scale", frame=frame)

        # Keyframe 0 (Bind Pose) - Only when creating new action (frame_offset == 0)
        # Skip when inserting into existing action to avoid snapping to T-pose
        if frame_offset == 0:
            lm_t = mathutils.Matrix.Translation((def_t.x, def_t.y, def_t.z))
            lm_r = def_r.to_matrix().to_4x4()
            lm_s = mathutils.Matrix.Diagonal((def_s.x, def_s.y, def_s.z, 1.0))
            n_bind_B = P @ (lm_t @ lm_r @ lm_s) @ P_inv
            
            set_keyframe(0, n_bind_B, True, True, True)

        if not track:
            continue

        # 2. Keyframe Animation Frames (Sparse Selective)
        for f_id, pose in track.poses.items():
            
            # Start with Native relative components
            n_t = pose.translation if (pose and pose.translation) else None
            n_r = pose.rotation if (pose and pose.rotation) else None
            n_s = pose.scale if (pose and pose.scale) else None
            
            has_t = n_t is not None
            has_r = n_r is not None
            has_s = n_s is not None
            
            # Reconstruct matrix using Fallbacks for missing parts
            # This is necessary because 'Retargeting' is a matrix op that needs a full matrix.
            # Even if we don't keyframe Translation, we need a Translation value to build the matrix
            # so that Rotation can be retargeted correctly (interactions).
            cur_t = n_t if n_t is not None else def_t
            cur_r = n_r if n_r is not None else def_r
            cur_s = n_s if n_s is not None else def_s
            
            # Build Native Matrix (l_mat)
            lm_t = mathutils.Matrix.Translation((cur_t.x, cur_t.y, cur_t.z))
            lm_r = cur_r.to_matrix().to_4x4()
            lm_s = mathutils.Matrix.Diagonal((cur_s.x, cur_s.y, cur_s.z, 1.0))
            l_mat = lm_t @ lm_r @ lm_s
            
            # Transform to Blender Space: N_target_B = P @ l_mat @ P_inv
            N_target_B = P @ l_mat @ P_inv
            
            # Start Actual Animation at Frame 1 (f_id + 1) + offset
            set_keyframe(frame_offset + f_id + 1, N_target_B, has_t, has_r, has_s)

    print(f"Matched {matched_count} tracks to bones")
    
    # Ensure interpolation mode is linear or suitable?
    # By default Blender uses Bezier. LtMAO uses Linear/Cubic. 
    # For now, let's leave default, but sparse keys fix is the main target.

    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Force update and reset to start frame to fix "glitchy first frame" visual bug
    bpy.context.view_layer.update()
    bpy.context.scene.frame_set(bpy.context.scene.frame_start)


def load(operator, context, filepath, create_new_action=True, insert_frame=0):
    armature_obj = context.active_object
    if not armature_obj or armature_obj.type != 'ARMATURE':
        for obj in context.scene.objects:
            if obj.type == 'ARMATURE':
                armature_obj = obj
                break
                
    if not armature_obj:
        operator.report({'ERROR'}, "No active armature found to apply animation to")
        return {'CANCELLED'}
        
    try:
        anm = read_anm(filepath)
        
        # Get action name from filename (without extension)
        action_name = os.path.splitext(os.path.basename(filepath))[0]
        
        if create_new_action:
            # Create a new action
            if not armature_obj.animation_data:
                armature_obj.animation_data_create()
            
            # Create new action with the ANM filename
            new_action = bpy.data.actions.new(name=action_name)
            armature_obj.animation_data.action = new_action
            
            # Apply animation starting at frame 0 (with +1 offset for bind pose)
            apply_anm(anm, armature_obj, frame_offset=0)
            
            # Store info on the action
            new_action["lol_anm_filepath"] = filepath
            new_action["lol_anm_filename"] = os.path.basename(filepath)
            
            operator.report({'INFO'}, f"Imported animation '{action_name}': {anm.frame_count} frames")
        else:
            # Insert into existing action at specified frame
            if not armature_obj.animation_data or not armature_obj.animation_data.action:
                operator.report({'ERROR'}, "No existing action to insert into. Use 'New Action' mode first.")
                return {'CANCELLED'}
            
            # Apply animation with frame offset
            apply_anm(anm, armature_obj, frame_offset=insert_frame)
            
            # Extend scene end frame if needed
            new_end = insert_frame + anm.frame_count
            if context.scene.frame_end < new_end:
                context.scene.frame_end = new_end
            
            operator.report({'INFO'}, f"Inserted '{action_name}' at frame {insert_frame}: {anm.frame_count} frames")
        
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed to load ANM: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
