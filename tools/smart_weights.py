"""
Skin Tools - Mesh Binding and Weighting
========================================

Integrates Surface Heat Diffuse Skinning for automatic weight generation.
Also provides utility operators for weight management.

Surface Heat Diffuse Skinning by mesh online (MIT License)
https://www.mesh-online.net/vhd.html
"""

import bpy
import sys
import os
import time
import platform
from subprocess import PIPE, Popen
from threading import Thread
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    PointerProperty, BoolProperty, CollectionProperty,
    StringProperty, IntProperty, FloatProperty, EnumProperty
)
from queue import Queue, Empty
from mathutils import Vector
from mathutils.geometry import intersect_point_line
import bmesh
from ..ui import icons


# =============================================================================
# Surface Heat Diffuse Skinning Operator
# =============================================================================

def get_shd_bin_path():
    """Get the path to the Surface Heat Diffuse executable."""
    addon_dir = os.path.dirname(os.path.dirname(__file__))
    shd_dir = os.path.join(addon_dir, "Surface-Heat-Diffuse-Skinning-master", "addon", "surface_heat_diffuse_skinning")

    if platform.system() == 'Windows':
        if platform.machine().endswith('64'):
            return os.path.join(shd_dir, "bin", "Windows", "x64", "shd.exe")
        else:
            return os.path.join(shd_dir, "bin", "Windows", "x86", "shd.exe")
    elif platform.system() == 'Darwin':
        return os.path.join(shd_dir, "bin", "Darwin", "shd")
    else:
        return os.path.join(shd_dir, "bin", "Linux", "shd")


def get_shd_data_path():
    """Get the path to the data directory for temp files."""
    addon_dir = os.path.dirname(os.path.dirname(__file__))
    return os.path.join(addon_dir, "Surface-Heat-Diffuse-Skinning-master", "addon", "surface_heat_diffuse_skinning", "data")


