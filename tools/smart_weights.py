import bpy
import bmesh
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import PointerProperty, BoolProperty, CollectionProperty, StringProperty, IntProperty, EnumProperty
from mathutils.geometry import intersect_point_line
from ..ui import icons

# Try to import geodesic voxel module
try:
    from . import auto_skinning
    HAS_GEODESIC_VOXEL = True
except ImportError:
    HAS_GEODESIC_VOXEL = False
    print("Geodesic Voxel module not available")

# Core bone names that should receive weights
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
    prefixes = ['c_', 'l_', 'r_', 'buffbone_', 'glb_', 'cstm_']
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def get_bone_segment_distance(point, head, tail):
    """Calculate shortest distance from point to bone segment."""
    pt_on_segment, t = intersect_point_line(point, head, tail)

    if t < 0.0:
        closest = head
        t = 0.0
    elif t > 1.0:
        closest = tail
        t = 1.0
    else:
        closest = pt_on_segment

    distance = (point - closest).length
    return distance, closest, t


# =============================================================================
# Property Groups
# =============================================================================

class WeightBoneItem(PropertyGroup):
    """List item for bone selection"""
    name: StringProperty()
    is_core: BoolProperty(default=False)
    enabled: BoolProperty(default=True)


class LOL_SmartWeightProperties(PropertyGroup):
    """Properties for smart weighting"""
    bone_list: CollectionProperty(type=WeightBoneItem)
    active_bone_index: IntProperty()


# =============================================================================
# Operators
# =============================================================================

class LOL_OT_PopulateWeightList(Operator):
    """Populate the list of bones to be used for weighting"""
    bl_idname = "lol.populate_weight_list"
    bl_label = "Detect Bones"
    bl_description = "Scan selected armature and identify core deform bones"

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        props = context.scene.lol_smart_weight
        armature = context.active_object

        if context.mode != 'OBJECT':
             bpy.ops.object.mode_set(mode='OBJECT')

        props.bone_list.clear()

        core_count = 0
        total_count = 0

        for bone in armature.data.bones:
            item = props.bone_list.add()
            item.name = bone.name

            norm_name = normalize_bone_name(bone.name)
            is_core = False

            if 'buffbone' not in bone.name.lower() and 'helper' not in bone.name.lower():
                if norm_name in CORE_BONES:
                    is_core = True

            item.is_core = is_core
            item.enabled = is_core

            if is_core:
                core_count += 1
            total_count += 1

        self.report({'INFO'}, f"Found {core_count} core bones out of {total_count}")
        return {'FINISHED'}


