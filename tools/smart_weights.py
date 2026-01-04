import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import PointerProperty, BoolProperty, CollectionProperty, StringProperty, IntProperty
from ..ui import icons

# Core bone names that should receive weights
# This list matches the standard logic used in retargeting
CORE_BONES = {
    'pelvis', 'hip', 'spine', 'spine1', 'spine2', 'spine3', 'chest', 'neck', 'head',
    'clavicle', 'shoulder', 'elbow', 'hand',
    'thumb1', 'thumb2', 'thumb3', 
    'index1', 'index2', 'index3', 
    'middle1', 'middle2', 'middle3', 
    'ring1', 'ring2', 'ring3', 
    'pinky1', 'pinky2', 'pinky3',
    'knee', 'kneelower', 'foot'
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

class WeightBoneItem(PropertyGroup):
    """List item for bone selection"""
    name: StringProperty()
    is_core: BoolProperty(default=False)
    enabled: BoolProperty(default=True)

class ShrinkBoneItem(PropertyGroup):
    """List item for bones to shrink"""
    name: StringProperty()

class LOL_SmartWeightProperties(PropertyGroup):
    """Properties for smart weighting"""
    bone_list: CollectionProperty(type=WeightBoneItem)
    active_bone_index: IntProperty()
    
    # Shrink List
    shrink_bone_list: CollectionProperty(type=ShrinkBoneItem)
    active_shrink_index: IntProperty()
    shrink_search_str: StringProperty(name="Bone", description="Bone to add to shrink list")
    
    restore_flags_after: BoolProperty(
        name="Restore Flags After",
        description="Restore original Deform flags after weighting. If unchecked, flags remain modified.",
        default=True
    )
    
    clear_unused_groups: BoolProperty(
        name="Clear Unchecked Groups",
        description="Remove vertex groups for unchecked bones before applying only auto weights to core bones. Essential for removing bad/old weights.",
        default=True
    )
    
    recalculate_normals: BoolProperty(
        name="Recalculate Normals (Inside/Outside)",
        description="Temporarily flip normals Outside for clean weighting, then flip back.",
        default=True
    )
    
    shrink_risky_bones: BoolProperty(
        name="Shrink Hands/Weapons",
        description="Shrink bones that often cause issues (Hands, Weapons) to small joints before weighting, but keep Spines/Hips large for cape coverage.",
        default=True
    )

class LOL_OT_PopulateWeightList(Operator):
    """Populate the list of bones to be used for weighting"""
    bl_idname = "lol.populate_weight_list"
    bl_label = "Scan Bones"
    bl_description = "Scan selected armature and identify core bones"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        props = context.scene.lol_smart_weight
        armature = context.active_object
        
        # Must be in Object Mode to read/edit EditBones? No, standard Bones are on data
        # But safest to be in Object Mode
        if context.mode != 'OBJECT':
             bpy.ops.object.mode_set(mode='OBJECT')
        
        props.bone_list.clear()
        
        core_count = 0
        total_count = 0
        
        for bone in armature.data.bones:
            item = props.bone_list.add()
            item.name = bone.name
            
            # Logic to determine if it's a core bone
            norm_name = normalize_bone_name(bone.name)
            is_core = False
            
            if 'buffbone' not in bone.name.lower() and 'helper' not in bone.name.lower():
                if norm_name in CORE_BONES:
                    is_core = True
                # Check for side variations of core bones (e.g. L_Knee)
                elif any(norm_name == core for core in CORE_BONES):
                    is_core = True
            
            item.is_core = is_core
            item.enabled = is_core  # Default enabled if it's a core bone
            
            if is_core:
                core_count += 1
            total_count += 1
            
        self.report({'INFO'}, f"Found {core_count} core bones out of {total_count}")
        
        # Auto-populate shrink list if enabled
        if props.shrink_risky_bones:
            props.shrink_bone_list.clear()
            for bone in armature.data.bones:
                name_lower = bone.name.lower()
                # Only Hand and Buffbone
                if 'hand' in name_lower or 'buffbone' in name_lower:
                    item = props.shrink_bone_list.add()
                    item.name = bone.name
        
        return {'FINISHED'}

class LOL_OT_ApplySmartWeights(Operator):
    """Apply Automatic Weights using only the selected bones"""
    bl_idname = "lol.apply_smart_weights"
    bl_label = "Apply Smart Weights"
    bl_description = "Temporarily disable deform for unselected bones, apply Auto Weights, then restore"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        # Need an Armature active and Mesh selected
        if not context.active_object or context.active_object.type != 'ARMATURE':
            return False
        # Check if a mesh is also selected
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        from mathutils import Vector
        props = context.scene.lol_smart_weight
        armature = context.active_object
        
        # 1. Store original states
        original_states = {}
        for bone in armature.data.bones:
            original_states[bone.name] = bone.use_deform
            
        # 2. Apply temporary states based on our UI list
        # If the list is empty, user might not have scanned. Scan now implicitly?
        if len(props.bone_list) == 0:
            bpy.ops.lol.populate_weight_list()
            
        # Create a lookup for enabled status from our list
        enabled_bones = {item.name: item.enabled for item in props.bone_list}
        
        # Apply flags
        count_active = 0
        for bone in armature.data.bones:
            if bone.name in enabled_bones:
                should_deform = enabled_bones[bone.name]
                bone.use_deform = should_deform
                if should_deform:
                    count_active += 1
            else:
                # If bone not in list (newly added?), default to off for safety
                bone.use_deform = False
                
        if props.clear_unused_groups:
             # Identify bones that are UNCHECKED
            unchecked_bone_names = [b.name for b in armature.data.bones if b.name not in enabled_bones or not enabled_bones[b.name]]
            
            # Remove vertex groups for these bones from the SELECTED MESH(es)
            # Operator poll ensures we have mesh selected
            meshes = [o for o in context.selected_objects if o.type == 'MESH']
            for mesh_obj in meshes:
                for target_name in unchecked_bone_names:
                    vg = mesh_obj.vertex_groups.get(target_name)
                    if vg:
                        mesh_obj.vertex_groups.remove(vg)
            self.report({'INFO'}, f"Cleared groups for {len(unchecked_bone_names)} unchecked bones")
        
        # 1b. Recalculate Normals (Critical for Heat Map)
        if props.recalculate_normals:
            # We need to be in Edit Mode ON THE MESH to recalc normals
            # Find the mesh object first
            target_mesh = None
            for obj in context.selected_objects:
                if obj.type == 'MESH':
                    target_mesh = obj
                    break
            
            if target_mesh:
                context.view_layer.objects.active = target_mesh
                if context.mode != 'EDIT_MESH':
                    bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.normals_make_consistent(inside=False)
                bpy.ops.object.mode_set(mode='OBJECT')
                context.view_layer.objects.active = armature

        # 2a. Selective Bone Shrinking (Fix "Weapon Pyramid" issue)
        # Only shrink bones that are likely to cause cross-talk (Hands, Weapons)
        # KEEP Spines/Hips large for Cape/Coat coverage.
        if props.shrink_risky_bones:
            bpy.ops.object.mode_set(mode='EDIT')
            eb = armature.data.edit_bones
            
            # Store original geometry data
            original_geometry = {}
            
            # Auto-populate shrink list if empty
            if len(props.shrink_bone_list) == 0:
                for b in armature.data.bones:
                    name_lower = b.name.lower()
                    # Only Hand and Buffbone
                    if 'hand' in name_lower or 'buffbone' in name_lower:
                        item = props.shrink_bone_list.add()
                        item.name = b.name
            
            # Build set of bone names to shrink
            shrink_names = {item.name for item in props.shrink_bone_list}

            for bone in eb:
                should_shrink = bone.name in shrink_names

                if should_shrink:
                    original_geometry[bone.name] = {
                        'tail': bone.tail.copy(),
                        'use_connect': bone.use_connect,
                        'length': bone.length
                    }
                    
                    bone.use_connect = False
                    
                    # Shrink to stub
                    direction = (bone.tail - bone.head).normalized()
                    if direction.length == 0: direction = Vector((0,0,1))
                    bone.tail = bone.head + (direction * 0.05) 

            bpy.ops.object.mode_set(mode='OBJECT')

        # 3. Apply Automatic Weights
        try:
            context.view_layer.objects.active = armature
            
            # (Logging removed as requested)
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')
            
            self.report({'INFO'}, f"Applied Smart Weights ({count_active} bones)")
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed: {str(e)}")
            
        # 4. Restore Bone Geometry
        if props.shrink_risky_bones:
            bpy.ops.object.mode_set(mode='EDIT')
            eb = armature.data.edit_bones
            for name, data in original_geometry.items():
                if name in eb:
                    bone = eb[name]
                    bone.tail = data['tail']
                    bone.use_connect = data['use_connect']
            bpy.ops.object.mode_set(mode='OBJECT')

        # 5. Flip Normals Back (If requested?) - Usually we want them OUTSIDE for game export anyway?
        # User said: "after we are done with weighting we need to flip the normals again"
        # Assuming flip back to INSIDE (League standard?)
        # Wait, League standard is usually OUTSIDE, but culling makes them invisible if inside.
        # Unless user model was specifically inside-out for outlining?
        # I will assume "Flip normals again" means "Reverse whatever we did".
        
        if props.recalculate_normals:
             # Find mesh again
            if target_mesh:
                context.view_layer.objects.active = target_mesh
                if context.mode != 'EDIT_MESH':
                     bpy.ops.object.mode_set(mode='EDIT')
                
                bpy.ops.mesh.select_all(action='SELECT')
                # Flip selected (inverts the Outside calc we did earlier)
                bpy.ops.mesh.flip_normals()
                
                bpy.ops.object.mode_set(mode='OBJECT')
                context.view_layer.objects.active = armature
        
        # 6. Restore deform flags
        if props.restore_flags_after:
            for name, state in original_states.items():
                if name in armature.data.bones:
                    armature.data.bones[name].use_deform = state

        return {'FINISHED'}

class LOL_OT_DebugWeights(Operator):
    """Print weights of selected vertices to System Console"""
    bl_idname = "lol.debug_weights"
    bl_label = "Debug Vertex Weights"
    bl_description = "Print influence list of selected vertices to the System Console"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        
        # Get selected vertices
        selected_verts = [v for v in mesh.vertices if v.select]
        
        if not selected_verts:
            self.report({'WARNING'}, "No vertices selected. Go to Edit Mode and select vertices.")
            return {'CANCELLED'}
            
        print("-" * 50)
        print(f"Debug Weights for '{obj.name}' ({len(selected_verts)} selected vertices):")
        
        # Cache group names
        group_names = {g.index: g.name for g in obj.vertex_groups}
        
        for v in selected_verts:
            print(f"Vertex {v.index}:")
            if not v.groups:
                print("  <No Weights>")
                continue
                
            # Print all non-zero weights
            seen_groups = set()
            sorted_groups = sorted(v.groups, key=lambda x: x.weight, reverse=True)
            for g in sorted_groups:
                g_name = group_names.get(g.group, f"Unknown({g.group})")
                print(f"  - {g_name}: {g.weight:.4f}")
                seen_groups.add(g_name)
            
            # OPTIONAL: Print zero weights found on vertex? 
            # Vertices only store groups they are assigned to. 
            # If a bone is missing here, it means the vertex is NOT in that group at all.

        
        print("-" * 50)
        self.report({'INFO'}, "Weights printed to System Console (Window > Toggle System Console)")
        return {'FINISHED'}

class LOL_UL_WeightBoneList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(item, "enabled", text="")
            icon = 'BONE_DATA' if item.is_core else 'BONE_DATA' # Could differentiate icon
            
            # Color code or format name
            if item.is_core:
                 row.label(text=item.name, icon=icon)
            else:
                 row.label(text=item.name, icon=icon) 
                 # Maybe dim text for non-core? Blender UI doesn't allow easy text coloring here
                 
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name)