class LOL_OT_SurfaceHeatDiffuse(Operator):
    """Surface Heat Diffuse Skinning - Advanced automatic weight generation"""
    bl_idname = "lol.surface_heat_diffuse"
    bl_label = "Surface Heat Diffuse Skinning"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _pid = None
    _queue = None
    _objs = []
    _permulation = []
    _selected_indices = []
    _selected_group_index_weights = []
    _start_time = None

    @classmethod
    def poll(cls, context):
        # Check if executable exists
        shd_path = get_shd_bin_path()
        if not os.path.exists(shd_path):
            return False

        # Need at least one armature and one mesh selected
        arm_count = sum(1 for ob in context.selected_objects if ob.type == 'ARMATURE')
        mesh_count = sum(1 for ob in context.selected_objects if ob.type == 'MESH')
        return context.mode == 'OBJECT' and arm_count == 1 and mesh_count >= 1

    def write_bone_data(self, obj, filepath):
        """Write armature bone data to file."""
        f = open(filepath, 'w', encoding='utf-8')
        f.write("# surface heat diffuse bone export.\n")

        amt = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in amt.edit_bones:
            if bone.use_deform:
                world_bone_head = obj.matrix_world @ bone.head
                world_bone_tail = obj.matrix_world @ bone.tail
                f.write("b,{},{},{},{},{},{},{}\n".format(
                    bone.name.replace(",", "\\;"),
                    world_bone_head[0], world_bone_head[1], world_bone_head[2],
                    world_bone_tail[0], world_bone_tail[1], world_bone_tail[2]))
        bpy.ops.object.mode_set(mode='OBJECT')
        f.close()

    def write_mesh_data(self, objs, filepath):
        """Write mesh data to file."""
        f = open(filepath, 'w', encoding='utf-8')
        f.write("# surface heat diffuse mesh export.\n")

        vertex_offset = 0
        for obj in objs:
            for v in obj.data.vertices:
                world_v_co = obj.matrix_world @ v.co
                f.write("v,{},{},{}\n".format(world_v_co[0], world_v_co[1], world_v_co[2]))

            for poly in obj.data.polygons:
                f.write("f")
                for loop_ind in poly.loop_indices:
                    vert_ind = obj.data.loops[loop_ind].vertex_index
                    f.write(",{}".format(vertex_offset + vert_ind))
                f.write("\n")

            vertex_offset += len(obj.data.vertices)
        f.close()

    def read_weight_data(self, objs, filepath):
        """Read weight data from output file and apply to meshes."""
        # Make permulation for all vertices
        vertex_offset = 0
        for obj in objs:
            for index in range(len(obj.data.vertices)):
                self._permulation.append((vertex_offset + index, index, obj))
            vertex_offset += len(obj.data.vertices)

        props = bpy.context.scene.lol_skin_tools
        if props.protect_selected:
            for index in range(len(objs)):
                obj = objs[index]
                self._selected_indices.append([i.index for i in obj.data.vertices if i.select])
                self._selected_group_index_weights.append([])

                for vert_ind in self._selected_indices[index]:
                    for g in obj.data.vertices[vert_ind].groups:
                        self._selected_group_index_weights[index].append(
                            (obj.vertex_groups[g.group].name, vert_ind, g.weight))

        f = open(filepath, 'r', encoding='utf-8')

        bones = []
        for line in f:
            if len(line) == 0:
                continue
            tokens = line.strip("\r\n").split(",")
            if tokens[0] == "b":
                group_name = tokens[1].replace("\\;", ",")
                bones.append(group_name)
                for obj in objs:
                    if obj.vertex_groups.get(group_name) is not None:
                        group = obj.vertex_groups[group_name]
                        obj.vertex_groups.remove(group)
                    obj.vertex_groups.new(name=group_name)
            if tokens[0] == "w":
                group_name = bones[int(tokens[2])]
                index = int(tokens[1])
                vert_ind = self._permulation[index][1]
                weight = float(tokens[3])
                obj = self._permulation[index][2]

                if props.protect_selected and vert_ind in self._selected_indices[objs.index(obj)]:
                    continue
                obj.vertex_groups[group_name].add([vert_ind], weight, 'REPLACE')

        f.close()

        if props.protect_selected:
            for index in range(len(objs)):
                obj = objs[index]
                for (group_name, vert_ind, weight) in self._selected_group_index_weights[index]:
                    obj.vertex_groups[group_name].add([vert_ind], weight, 'REPLACE')

    def modal(self, context, event):
        if event.type == 'ESC':
            self._pid.terminate()
            return self.cancel(context)

        if event.type == 'TIMER':
            if self._pid.poll() is None:
                try:
                    rawline = self._queue.get_nowait()
                except Empty:
                    pass
                else:
                    line = rawline.decode().strip("\r\n")
                    self.report({'INFO'}, line)
            else:
                data_path = get_shd_data_path()
                self.read_weight_data(self._objs, os.path.join(data_path, "untitled-weight.txt"))
                running_time = time.time() - self._start_time
                self.report({'INFO'}, "Complete, running time: {} minutes {} seconds".format(
                    int(running_time / 60), int(running_time % 60)))
                bpy.ops.object.parent_set(type='ARMATURE')
                return self.cancel(context)

        return {'RUNNING_MODAL'}

    def execute(self, context):
        arm_count = 0
        obj_count = 0
        for ob in context.selected_objects:
            if ob.type == 'ARMATURE':
                arm_count += 1
            if ob.type == 'MESH':
                obj_count += 1

        if not (context.mode == 'OBJECT' and arm_count == 1 and obj_count >= 1):
            self.report({'ERROR'}, "Please select one armature and at least one mesh in OBJECT mode")
            return {'CANCELLED'}

        # Check if executable exists
        shd_path = get_shd_bin_path()
        if not os.path.exists(shd_path):
            self.report({'ERROR'}, f"Surface Heat Diffuse executable not found at: {shd_path}")
            return {'CANCELLED'}

        self._objs = []
        self._permulation = []
        self._selected_indices = []
        self._selected_group_index_weights = []

        arm = None
        objs = []

        for ob in context.selected_objects:
            if ob.type == 'ARMATURE':
                arm = ob
            if ob.type == 'MESH':
                objs.append(ob)

        objs.sort(key=lambda obj: obj.name)
        self._objs = objs

        for obj in objs:
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='OBJECT')

        data_path = get_shd_data_path()
        os.makedirs(data_path, exist_ok=True)

        self.write_mesh_data(objs, os.path.join(data_path, "untitled-mesh.txt"))

        context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='OBJECT')

        self.write_bone_data(arm, os.path.join(data_path, "untitled-bone.txt"))

        ON_POSIX = 'posix' in sys.builtin_module_names

        if ON_POSIX:
            os.chmod(shd_path, 0o755)

        def enqueue_output(out, queue):
            for line in iter(out.readline, b''):
                queue.put(line)
            out.close()

        props = context.scene.lol_skin_tools

        self._pid = Popen([
            shd_path,
            "untitled-mesh.txt",
            "untitled-bone.txt",
            "untitled-weight.txt",
            str(props.voxel_resolution),
            str(props.diffuse_loops),
            str(props.sample_rays),
            str(props.max_influences),
            str(props.diffuse_falloff),
            props.edge_sharpness,
            "y" if props.detect_solidify else "n"
        ],
            cwd=data_path,
            stdout=PIPE,
            bufsize=1,
            close_fds=ON_POSIX)

        self._queue = Queue()
        t = Thread(target=enqueue_output, args=(self._pid.stdout, self._queue))
        t.daemon = True
        t.start()

        self._start_time = time.time()
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        context.window_manager.event_timer_remove(self._timer)
        self._objs = []
        self._permulation = []
        self._selected_indices = []
        self._selected_group_index_weights = []
        return {'CANCELLED'}