class LOL_OT_WeightListAction(Operator):
    """Select/deselect items in the bone list"""
    bl_idname = "lol.weight_list_action"
    bl_label = "List Action"

    action: EnumProperty(
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

        selected_verts = [v for v in mesh.vertices if v.select]

        if not selected_verts:
            self.report({'WARNING'}, "No vertices selected")
            return {'CANCELLED'}

        print("-" * 50)
        print(f"Debug Weights for '{obj.name}' ({len(selected_verts)} verts):")

        group_names = {g.index: g.name for g in obj.vertex_groups}

        for v in selected_verts:
            print(f"Vertex {v.index}:")
            if not v.groups:
                print("  <No Weights>")
                continue

            sorted_groups = sorted(v.groups, key=lambda x: x.weight, reverse=True)
            for g in sorted_groups:
                g_name = group_names.get(g.group, f"Unknown({g.group})")
                print(f"  - {g_name}: {g.weight:.4f}")

        print("-" * 50)
        self.report({'INFO'}, "Weights printed to System Console")
        return {'FINISHED'}


class LOL_OT_DeleteShapeKeys(Operator):
    """Delete all shape keys from the selected mesh"""
    bl_idname = "lol.delete_shape_keys"
    bl_label = "Delete All Shape Keys"
    bl_description = "Remove all shape keys from selected meshes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' and obj.data.shape_keys for obj in context.selected_objects)

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH' and obj.data.shape_keys:
                context.view_layer.objects.active = obj
                obj.shape_key_clear()
                count += 1

        self.report({'INFO'}, f"Deleted shape keys from {count} mesh(es)")
        return {'FINISHED'}


class LOL_OT_ClearMismatchedGroups(Operator):
    """Clear vertex groups that don't match armature bone names"""
    bl_idname = "lol.clear_mismatched_groups"
    bl_label = "Clear Mismatched Groups"
    bl_description = "Remove vertex groups that don't match any bone in the armature"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != 'ARMATURE':
            return False
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        armature = context.active_object
        bone_names = set(bone.name for bone in armature.data.bones)

        total_removed = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            to_remove = [vg.name for vg in obj.vertex_groups if vg.name not in bone_names]
            for name in to_remove:
                vg = obj.vertex_groups.get(name)
                if vg:
                    obj.vertex_groups.remove(vg)
                    total_removed += 1

        self.report({'INFO'}, f"Removed {total_removed} mismatched vertex groups")
        return {'FINISHED'}


class LOL_OT_ClearAllVertexGroups(Operator):
    """Clear all vertex groups from selected meshes"""
    bl_idname = "lol.clear_all_vertex_groups"
    bl_label = "Clear All Groups"
    bl_description = "Remove ALL vertex groups from selected meshes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' and len(obj.vertex_groups) > 0 for obj in context.selected_objects)

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                num_groups = len(obj.vertex_groups)
                obj.vertex_groups.clear()
                count += num_groups

        self.report({'INFO'}, f"Removed {count} vertex groups")
        return {'FINISHED'}


class LOL_OT_TransferWeights(Operator):
    """Transfer weights from another mesh"""
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

        bpy.ops.object.select_all(action='DESELECT')
        target_obj.select_set(True)
        source_obj.select_set(True)
        context.view_layer.objects.active = target_obj

        try:
            bpy.ops.object.data_transfer(
                data_type='VGROUP_WEIGHTS',
                vert_mapping='POLYINTERP_NEAREST',
                layers_select_src='ALL',
                layers_select_dst='NAME'
            )
            self.report({'INFO'}, f"Transferred weights from {source_obj.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Transfer failed: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}


class LOL_OT_BindToNearestBone(Operator):
    """Rigidly bind selected vertices to nearest bone"""
    bl_idname = "lol.bind_nearest_bone"
    bl_label = "Bind to Nearest Bone"
    bl_description = "Find nearest bone for each selected vertex and assign 100% weight"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        armature = None

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
            self.report({'WARNING'}, "No vertices selected")
            return {'CANCELLED'}

        mw_mesh = obj.matrix_world
        mw_arm = armature.matrix_world

        props = context.scene.lol_smart_weight
        if len(props.bone_list) > 0:
             enabled_names = {item.name for item in props.bone_list if item.enabled}
             source_bones = [b for b in armature.data.bones if b.name in enabled_names]
        else:
             source_bones = armature.data.bones

        if not source_bones:
             self.report({'ERROR'}, "No eligible bones found")
             return {'CANCELLED'}

        bones = []
        for bone in source_bones:
            head_world = mw_arm @ bone.head_local
            tail_world = mw_arm @ bone.tail_local
            bones.append((bone.name, head_world, tail_world))

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
                dist, _, _ = get_bone_segment_distance(v_world, head, tail)

                if dist < min_dist:
                    min_dist = dist
                    best_bone_name = name

            if best_bone_name:
                dvert = v[dvert_lay]
                dvert.clear()
                gi = get_group_index(best_bone_name)
                dvert[gi] = 1.0
                count += 1

        bmesh.update_edit_mesh(mesh)
        self.report({'INFO'}, f"Bound {count} vertices to nearest bones")
        return {'FINISHED'}


class LOL_UL_WeightBoneList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(item, "enabled", text="")
            row.label(text=item.name, icon='BONE_DATA')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name)


# =============================================================================
# UI Panel
# =============================================================================

class LOL_PT_SmartWeightPanel(Panel):
    bl_label = "Skin Tools"
    bl_idname = "VIEW3D_PT_lol_skin_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Misc LoL Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        layout = self.layout
        from ..ui import icons
        layout.label(text="", icon_value=icons.get_icon("icon_54"))

    def draw(self, context):
        layout = self.layout
        props = context.scene.lol_smart_weight

        # --- Deform Bones ---
        box = layout.box()
        box.label(text="Bone Manager", icon='GROUP_BONE')

        row = box.row()
        row.operator("lol.populate_weight_list", icon='FILE_REFRESH', text="Detect Bones")

        if len(props.bone_list) > 0:
            row = box.row()
            row.template_list("LOL_UL_WeightBoneList", "", props, "bone_list", props, "active_bone_index", rows=6)

            row = box.row(align=True)
            op = row.operator("lol.weight_list_action", text="All")
            op.action = 'SELECT_ALL'
            op = row.operator("lol.weight_list_action", text="None")
            op.action = 'DESELECT_ALL'
            op = row.operator("lol.weight_list_action", text="Core")
            op.action = 'SELECT_CORE'

        # --- Auto Skinning ---
        if HAS_GEODESIC_VOXEL:
            layout.separator()
            auto_skinning.draw_geodesic_panel(layout, context)

        # --- Utilities ---
        layout.separator()
        box = layout.box()
        box.label(text="Utilities", icon='TOOL_SETTINGS')
        col = box.column(align=True)
        col.operator("lol.debug_weights", icon='INFO')
        col.operator("lol.delete_shape_keys", icon='SHAPEKEY_DATA')
        col.operator("lol.clear_mismatched_groups", icon='X')
        col.operator("lol.clear_all_vertex_groups", icon='TRASH')


# =============================================================================
# Registration
# =============================================================================

classes = [
    WeightBoneItem,
    LOL_SmartWeightProperties,
    LOL_OT_PopulateWeightList,
    LOL_OT_TransferWeights,
    LOL_OT_BindToNearestBone,
    LOL_OT_DebugWeights,
    LOL_OT_WeightListAction,
    LOL_OT_DeleteShapeKeys,
    LOL_OT_ClearMismatchedGroups,
    LOL_OT_ClearAllVertexGroups,
    LOL_UL_WeightBoneList,
]

panel_classes = [
    LOL_PT_SmartWeightPanel
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.lol_smart_weight = PointerProperty(type=LOL_SmartWeightProperties)

    if HAS_GEODESIC_VOXEL:
        auto_skinning.register()

def unregister():
    if HAS_GEODESIC_VOXEL:
        try:
            auto_skinning.unregister()
        except:
            pass

    for cls in reversed(panel_classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lol_smart_weight

def register_panel():
    """Register just the panel (for preference toggle)"""
    for cls in panel_classes:
        try:
            bpy.utils.register_class(cls)
        except:
            pass

def unregister_panel():
    """Unregister just the panel (for preference toggle)"""
    for cls in reversed(panel_classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