class LOL_OT_TransferWeights(Operator):
    """Transfer weights from another mesh (Nearest Face Interpolated)"""
    bl_idname = "lol.transfer_weights"
    bl_label = "Transfer Weights"
    bl_description = "Transfer weights from source mesh to selected mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    source_object: StringProperty(name="Source Mesh")
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        target_obj = context.active_object
        source_obj = context.scene.objects.get(self.source_object)
        
        if not source_obj:
            self.report({'ERROR'}, "Source object not found")
            return {'CANCELLED'}
        
        if source_obj.type != 'MESH':
            self.report({'ERROR'}, "Source must be a mesh")
            return {'CANCELLED'}
            
        # Add Data Transfer Modifier
        mod = target_obj.modifiers.new(name="WeightTransfer", type='DATA_TRANSFER')
        mod.object = source_obj
        mod.use_loop_data = False 
        mod.use_vert_data_vertex_group = True
        mod.data_types_verts_vgroup = 'ALL' # 'ALL' groups
        mod.vert_mapping = 'NEAREST' # Nearest vertex vs Nearest Face Interpolated
        # Usually NEAREST_POLY (Nearest Face Interpolated) is best for mismatched topology
        # But 'NEAREST' is safer if meshes are very different. Let's try Poly Interp.
        mod.vert_mapping = 'POLYINTERP_NEAREST' 
        
        try:
            # Generate the data
            bpy.ops.object.datalayout_transfer(modifier=mod.name)
            
            # Apply the modifier
            bpy.ops.object.modifier_apply(modifier=mod.name)
            
            self.report({'INFO'}, f"Transferred weights from {source_obj.name}")
        except Exception as e:
            target_obj.modifiers.remove(mod)
            self.report({'ERROR'}, f"Transfer failed: {str(e)}")
            return {'CANCELLED'}
            
        return {'FINISHED'}

