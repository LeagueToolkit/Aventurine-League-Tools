"""
LoL Animation Retarget
Transfer animations between LoL skeletons with different bone structures
"""

import bpy
import re
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import StringProperty, PointerProperty, CollectionProperty, EnumProperty
from ..ui import icons


# Common bone name aliases for LoL rigs
BONE_ALIASES = {
    # Spine variations
    'spine3': ['chest', 'buffbone_glb_chest', 'c_chest'],
    'chest': ['spine3', 'buffbone_glb_chest', 'c_spine3'],
    'buffbone_glb_chest': ['chest', 'spine3', 'c_chest'],
    
    # Root variations  
    'root': ['pelvis', 'c_pelvis', 'c_root'],
    'pelvis': ['root', 'c_root', 'c_pelvis'],
    
    # Common prefixed versions
    'c_spine': ['spine', 'spine1'],
    'c_spine1': ['spine1', 'spine'],
    'c_spine2': ['spine2'],
}


def normalize_bone_name(name):
    """Normalize bone name for comparison - remove common prefixes and lowercase"""
    name = name.lower()
    # Remove common prefixes
    prefixes = ['c_', 'l_', 'r_', 'buffbone_', 'glb_', 'cstm_']
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def find_best_match(source_bone_name, target_bones):
    """Find the best matching target bone for a source bone"""
    source_normalized = normalize_bone_name(source_bone_name)
    
    # Priority 1: Exact name match
    if source_bone_name in target_bones:
        return source_bone_name
    
    # Priority 2: Normalized name match
    for target_name in target_bones:
        if normalize_bone_name(target_name) == source_normalized:
            return target_name
    
    # Priority 3: Check aliases
    source_lower = source_bone_name.lower()
    if source_lower in BONE_ALIASES:
        for alias in BONE_ALIASES[source_lower]:
            for target_name in target_bones:
                if target_name.lower() == alias or normalize_bone_name(target_name) == alias:
                    return target_name
    
    # Priority 4: Partial match (contains)
    for target_name in target_bones:
        if source_normalized in normalize_bone_name(target_name) or normalize_bone_name(target_name) in source_normalized:
            return target_name
    
    return None  # No match found


class BoneMappingItem(PropertyGroup):
    """Single bone mapping entry"""
    source_bone: StringProperty(name="Source Bone")
    target_bone: StringProperty(name="Target Bone")
    enabled: bpy.props.BoolProperty(name="Enabled", default=True)