# =============================================================================
# Utility Operators (Kept from original)
# =============================================================================

def get_bone_segment_distance(point, head, tail):
    """Calculate shortest distance from point to bone segment."""
    pt_on_segment, t = intersect_point_line(point, head, tail)

    if t < 0.0:
        closest = head
    elif t > 1.0:
        closest = tail
    else:
        closest = pt_on_segment

    distance = (point - closest).length
    return distance, closest, t


class LOL_OT_DeleteShapeKeys(Operator):
    """Delete all shape keys from the selected mesh"""
    bl_idname = "lol.delete_shape_keys"
    bl_label = "Delete All Shape Keys"
    bl_description = "Remove all shape keys from selected meshes (LoL doesn't use shape keys)"
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
    bl_label = "Clear Mismatched Vertex Groups"
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

            to_remove = []
            for vg in obj.vertex_groups:
                if vg.name not in bone_names:
                    to_remove.append(vg.name)

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
    bl_label = "Clear All Vertex Groups"
    bl_description = "Remove ALL vertex groups from selected meshes (fresh start before binding)"
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

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        props = context.scene.lol_skin_tools
        target_obj = context.active_object
        source_obj = context.scene.objects.get(props.transfer_source)

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
    bl_label = "Bind Selected to Nearest"
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

        bones = []
        for bone in armature.data.bones:
            if bone.use_deform:
                head_world = mw_arm @ bone.head_local
                tail_world = mw_arm @ bone.tail_local
                bones.append((bone.name, head_world, tail_world))

        if not bones:
            self.report({'ERROR'}, "No deform bones found")
            return {'CANCELLED'}

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


# =============================================================================
# Property Group
# =============================================================================

class LOL_SkinToolsProperties(PropertyGroup):
    """Properties for skin tools"""

    # Surface Heat Diffuse Settings
    voxel_resolution: IntProperty(
        name="Voxel Resolution",
        description="Maximum voxel grid size (higher = more accurate, slower)",
        default=128,
        min=32,
        max=1024
    )

    diffuse_loops: IntProperty(
        name="Diffuse Loops",
        description="Heat diffuse passes = Voxel Resolution * Diffuse Loops",
        default=5,
        min=1,
        max=9
    )

    sample_rays: IntProperty(
        name="Sample Rays",
        description="Ray samples count for heat calculation",
        default=64,
        min=32,
        max=128
    )

    max_influences: IntProperty(
        name="Max Influences",
        description="Maximum bones per vertex (4 is standard for games)",
        default=4,
        min=1,
        max=128
    )

    diffuse_falloff: FloatProperty(
        name="Diffuse Falloff",
        description="Heat diffuse falloff rate",
        default=0.2,
        min=0.01,
        max=0.99
    )

    edge_sharpness: EnumProperty(
        name="Edge Sharpness",
        description="Weight transition sharpness at edges",
        items=[
            ('1', 'Soft', 'Soft weight transitions'),
            ('2', 'Normal', 'Normal weight transitions'),
            ('3', 'Sharp', 'Sharp weight transitions'),
            ('4', 'Sharpest', 'Sharpest weight transitions')
        ],
        default='3'
    )

    protect_selected: BoolProperty(
        name="Protect Selected Weights",
        description="Keep weights on selected vertices unchanged",
        default=False
    )

    detect_solidify: BoolProperty(
        name="Detect Solidify",
        description="Detect solidified clothes (bones must be inside mesh volume)",
        default=False
    )

    # Transfer weights source
    transfer_source: StringProperty(
        name="Source Mesh",
        description="Mesh to transfer weights from"
    )