class LOL_OT_BindToNearestBone(Operator):
    """Rigidly bind selected vertices to the physically nearest bone in the armature"""
    bl_idname = "lol.bind_nearest_bone"
    bl_label = "Bind Selected to Nearest"
    bl_description = "Find nearest bone for each selected vertex and assign 100% weight (Rigid Binding). Good for floating parts."
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        import bmesh
        from mathutils.geometry import intersect_point_line
        
        obj = context.active_object
        mesh = obj.data
        armature = None
        
        # Find armature modifier
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object:
                armature = mod.object
                break
        
        if not armature:
            self.report({'ERROR'}, "Object has no Armature modifier")
            return {'CANCELLED'}
            
        bm = bmesh.from_edit_mesh(mesh)
        selected_verts = [v for v in bm.verts if v.select]
        
        if not selected_verts:
            self.report({'WARNING'}, "No vertices selected. Select floating geometry in Edit Mode.")
            return {'CANCELLED'}
            
        # Cache Bone World Coordinates
        mw_mesh = obj.matrix_world
        mw_arm = armature.matrix_world
        
        bones = []
        
        # Only consider ENABLED bones from our tool to allow filtering!
        props = context.scene.lol_smart_weight
        if len(props.bone_list) > 0:
             enabled_names = {item.name for item in props.bone_list if item.enabled}
             source_bones = [b for b in armature.data.bones if b.name in enabled_names]
        else:
             source_bones = armature.data.bones
             
        if not source_bones:
             self.report({'ERROR'}, "No eligible bones found (check Smart Weight list)")
             return {'CANCELLED'}

        # Pre-calc bone world coords
        for bone in source_bones:
            head_world = mw_arm @ bone.head_local
            tail_world = mw_arm @ bone.tail_local
            bones.append((bone.name, head_world, tail_world))
            
        # Get Vertex Groups layer
        dvert_lay = bm.verts.layers.deform.verify()
        
        def get_group_index(name):
            vg = obj.vertex_groups.get(name)
            if not vg:
                vg = obj.vertex_groups.new(name=name)
            return vg.index

        count = 0
        
        for v in selected_verts:
            v_world = mw_mesh @ v.co
            
            best_bone_name = None
            min_dist = 999999.0
            
            for name, head, tail in bones:
                # Distance to line segment
                pt_on_segment, percent = intersect_point_line(v_world, head, tail)
                
                # Constrain to segment
                if percent < 0.0:
                    dist = (v_world - head).length
                elif percent > 1.0:
                    dist = (v_world - tail).length
                else:
                    dist = (v_world - pt_on_segment).length
                    
                if dist < min_dist:
                    min_dist = dist
                    best_bone_name = name
            
            if best_bone_name:
                # Assign Weight
                dvert = v[dvert_lay]
                dvert.clear() # Clear existing
                gi = get_group_index(best_bone_name)
                dvert[gi] = 1.0
                count += 1
                
        bmesh.update_edit_mesh(mesh)
        self.report({'INFO'}, f"Bound {count} vertices to nearest bones")
        return {'FINISHED'}

