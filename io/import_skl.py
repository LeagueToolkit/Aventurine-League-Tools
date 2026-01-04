"""SKL skeleton importer - Visual skeleton layout without leaf bones"""
import bpy
import mathutils
from ..utils.binary_utils import BinaryStream


class SKLJoint:
    __slots__ = ('name', 'parent', 'local_translation', 'local_scale', 'local_rotation', 'global_pos',
                 'raw_trans', 'raw_rot', 'raw_scale')
    
    def __init__(self):
        self.name = None
        self.parent = None
        self.local_translation = None
        self.local_scale = None
        self.local_rotation = None
        self.global_pos = None
        # Raw native components
        self.raw_trans = None
        self.raw_rot = None
        self.raw_scale = None


def read_skl(filepath):
    joints = []
    influences = []
    
    with open(filepath, 'rb') as f:
        bs = BinaryStream(f)
        
        bs.pad(4) # Resource size
        magic = bs.read_uint32()
        
        if magic == 0x22FD4FC3:
            version = bs.read_uint32()
            if version != 0:
                raise Exception(f'Unsupported SKL version: {version}')
            
            bs.pad(2) # flags
            joint_count = bs.read_uint16()
            influence_count = bs.read_uint32()
            joints_offset = bs.read_int32()
            bs.pad(4) # joint indices offset
            influences_offset = bs.read_int32()
            bs.pad(32) # Other offsets and reserved
            
            # Read joints
            if joints_offset > 0:
                bs.seek(joints_offset)
                joints = [SKLJoint() for _ in range(joint_count)]
                
                for i in range(joint_count):
                    joint = joints[i]
                    
                    # 16 bytes header per joint
                    bs.pad(4) # flags and id
                    joint.parent = bs.read_int16()
                    bs.pad(10) # flags(2) + hash(4) + radius(4)
                    
                    # Local transform
                    trans = bs.read_vec3()
                    scale = bs.read_vec3()
                    rot_raw = bs.read_quat()
                    rot = mathutils.Quaternion((rot_raw.w, rot_raw.x, rot_raw.y, rot_raw.z))
                    
                    joint.raw_trans = trans
                    joint.raw_rot = rot
                    joint.raw_scale = scale
                    
                    # League to Blender (Y-up to Z-up)
                    # Mapping: X' = -x (Mirror), Y' = -z, Z' = y
                    P = mathutils.Matrix(((-1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
                    P_inv = P.inverted()
                    
                    # League Local Matrix (Order: T * R * S)
                    l_t = mathutils.Matrix.Translation(trans)
                    # rot is (x,y,z,w) from read_quat
                    l_r = mathutils.Quaternion((rot.w, rot.x, rot.y, rot.z)).to_matrix().to_4x4()
                    l_s = mathutils.Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0))
                    l_mat = l_t @ l_r @ l_s
                    
                    # Blender Local Matrix
                    b_mat = P @ l_mat @ P_inv
                    b_t, b_r, b_s = b_mat.decompose()
                    
                    joint.local_translation = b_t
                    joint.local_rotation = b_r
                    joint.local_scale = b_s
                    
                    # Inversed global transform (40 bytes)
                    bs.pad(40)
                    
                    joint_name_offset = bs.read_int32()
                    return_offset = bs.tell()
                    bs.seek(return_offset - 4 + joint_name_offset)
                    joint.name = bs.read_char_until_zero().rstrip('\0')
                    
                    if i == 0 and joint.name == '':
                        bs.pad(1)
                        joint.name = bs.read_char_until_zero()
                    
                    bs.seek(return_offset)
            
            # Read influences mapping
            if influences_offset > 0 and influence_count > 0:
                bs.seek(influences_offset)
                influences = bs.read_uint16(influence_count)
                if not isinstance(influences, (list, tuple)):
                    influences = [influences]

        else:
            raise Exception('Legacy SKL or wrong signature')
    
    return joints, influences


def create_armature(joints, name="Armature"):
    # Pass 1: Global positions via matrices
    global_pos = [mathutils.Vector((0,0,0))] * len(joints)
    mats = [mathutils.Matrix.Identity(4)] * len(joints)
    
    for i, joint in enumerate(joints):
        mat_t = mathutils.Matrix.Translation(joint.local_translation)
        mat_r = joint.local_rotation.to_matrix().to_4x4()
        local_mat = mat_t @ mat_r
        
        if joint.parent >= 0:
            mats[i] = mats[joint.parent] @ local_mat
        else:
            mats[i] = local_mat
        
        joint.global_pos = mats[i].to_translation()
    
    armature_data = bpy.data.armatures.new(name)
    armature_obj = bpy.data.objects.new(name, armature_data)
    bpy.context.scene.collection.objects.link(armature_obj)
    bpy.context.view_layer.objects.active = armature_obj
    
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Pass 2: Create bones and set heads
    for i, joint in enumerate(joints):
        bone = armature_data.edit_bones.new(joint.name)
        bone.head = joint.global_pos
        # Temporary tail
        bone.tail = bone.head + mathutils.Vector((0, 0, 0.1))
        
    # Pass 3: Set Parenting
    for i, joint in enumerate(joints):
        if joint.parent >= 0:
            bone = armature_data.edit_bones[joint.name]
            parent_bone = armature_data.edit_bones[joints[joint.parent].name]
            bone.parent = parent_bone

    # Pass 4: Set tails (Point to Child)
    for bone in armature_data.edit_bones:
        if bone.children:
            # Point to first child
            child = bone.children[0]
            if (child.head - bone.head).length > 0.001:
                bone.tail = child.head
            else:
                # Fallback direction if child at same spot
                bone.tail = bone.head + mathutils.Vector((0, 0, 0.1))
        else:
            # TERMINAL BONE: Apply rotation/direction from parent
            if bone.parent:
                # Inherit direction from parent
                parent_dir = (bone.parent.tail - bone.parent.head)
                if parent_dir.length > 0.001:
                    # Inherit parent's scale/length logic
                    bone.tail = bone.head + parent_dir.normalized() * (bone.parent.length * 0.5)
                else:
                    bone.tail = bone.head + mathutils.Vector((0, 0, 0.1))
            else:
                bone.tail = bone.head + mathutils.Vector((0, 0, 0.1))
        
        # Ensure no zero length
        if (bone.tail - bone.head).length < 0.001:
            bone.tail = bone.head + mathutils.Vector((0, 0, 0.1))

    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Pass 5: Apply scale and store bind pose for animator
    for i, joint in enumerate(joints):
        pbone = armature_obj.pose.bones[joint.name]
        pbone.scale = joint.local_scale
        # Store bind pose for animator fallback (absolute local relative to parent in Blender space)
        pbone["bind_translation"] = joint.local_translation
        pbone["bind_rotation"] = joint.local_rotation
        pbone["bind_scale"] = joint.local_scale
        
        # Store RAW native components for robust fallback in ANM tracks
        # These are what was read from the file before any coordinate conversion.
        # We store them as lists/tuples so they are easy to retrieve.
        # The rotation is stored as mathutils.Quaternion (w,x,y,z)
        pbone["native_bind_t"] = [joint.raw_trans.x, joint.raw_trans.y, joint.raw_trans.z]
        pbone["native_bind_r"] = [joint.raw_rot.w, joint.raw_rot.x, joint.raw_rot.y, joint.raw_rot.z]
        pbone["native_bind_s"] = [joint.raw_scale.x, joint.raw_scale.y, joint.raw_scale.z]

    return armature_obj


def load(operator, context, filepath):
    try:
        import os
        joints, influences = read_skl(filepath)
        armature_obj = create_armature(joints)
        
        # Store import path for export convenience
        armature_obj["lol_skl_filepath"] = filepath
        armature_obj["lol_skl_filename"] = os.path.basename(filepath)
        
        operator.report({'INFO'}, f'Imported {len(joints)} bones')
        return {'FINISHED'}
    
    except Exception as e:
        operator.report({'ERROR'}, f'Failed: {str(e)}')
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}