class LOLRetargetProperties(PropertyGroup):
    """Properties for the retarget panel"""
    source_armature: PointerProperty(
        name="Source Armature",
        description="Armature with the animation to copy",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    target_armature: PointerProperty(
        name="Target Armature", 
        description="Armature to apply the animation to",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    bone_mappings: CollectionProperty(type=BoneMappingItem)
    map_root_to_pelvis: bpy.props.BoolProperty(
        name="Map Root to Pelvis",
        description="Map Source Root to Target Pelvis/Hip, and skip Source Pelvis. Useful if Source uses Root for movement but Target uses Pelvis.",
        default=False
    )
    ignore_extras: bpy.props.BoolProperty(
        name="Ignore Extra Bones",
        description="Exclude Buffbones, Hair, Face, Weapon, etc. from mapping",
        default=True
    )
    mapping_generated: bpy.props.BoolProperty(default=False)
    active_mapping_index: bpy.props.IntProperty(default=0)


class LOL_OT_GenerateMapping(Operator):
    """Generate automatic bone mapping between source and target"""
    bl_idname = "lol_retarget.generate_mapping"
    bl_label = "Generate Mapping"
    bl_description = "Auto-detect bone mapping between source and target armatures"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.lol_retarget
        
        if not props.source_armature or not props.target_armature:
            self.report({'ERROR'}, "Select both source and target armatures")
            return {'CANCELLED'}
        
        if props.source_armature == props.target_armature:
            self.report({'ERROR'}, "Source and target must be different armatures")
            return {'CANCELLED'}
        
        source_bones = [b.name for b in props.source_armature.data.bones]
        target_bones = [b.name for b in props.target_armature.data.bones]
        
        # Clear existing mappings
        props.bone_mappings.clear()
        
        matched = 0
        unmatched = 0
        
        # Core Bone Whitelist (Normalized)
        # These are the ONLY bones allowed when strict mode (Ignore Extras) is on
        core_bones = [
            'root', 'pelvis', 'hip', 'spine', 'spine1', 'spine2', 'spine3', 'chest', 'neck', 'head',
            'clavicle', 'shoulder', 'elbow', 'hand',
            'thumb1', 'thumb2', 'thumb3', 
            'index1', 'index2', 'index3', 
            'middle1', 'middle2', 'middle3', 
            'ring1', 'ring2', 'ring3', 
            'pinky1', 'pinky2', 'pinky3',
            'knee', 'kneelower', 'kneeupper', 'foot', 'toe', 'ball'
            # Removed facial bones (jaw, eye, mouth etc) as per request
        ]
        
        # Helper to check if name is core bone
        def is_core_bone(name):
            # Strict rejection of buffbones/helpers
            if 'buffbone' in name.lower() or 'helper' in name.lower():
                return False
                
            norm = normalize_bone_name(name)
            # Check exact list
            if norm in core_bones:
                return True
            # Check prefix variations (e.g. L_Knee is core if 'knee' is core)
            for core in core_bones:
                if norm == core:
                    return True
            return False

        for source_bone in source_bones:
            item = props.bone_mappings.add()
            item.source_bone = source_bone
            
            norm_name = normalize_bone_name(source_bone)
            
            # STRICT MODE: Only allow whitelisted bones
            if props.ignore_extras:
                if not is_core_bone(source_bone):
                    item.target_bone = ""
                    item.enabled = False
                    unmatched += 1
                    continue
            
            # Special handling for Root -> Pelvis
            if props.map_root_to_pelvis:
                # If this is the Source Pelvis/Hip, skip it
                if norm_name in ['pelvis', 'hip']:
                    item.target_bone = ""
                    item.enabled = False
                    unmatched += 1
                    continue
                # If this is the Source Root, try to find Target Pelvis/Hip
                if norm_name == 'root':
                    # Look for pelvis/hip in target
                    found_pelvis = False
                    for t_bone in target_bones:
                        if normalize_bone_name(t_bone) in ['pelvis', 'hip']:
                            item.target_bone = t_bone
                            item.enabled = True
                            matched += 1
                            found_pelvis = True
                            break
                    if found_pelvis:
                        continue
            
            # Find match using standard fuzzy/alias logic
            match = find_best_match(source_bone, target_bones)
            
            if match:
                # Extra safety for strict mode: Target must also be a core bone
                if props.ignore_extras:
                    if not is_core_bone(match):
                        item.target_bone = ""
                        item.enabled = False
                        unmatched += 1
                        continue
                    
                    # Prevent partial overlapping names like "Hip_Helper" matching "Hip"
                    # If we are here, both source and target are "core bones" roughly speaking,
                    # but normalize_bone_name("L_Hip_Helper") -> "Hip_Helper" which is NOT in core_bones list.
                    # Wait, my is_core_bone function logic above handles this naturally:
                    # "Hip_Helper" norm is "hip_helper", which isn't in core_bones list.
                    # So "L_Hip_Helper" would be rejected at the start of the loop.
                    
                    pass 

                item.target_bone = match
                item.enabled = True
                matched += 1
            else:
                item.target_bone = ""
                item.enabled = False
                unmatched += 1
        
        props.mapping_generated = True
        self.report({'INFO'}, f"Mapping generated: {matched} matched, {unmatched} unmatched")
        return {'FINISHED'}


class LOL_OT_ApplyRetarget(Operator):
    """Apply the animation from source to target using the bone mapping"""
    bl_idname = "lol_retarget.apply"
    bl_label = "Apply Retarget"
    bl_description = "Transfer animation from source to target armature"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.lol_retarget
        
        if not props.source_armature or not props.target_armature:
            self.report({'ERROR'}, "Select both source and target armatures")
            return {'CANCELLED'}
        
        if not props.mapping_generated:
            self.report({'ERROR'}, "Generate mapping first")
            return {'CANCELLED'}
        
        source_arm = props.source_armature
        target_arm = props.target_armature
        
        if source_arm == target_arm:
            self.report({'ERROR'}, "Source and Target must be different armatures")
            return {'CANCELLED'}
        
        # Check source has animation
        if not source_arm.animation_data or not source_arm.animation_data.action:
            self.report({'ERROR'}, "Source armature has no animation")
            return {'CANCELLED'}
        
        source_action = source_arm.animation_data.action
        
        # Handle Action Creation (Reuse or Create)
        new_action_name = f"{source_action.name}_retargeted"
        new_action = bpy.data.actions.get(new_action_name)
        
        if new_action:
            # Clear existing action data to overwrite
            new_action.fcurves.clear()
        else:
            # Create new
            new_action = bpy.data.actions.new(name=new_action_name)
        
        # Ensure target has animation data
        if not target_arm.animation_data:
            target_arm.animation_data_create()
        target_arm.animation_data.action = new_action
        
        # Force Target to Pose Mode to see results
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        context.view_layer.objects.active = target_arm
        target_arm.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
        
        # Set target bones to quaternion mode
        for pbone in target_arm.pose.bones:
            pbone.rotation_mode = 'QUATERNION'
        
        # Build mapping dict
        mapping = {}
        for item in props.bone_mappings:
            if item.enabled and item.target_bone:
                mapping[item.source_bone] = item.target_bone
        
        # Copy keyframes
        copied_curves = 0
        
        for fcurve in source_action.fcurves:
            # Parse the data path to get bone name
            # Format: pose.bones["BoneName"].location/rotation_quaternion/scale
            match = re.match(r'pose\.bones\["(.+?)"\]\.(.+)', fcurve.data_path)
            if not match:
                continue
            
            source_bone_name = match.group(1)
            property_name = match.group(2)
            
            # Check if this bone is mapped
            if source_bone_name not in mapping:
                continue
            
            target_bone_name = mapping[source_bone_name]
            
            # Check target bone exists
            if target_bone_name not in target_arm.pose.bones:
                continue
            
            # Create new fcurve for target - check if exists first
            new_data_path = f'pose.bones["{target_bone_name}"].{property_name}'
            
            # Check if this curve already exists
            existing_curve = new_action.fcurves.find(new_data_path, index=fcurve.array_index)
            
            if existing_curve:
                # If it exists, clear its keyframes so we overwrite it properly
                existing_curve.keyframe_points.clear()
                new_fcurve = existing_curve
            else:
                # Create new
                new_fcurve = new_action.fcurves.new(data_path=new_data_path, index=fcurve.array_index)
            
            # Copy all keyframes
            for kp in fcurve.keyframe_points:
                new_fcurve.keyframe_points.insert(kp.co.x, kp.co.y)
            
            copied_curves += 1
        
        # Final update
        context.view_layer.update()
        
        self.report({'INFO'}, f"Retargeted to {target_arm.name} (Action: {new_action_name})")
        return {'FINISHED'}


class LOL_OT_ClearMapping(Operator):
    """Clear the current bone mapping"""
    bl_idname = "lol_retarget.clear_mapping"
    bl_label = "Clear Mapping"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.lol_retarget
        props.bone_mappings.clear()
        props.mapping_generated = False
        self.report({'INFO'}, "Mapping cleared")
        return {'FINISHED'}


class LOL_UL_BoneMapping(bpy.types.UIList):
    """UI List for displaying bone mappings"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # Draw each row
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            # Checkbox
            row.prop(item, "enabled", text="")
            
            # Source Bone (Label)
            row.label(text=item.source_bone)
            
            # Arrow
            row.label(text="", icon='FORWARD')
            
            # Target Bone (Editable)
            if item.target_bone:
                row.prop(item, "target_bone", text="", icon='BONE_DATA')
            else:
                row.prop(item, "target_bone", text="", icon='ERROR', placeholder="No Match")
                
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.source_bone)


class LOL_PT_RetargetPanel(Panel):
    """Animation Retarget Panel"""
    bl_label = "LoL Retarget"
    bl_idname = "VIEW3D_PT_lol_retarget"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'LoL Retarget'
    
    def draw_header(self, context):
        layout = self.layout
        layout.label(text="", icon_value=icons.get_icon("plugin_icon"))
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.lol_retarget
        
        # Armature Selection
        box = layout.box()
        box.label(text="Armatures", icon='ARMATURE_DATA')
        box.prop(props, "source_armature", text="Source (has anim)")
        box.prop(props, "target_armature", text="Target (receives anim)")
        
        # Settings
        box = layout.box()
        box.label(text="Options", icon='PREFERENCES')
        box.prop(props, "map_root_to_pelvis", text="Map Source Root → Target Hip")
        box.prop(props, "ignore_extras", text="Ignore Extras (Buffbones/Hair)")
        
        # Actions
        row = layout.row(align=True)
        row.operator("lol_retarget.generate_mapping", text="Generate Mapping", icon='FILE_REFRESH')
        row.operator("lol_retarget.clear_mapping", text="", icon='X')
        
        # Mapping Preview
        if props.mapping_generated and len(props.bone_mappings) > 0:
            box = layout.box()
            box.label(text="Bone Mapping", icon='BONE_DATA')
            
            # Count stats
            matched = sum(1 for m in props.bone_mappings if m.target_bone and m.enabled)
            total = len(props.bone_mappings)
            box.label(text=f"Matched: {matched}/{total}")
            
            # Scrolable UI List
            row = box.row()
            row.template_list("LOL_UL_BoneMapping", "", props, "bone_mappings", props, "active_mapping_index", rows=10)
        
        # Apply Button
        layout.separator()
        row = layout.row()
        row.scale_y = 1.5
        row.operator("lol_retarget.apply", text="Apply Retarget", icon='PLAY')


# Registration
classes = [
    BoneMappingItem,
    LOLRetargetProperties,
    LOL_OT_GenerateMapping,
    LOL_OT_ApplyRetarget,
    LOL_OT_ClearMapping,
    LOL_UL_BoneMapping,
    LOL_PT_RetargetPanel,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lol_retarget = PointerProperty(type=LOLRetargetProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lol_retarget