class LOL_OT_AddShrinkBone(Operator):
    """Add bone to shrink list"""
    bl_idname = "lol.add_shrink_bone"
    bl_label = "Add"
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        bone_name = props.shrink_search_str
        if bone_name:
            # Check if exists
            exists = False
            for item in props.shrink_bone_list:
                if item.name == bone_name:
                    exists = True
                    break
            if not exists:
                item = props.shrink_bone_list.add()
                item.name = bone_name
                props.shrink_search_str = ""
        return {'FINISHED'}

class LOL_OT_RemoveShrinkBone(Operator):
    """Remove selected bone from shrink list"""
    bl_idname = "lol.remove_shrink_bone"
    bl_label = "Remove"
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        if props.active_shrink_index >= 0 and len(props.shrink_bone_list) > 0:
            props.shrink_bone_list.remove(props.active_shrink_index)
            props.active_shrink_index = max(0, props.active_shrink_index - 1)
        return {'FINISHED'}

class LOL_OT_PopulateShrinkList(Operator):
    """Auto-detect and populate risky bones"""
    bl_idname = "lol.populate_shrink_list"
    bl_label = "Auto-Detect"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        props.shrink_bone_list.clear()
        
        armature = context.active_object
        
        count = 0
        for bone in armature.data.bones:
            name_lower = bone.name.lower()
            # Only Hand and Buffbone
            if 'hand' in name_lower or 'buffbone' in name_lower:
                item = props.shrink_bone_list.add()
                item.name = bone.name
                count += 1
        self.report({'INFO'}, f"Added {count} risky bones")
        return {'FINISHED'}