# =============================================================================
# UI Panel - Now in Aventurine LoL tab
# =============================================================================

class LOL_PT_SkinToolsPanel(Panel):
    bl_label = "Skin Tools"
    bl_idname = "VIEW3D_PT_lol_skin_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Misc LoL Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        layout = self.layout
        layout.label(text="", icon_value=icons.get_icon("icon_54"))

    def draw(self, context):
        layout = self.layout
        props = context.scene.lol_skin_tools

        # Check if Surface Heat Diffuse is available
        shd_available = os.path.exists(get_shd_bin_path())

        # --- Surface Heat Diffuse Section ---
        box = layout.box()
        box.label(text="Surface Heat Diffuse", icon='MOD_ARMATURE')

        if shd_available:
            col = box.column(align=True)
            col.prop(props, "voxel_resolution")
            col.prop(props, "diffuse_loops")
            col.prop(props, "sample_rays")
            col.prop(props, "max_influences")
            col.prop(props, "diffuse_falloff")
            col.prop(props, "edge_sharpness")

            box.separator()
            col = box.column(align=True)
            col.prop(props, "protect_selected")
            col.prop(props, "detect_solidify")

            box.separator()
            row = box.row()
            row.scale_y = 1.5
            row.operator("lol.surface_heat_diffuse", icon='BONE_DATA')
        else:
            box.label(text="Executable not found!", icon='ERROR')
            box.label(text="Download from mesh-online.net")
            box.label(text="or build from source in:")
            box.label(text="Surface-Heat-Diffuse-Skinning-master/")

        layout.separator()

        # --- Cleanup Tools ---
        box = layout.box()
        box.label(text="Cleanup Tools", icon='BRUSH_DATA')

        col = box.column(align=True)
        col.operator("lol.delete_shape_keys", icon='SHAPEKEY_DATA')
        col.operator("lol.clear_all_vertex_groups", icon='GROUP_VERTEX')
        col.operator("lol.clear_mismatched_groups", icon='X')

        layout.separator()

        # --- Transfer Weights ---
        box = layout.box()
        box.label(text="Transfer Weights", icon='MOD_DATA_TRANSFER')
        col = box.column(align=True)
        col.prop_search(props, "transfer_source", context.scene, "objects", text="Source")
        col.operator("lol.transfer_weights", icon='PASTEDOWN')

        layout.separator()

        # --- Manual Tools ---
        box = layout.box()
        box.label(text="Manual Tools", icon='TOOL_SETTINGS')
        col = box.column(align=True)
        col.operator("lol.bind_nearest_bone", icon='BONE_DATA')
        col.operator("lol.debug_weights", icon='INFO')


# =============================================================================
# Registration
# =============================================================================

classes = [
    LOL_SkinToolsProperties,
    LOL_OT_SurfaceHeatDiffuse,
    LOL_OT_DeleteShapeKeys,
    LOL_OT_ClearMismatchedGroups,
    LOL_OT_ClearAllVertexGroups,
    LOL_OT_TransferWeights,
    LOL_OT_BindToNearestBone,
    LOL_OT_DebugWeights,
]

panel_classes = [
    LOL_PT_SkinToolsPanel
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    for cls in panel_classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.lol_skin_tools = PointerProperty(type=LOL_SkinToolsProperties)


def unregister():
    for cls in reversed(panel_classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass

    if hasattr(bpy.types.Scene, 'lol_skin_tools'):
        del bpy.types.Scene.lol_skin_tools


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