class LOL_PT_SmartWeightPanel(Panel):
    bl_label = "Smart Weights"
    bl_idname = "VIEW3D_PT_lol_smart_weights"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Smart Weight' # Dedicated Tab as requested
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.lol_smart_weight
        
        # --- Section 1: Auto Weights (with Bone Linking) ---
        layout.label(text="Method A: Auto Weights", icon='AUTOMERGE_OFF')
        box = layout.box()
        
        # Scan Button
        row = box.row()
        row.operator("lol.populate_weight_list", icon='FILE_REFRESH', text="Detect Bones")
        
        # List
        if len(props.bone_list) > 0:
            box.label(text="Allowed Bones:", icon='GROUP_BONE')
            row = box.row()
            row.template_list("LOL_UL_WeightBoneList", "", props, "bone_list", props, "active_bone_index", rows=6)
            
            # Selection Helpers
            row = box.row(align=True)
            op = row.operator("lol.weight_list_action", text="All")
            op.action = 'SELECT_ALL'
            op = row.operator("lol.weight_list_action", text="None")
            op.action = 'DESELECT_ALL'
            op = row.operator("lol.weight_list_action", text="Core Only")
            op.action = 'SELECT_CORE'
            
        box.separator()
        box.prop(props, "clear_unused_groups")
        box.prop(props, "recalculate_normals")
        box.prop(props, "shrink_risky_bones")
        
        if props.shrink_risky_bones:
            col = box.column()
            col.label(text="Bones to Shrink:")
            
            row = col.row()
            row.template_list("UI_UL_list", "shrink_list", props, "shrink_bone_list", props, "active_shrink_index", rows=4)
            
            col2 = col.column(align=True)
            row = col2.row(align=True)
            if context.active_object and context.active_object.type == 'ARMATURE':
                row.prop_search(props, "shrink_search_str", context.active_object.data, "bones", text="", icon='BONE_DATA')
                row.operator("lol.add_shrink_bone", text="", icon='ADD')
            
            row = col2.row(align=True)
            row.operator("lol.remove_shrink_bone", text="Remove", icon='X')
            row.operator("lol.populate_shrink_list", text="Auto-Detect", icon='FILE_REFRESH')
        
        row = box.row()
        row.scale_y = 1.5
        row.operator("lol.apply_smart_weights", icon='MOD_ARMATURE')
        
        layout.separator()
        
        # --- Section 2: Weight Transfer ---
        layout.label(text="Method B: Weight Transfer", icon='LINK_BLEND')
        box = layout.box()
        box.label(text="Transfer from another mesh:")
        
        # Object Picker (reuse prop from where? We need a prop. Let's make a temporary one or use prop search)
        # Using a PropSearch on the Scene is easiest
        box.prop_search(props, "transfer_source", context.scene, "objects", text="Source", icon='MESH_DATA')
        
        row = box.row()
        row.scale_y = 1.5
        op = row.operator("lol.transfer_weights", icon='TRIA_LEFT')
        op.source_object = props.transfer_source
        
        row = box.row()
        row.scale_y = 1.5
        op = row.operator("lol.transfer_weights", icon='TRIA_LEFT')
        op.source_object = props.transfer_source
        
        layout.separator()

class LOL_OT_WeightListAction(Operator):
    """Helper to select/deselect items in the list"""
    bl_idname = "lol.weight_list_action"
    bl_label = "List Action"
    
    action: bpy.props.EnumProperty(
        items=[
            ('SELECT_ALL', "Select All", ""),
            ('DESELECT_ALL', "Deselect All", ""),
            ('SELECT_CORE', "Select Core", ""),
        ]
    )
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        for item in props.bone_list:
            if self.action == 'SELECT_ALL':
                item.enabled = True
            elif self.action == 'DESELECT_ALL':
                item.enabled = False
            elif self.action == 'SELECT_CORE':
                item.enabled = item.is_core
        return {'FINISHED'}

classes = [
    WeightBoneItem,
    ShrinkBoneItem,
    LOL_SmartWeightProperties,
    LOL_OT_PopulateWeightList,
    LOL_OT_ApplySmartWeights,
    LOL_OT_TransferWeights,
    LOL_OT_AddShrinkBone,
    LOL_OT_RemoveShrinkBone,
    LOL_OT_PopulateShrinkList,
    LOL_OT_BindToNearestBone,
    LOL_OT_DebugWeights,
    LOL_OT_WeightListAction,
    LOL_UL_WeightBoneList,
    LOL_PT_SmartWeightPanel
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Extend properties with the transfer source pointer
    LOL_SmartWeightProperties.transfer_source = StringProperty(
        name="Source Mesh", 
        description="Mesh to transfer weights from"
    )
    
    bpy.types.Scene.lol_smart_weight = PointerProperty(type=LOL_SmartWeightProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lol_smart_weight
